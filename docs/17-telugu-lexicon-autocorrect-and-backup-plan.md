# 17 — Telugu Lexicon, Opt-In OCR Auto-Correction, Batch Page Approval, and Pi-to-Mac Automated Backups

## 1. Executive Summary & Effort Estimate

Proofreading scanned Telugu literary books line by line is slow when every edit requires typing fixes manually, toggling `Save to correction memory`, clicking `Save Correction` per line, and finally approving the page. This plan delivers an end-to-end speedup while preserving the product's core safety invariants (**raw OCR is never overwritten** and **no text is silently auto-mutated without human review**).

### Effort & Delivery Estimate

| Workstream | Scope | Estimated Effort | Risk / Notes |
| --- | --- | --- | --- |
| **1. Local Telugu Lexicon Builder & Corpus** | Reproducible script `scripts/build_telugu_lexicon.py` combining LibreOffice `te_IN.dic`, C.P. Brown classical Telugu dictionary (`brown.babylon`), Telugu Janapada headwords (`janapada.babylon`), and real-world frequency lists (`FrequencyWords`, `wordfrequency.info`) into compressed NFC lexicon `models/lexicon/telugu_lexicon.tsv.gz` + manifest | ~30–40 min | Clean open-source URLs verified (`HTTP 200`); optional `--include-wiktionary` flag for 94 MB Wiktionary dump |
| **2. Telugu Context & OCR Auto-Correct Engine** | `src/services/lexicon_service.py`: SymSpell-style delete-neighborhood index + Telugu morphological suffix tolerance + Telugu visual OCR confusion weighting (`ధ↔ణ`, `స↔న`, `ప↔వ`, `ట↔ల`, vowel signs, virama/anusvara) + sentence/bigram context ranking backed by PostgreSQL approved sentences & `correction_memory` | ~45–60 min | Memory-safe for Raspberry Pi 5 (lazy load, compact compressed lexicon, bounded candidate search) |
| **3. Backend APIs & Smart Correction Memory** | `POST /api/v1/books/{book_id}/pages/{page_number}/autocorrect`, `POST /api/v1/books/{book_id}/pages/{page_number}/batch-save`, and noise-guarded automatic correction-memory capture (`is_safe_auto_memory_rule`) | ~35–45 min | Atomic DB transaction for batch-save + page approval; filters out pure digit/page-number noise like `ర్మ → 43` |
| **4. Web Studio Proofreading UX** | Default `Save to correction memory` to **checked** when a line is edited; add **`Auto-Correct Page`** (opt-in preview into editable drafts with diff/confidence badges + undo) and **`Save All & Approve Page`** (saves every edited draft and approves the entire page in one click) | ~40–50 min | Full Vitest coverage + accessible toolbar (`role="toolbar"`, `role="status"` announcements) |
| **5. Automated Pi → Mac Mini Backups** | Passwordless `scripts/backup_pi_to_mac.sh` + macOS `launchd` LaunchAgent (`org.lahari.telugu-digitizer-backup`, every 4 hours) syncing `/var/backups/postgres/`, live `correction_memory` JSON export, and `workspace/` (`originals/`, `training_crops/`, `exports/`) to `~/Backups/` | ~20–30 min | Compatible with `rpi-setup` `~/Backups/rpi-postgres/`; includes Pi-side 6-hour `pg-backup.timer` override guide |
| **6. Automated Verification & Live Smoke Test** | Backend `pytest`, frontend `vitest` + Vite production build, Flutter `dart analyze` + `flutter test`, and live Pi → Mac backup run | ~20–30 min | Verified locally against PostgreSQL and live Pi `192.168.1.13` |
| **Total** | **Full end-to-end delivery** | **~3–4 hours (single implementation pass)** | Ready to deploy immediately to Raspberry Pi after verification |

---

## 2. Core Design Principles & Invariants

1. **Raw OCR remains immutable:** `ocr_blocks.raw_text` is never overwritten by auto-correction or batch save. All edits remain append-only rows in `review_edits` and materialized latest text in `document_text_blocks`.
2. **Human-in-the-loop opt-in auto-correction:** Auto-correction is triggered explicitly by clicking **`Auto-Correct Page`** (never silently on OCR completion). Proposed fixes populate the editable line drafts with clear change chips (`original → replacement`, source, confidence) so the reviewer can inspect, tweak, undo, or commit the entire page with one click.
3. **Database-backed continuous learning:** Every verified manual correction is persisted in PostgreSQL (`review_edits`, `document_text_blocks`, and `correction_memory`), and approved sentences immediately feed the in-book + global bigram/vocabulary context scorer for future pages and future books.
4. **Classical + modern Telugu awareness:** Literary books (e.g., *Amuktamalyada*) contain classical words (*granthika*), *sandhi* compounds, and agglutinative case suffixes. A naive modern spellchecker would over-correct valid words. We combine C.P. Brown's classical dictionary, Janapada literary headwords, LibreOffice `te_IN`, morphological suffix stripping, and conservative confidence thresholds so valid classical words are left untouched.

---

## 3. Telugu Dictionary & Sentence Context Architecture

### 3.1 Lexicon Sources (`scripts/build_telugu_lexicon.py`)

All sources are fetched reproducibly, normalized to Unicode **NFC**, stripped of non-Telugu punctuation/ASCII noise, filtered to valid Telugu script tokens (`[\u0C00-\u0C7F]+`), deduplicated, and ranked with composite frequency weights:

| Source | Domain Coverage | License / Origin | Weighting Role |
| --- | --- | --- | --- |
| `LibreOffice/dictionaries` (`te_IN/te_IN.dic`) | Curated modern Telugu dictionary & inflections | GPL/LGPL/MPL (LibreOffice) | Core curated base lexicon |
| `indic-dict/stardict-telugu` (`brown/brown.babylon`) | C.P. Brown Classical Telugu-English headwords | Open-source StarDict corpus | Classical / literary / *granthika* vocabulary |
| `indic-dict/stardict-telugu` (`janapada/janapada.babylon`) | Telugu folk, regional, and literary vocabulary | Open-source StarDict corpus | Extended literary & colloquial coverage |
| `hermitdave/FrequencyWords` (`2018/te/te_full.txt`) | Real-world Telugu word frequencies | MIT / CC-BY-SA | Primary frequency prior for ranking candidates |
| `frekwencja/most-common-words-multilingual` (`te.txt`) | High-frequency contemporary Telugu words | Open corpus | Boost for common everyday vocabulary |
| `wiktionary_telugu.babylon` (`--include-wiktionary`, enabled in built lexicon) | Telugu Wiktionary headwords (`78,552` unique Telugu tokens) | CC-BY-SA | Broad modern, Sanskritized, & classical coverage |

Output artifacts stored in `models/lexicon/`:
- `models/lexicon/telugu_lexicon.tsv.gz` — gzipped UTF-8 TSV (`word\tfreq\tsource_flags`), **186,086 NFC Telugu words** (`0.88 MB` compressed, fast to deploy to Raspberry Pi).
- `models/lexicon/manifest.json` — build timestamp, per-source word counts, total unique NFC words, SHA-256 checksum.

### 3.2 Multi-Layer Auto-Correction Pipeline (`src/services/lexicon_service.py`)

When the user triggers **`Auto-Correct Page`**, each non-ignored block on the page is analyzed left-to-right across three ranked layers:

1. **Layer 1 — Database `correction_memory` (Highest Priority, Confidence `0.95–0.99`)**
   - Uses active rules (`book_only` for the current book and `global_suggestion` across books) via the existing contextual matcher (`left_context`, `right_context`, `approved_count > rejected_count`, and no unresolved conflicting rule).
   - Supports 1–4 token spans and preserves leading/trailing punctuation.

2. **Layer 2 — Telugu Lexicon + Visual OCR Confusion Matcher (Confidence `0.78–0.94`)**
   - Skips tokens that are:
     - Non-Telugu (ASCII, digits, pure punctuation) or very short (`len < 3` codepoints).
     - Already present in the **static Telugu lexicon** OR present in **verified DB vocabulary** (`document_text_blocks` & `correction_memory.corrected_text`).
     - Recognized as a valid **suffix-inflected form** (stem in lexicon + common Telugu case/plural/postposition suffixes such as `లు`, `ను`, `ని`, `కి`, `కు`, `లో`, `తో`, `చే`, `చేత`, `పై`, `గా`, `ైన`, `యొక్క`, `వల్ల`, `కొరకు`, `నుండి`, `నుంచి`, `అని`, `కూడా`).
     - Recognized as a valid **two-part compound** (left stem ≥ 3 chars + right stem ≥ 3 chars both in lexicon, covering common *samāsa* compounds like `అష్టాదశ` + `వర్ణనలు`).
   - For unknown Telugu tokens, generates candidates via a **SymSpell-style 1-delete + 2-delete neighborhood index** (and targeted Telugu OCR confusion substitutions), then scores each candidate with a **weighted Telugu OCR edit distance**:
     - Low substitution cost (`0.30–0.45`) for known Telugu OCR confusions:
       - Consonants: `ధ↔ణ`, `స↔న`, `ప↔వ`, `ట↔ల`, `త↔న`, `క↔ర`, `గ↔ర`, `మ↔య`, `చ↔ద`, `భ↔ధ`, `ఖ↔ర`, `ళ↔ల`, `ష↔స`, `శ↔స`, `ఱ↔ర`
       - Vowel signs (గుణింతాలు): `ె↔ే`, `ొ↔ో`, `ి↔ీ`, `ు↔ూ`, `ృ↔ు`, `ా↔ో`, `ై↔ె`
       - Diacritics: missing/extra `ం` (anusvara), `్` (virama/halant), `ః` (visarga)
     - Standard cost (`1.0`) for arbitrary edits.
   - Only accepts candidates whose weighted OCR cost is small (`<= 1.15`, or `<= 1.45` for longer words `>= 7` chars) and whose confidence clears `min_confidence` (default `0.78`).

3. **Layer 3 — Sentence / Bigram Context Disambiguation ("Possible Best Sentences")**
   - Builds an in-memory **Telugu word & bigram model** on demand from:
     - Approved/edited blocks in the current book (`document_text_blocks` + `review_edits`), weighted higher for domain coherence (*Amuktamalyada* style/names/terminology).
     - Approved blocks across all books in PostgreSQL (`document_text_blocks` where `block_role != 'ignore'`).
     - Contextual pairs (`left_context → corrected_text`, `corrected_text → right_context`) from `correction_memory`.
   - When multiple dictionary candidates compete for an unknown token $w_i$, each candidate $c$ is scored by combining:
     $$\text{score}(c \mid w_{i-1}, w_{i+1}) = -\alpha \cdot d_{\text{OCR}}(w_i, c) + \beta \cdot \log_{10}(\text{freq}(c) + 1) + \gamma \cdot \text{bigram\_bonus}(w_{i-1}, c, w_{i+1}) + \delta \cdot \text{book\_vocab\_bonus}(c)$$
   - If the top candidate clearly beats the runner-up (margin check) and clears the confidence threshold, it is proposed; ambiguous ties are skipped to avoid false positives.

---

## 4. Smart `Save to Correction Memory` Default & Noise Guard

To eliminate repetitive checkbox clicking while keeping `correction_memory` clean:

1. **Web UI Default:** Whenever a block has unsaved manual text edits, `Save to correction memory` starts **checked (`true`)** by default (with scope `book_only`). The user can still uncheck it or change scope to `global_suggestion` before saving.
2. **Backend Noise Guard (`is_safe_auto_memory_rule`):**
   - When saving edits in batch (or when `auto_filter_noise=True` on single-block save), automatically skip creating a `correction_memory` rule if:
     - `corrected_span` is purely digits/numerals/punctuation (e.g., `ర్మ → 43`, page numbers, bullet markers), OR
     - `incorrect_span` has no Telugu letters, OR
     - The span rewrite is too broad (`> 2` tokens in `incorrect_span` or `> 3` tokens in `corrected_span`, or `len > 45` chars) — such edits are full-line restructurings rather than reusable OCR typo rules, OR
     - `incorrect_span == corrected_span` after NFC normalization.
   - Explicit single-block saves with `incorrect_span`/`corrected_span` supplied manually bypass the noise filter.
   - Regardless of whether a `correction_memory` rule is added, the edited text itself is **always** persisted in `review_edits` and `document_text_blocks` in PostgreSQL.

---

## 5. REST API Contracts

### 5.1 `POST /api/v1/books/{book_id}/pages/{page_number}/autocorrect`

Computes non-destructive auto-correction proposals for the page (does **not** mutate the database).

**Request:**
```json
{
  "primary_run_id": "uuid-or-null",
  "use_correction_memory": true,
  "use_dictionary": true,
  "use_sentence_context": true,
  "min_confidence": 0.78,
  "current_texts": {
    "block-uuid": "optional unsaved draft text"
  }
}
```

**Response (`200 OK`):**
```json
{
  "book_id": "uuid",
  "page_number": 7,
  "primary_run_id": "uuid",
  "lexicon_word_count": 185420,
  "total_blocks_scanned": 24,
  "changed_blocks_count": 6,
  "total_changes_count": 9,
  "blocks": [
    {
      "block_id": "uuid",
      "original_text": "అష్టాదశవర్ధనలు",
      "proposed_text": "అష్టాదశవర్ణనలు",
      "changes": [
        {
          "original": "అష్టాదశవర్ధనలు",
          "replacement": "అష్టాదశవర్ణనలు",
          "source": "dictionary_context",
          "confidence": 0.91,
          "reason": "Telugu OCR confusion (ధ→ణ) + lexicon match"
        }
      ]
    }
  ]
}
```

### 5.2 `POST /api/v1/books/{book_id}/pages/{page_number}/batch-save`

Atomically saves all edited/auto-corrected blocks on a page, records noise-filtered corrections into `correction_memory`, captures `TrainingSample` crops (when `training_consent=True`), optionally approves all remaining unignored blocks, and optionally marks the entire page `approved` in **one transaction**.

**Request:**
```json
{
  "primary_run_id": "uuid-or-null",
  "edits": [
    {
      "block_id": "uuid",
      "edited_text": "అష్టాదశవర్ణనలు - 43",
      "block_role": "paragraph",
      "add_to_correction_memory": true,
      "memory_scope": "book_only",
      "correction_type": null,
      "review_note": "Auto-correct reviewed & approved"
    }
  ],
  "approve_remaining_blocks": true,
  "mark_page_approved": true
}
```

**Response (`200 OK`):**
```json
{
  "book_id": "uuid",
  "page_number": 7,
  "saved_edits_count": 6,
  "approved_blocks_count": 18,
  "correction_memory_created_count": 4,
  "correction_memory_skipped_noise_count": 2,
  "page_review_status": "approved"
}
```

---

## 6. Web Studio Proofreading Workflow

In [ReviewEditorPanel.tsx](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/frontend/src/components/ReviewEditorPanel.tsx):

1. **Toolbar actions:**
   - **`✨ Auto-Correct Page`**: Calls `POST .../autocorrect`, populates proposed fixes into the line drafts, shows a clear summary banner (e.g., *"Auto-corrected 6 line(s) (9 fix(es)) into drafts — review and click Save All & Approve Page"*), renders compact diff badges on each modified card (`original → replacement · Dictionary/Memory · 91%`), and provides a **`Revert Auto-Correct`** button if the reviewer wants to discard all uncommitted auto-fixes in one click.
   - **`✓ Save All & Approve Page`** (replaces/enhances the plain `Approve Page` button when there are unsaved drafts or pending lines): Calls `POST .../batch-save` with every modified block (respecting per-block `Save to correction memory` checkbox, scope, and block role), approves remaining unignored lines, and marks the page `approved` in a single request.
   - Existing **`Approve Page`** behavior remains seamless when there are 0 unsaved edits.
2. **Per-block default:**
   - `Save to correction memory` defaults to **checked (`true`)** whenever a line is modified manually or via auto-correct.
   - Unchecking it on a specific line opts that line out of `correction_memory` while still saving the edit to the page.

---

## 7. Automated Pi → Mac Mini Frequent Backup Architecture

To protect PostgreSQL data (all books, OCR runs, human edits, `correction_memory`, `training_samples`) and uploaded PDFs/crops against Raspberry Pi SD/SSD failures:

### 7.1 What Gets Backed Up
1. **PostgreSQL dumps (`/var/backups/postgres/` → `~/Backups/rpi-postgres/`):**
   - Uses existing `pgbackup` group permissions on `lipi@192.168.1.13` (100% passwordless over SSH key — no `sudo` required).
   - Preserves compatibility with `rpi-setup/docs/16-backups-and-restore.md`.
2. **Live `correction_memory` + Books metadata JSON snapshot (`~/Backups/telugu-digitizer/snapshots/`):**
   - Fetches `/api/v1/corrections` and `/api/v1/books` directly from the Pi API (`http://192.168.1.13:8085` with fallback to `https://lahari.org/telugu`) on every backup run so even mid-day edits between `pg_dump` runs are safely captured on the Mac Mini (30-day rolling retention).
3. **Workspace files (`/home/lipi/telugu-digitizer/workspace/` → `~/Backups/telugu-digitizer/workspace/`):**
   - Incremental `rsync` of `originals/` (source PDFs), `training_crops/`, and `exports/` (skipping bulky regenerable `pages/` PNG renders by default, configurable via env flag).

### 7.2 Schedule & Automation
- **Mac Mini (`launchd`):** `scripts/install_mac_backup_agent.sh` installs `~/Library/LaunchAgents/org.lahari.telugu-digitizer-backup.plist`, running `scripts/backup_pi_to_mac.sh` **every 4 hours (`StartInterval = 14400`)** plus immediately at login/load, logging to `~/Backups/telugu-digitizer/backup.log`.
- **Optional Raspberry Pi DB dump frequency increase (6-hour `pg_dump`):**
  Currently the Pi runs `pg-backup.timer` daily at `02:30`. To refresh `/var/backups/postgres/telugu_digitizer_*.dump` every 4–6 hours on the Pi itself, run once on the Pi:
  ```bash
  sudo systemctl edit pg-backup.timer
  # Add:
  # [Timer]
  # OnCalendar=
  # OnCalendar=00/4:15:00
  sudo systemctl daemon-reload && sudo systemctl restart pg-backup.timer
  ```

---

## 8. Verification Plan

1. **Lexicon build verification:** Run `python3 scripts/build_telugu_lexicon.py` and verify word count, NFC normalization, classical words (`అష్టాదశ`, `వర్ణనలు`, `ఆముక్తమాల్యద`), and file size.
2. **Backend unit & integration tests:** New `tests/test_lexicon_and_autocorrect.py` covering lexicon loading, Telugu suffix tolerance, OCR confusion fixing (`అష్టాదశవర్ధనలు → అష్టాదశవర్ణనలు`, `పస్తకం → పుస్తకం`), bigram sentence context disambiguation, noise guard (`ర్మ → 43` skipped from `correction_memory`), `POST .../autocorrect`, and `POST .../batch-save` atomic approval; plus full `.venv/bin/pytest -v`.
3. **Frontend & Mobile tests:** Update `ReviewEditorPanel.test.tsx` for default-checked correction memory, `Auto-Correct Page`, and `Save All & Approve Page`; run `npm test && npm run build` and `dart analyze --fatal-infos && flutter test`.
4. **Live backup verification:** Install LaunchAgent and execute `scripts/backup_pi_to_mac.sh` against `lipi@192.168.1.13`, verifying PostgreSQL dumps, JSON snapshots, and workspace files land in `~/Backups/`.
