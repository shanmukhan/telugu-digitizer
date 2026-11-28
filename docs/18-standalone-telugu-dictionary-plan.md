# 18 — Standalone Telugu Dictionary on `lahari.org/telugu` — Plan & Estimates

## 1. Current Status

Today, the 186,086-word Telugu lexicon (`models/lexicon/telugu_lexicon.tsv.gz`) is **internal-only**:
- It powers `POST /api/v1/books/{book_id}/pages/{page_number}/autocorrect` behind the scenes.
- It stores only `word`, `weight`, and `source_flags` (not meanings/definitions).
- There is no standalone UI tab, public/in-app search endpoint, definition viewer, or custom word management yet.

## 2. Proposed Standalone Telugu Dictionary Experience

Add a **standalone `📖 Telugu Dictionary` view** directly in the top navigation bar (and bookmarkable via `?view=dictionary` on `https://lahari.org/telugu/`), usable **without uploading or selecting any book**, while also feeding verified custom words directly into OCR Auto-Correct.

### Core Capabilities

1. **Instant Telugu Word Lookup & Prefix Autocomplete**
   - Type in Telugu or use the existing on-screen **Telugu Keyboard (InScript + Phonetic)** already built into the website.
   - Exact headword match, fast prefix suggestions, and source badges (`C.P. Brown Classical`, `Telugu Wiktionary`, `Janapada`, `LibreOffice te_IN`, `Custom`).
2. **Full Meanings & Definitions (Classical + Modern)**
   - Parse and preserve the actual definitions from our open-source dictionaries (not just headwords):
     - **C.P. Brown** (`brown.babylon`): Classical & literary Telugu → English meanings (ideal for *Amuktamalyada* and classical poetry).
     - **Janapada** (`janapada.babylon`): Folk, regional, and idiomatic Telugu meanings.
     - **Telugu Wiktionary** (`wiktionary_telugu.babylon`): Telugu → Telugu meanings & usage notes.
3. **English → Telugu Reverse Search (FTS5)**
   - Search an English word (e.g., `book`, `lotus`, `description`) to find matching Telugu headwords from C.P. Brown and Janapada.
4. **Telugu Spell-Check & "Did you mean?" / Paragraph Checker**
   - Unknown Telugu words automatically show clickable suggestions powered by our visual OCR confusion + suffix/compound matcher (`అష్టాదశవర్ధనలు → అష్టాదశవర్ణనలు`, `పస్తకం → పుస్తకం`).
   - Optional quick **Check Telugu Text** box: paste a sentence or paragraph to verify spelling against all 186k+ words + custom words.
5. **Custom User Dictionary (Persisted in PostgreSQL)**
   - Add missing classical, domain-specific, or proper-noun Telugu words (with optional English/Telugu meaning & notes) via a PostgreSQL table (`custom_dictionary_words`).
   - Backed up automatically every 4 hours via our existing Pi → Mac Mini PostgreSQL backup pipeline.
   - Immediately recognized by both the standalone Dictionary and **`✨ Auto-Correct Page`** so valid classical words in your books are never mis-flagged.
6. **Optional Quick-Lookup While Proofreading**
   - Highlight or click a word inside the Proofreading Editor to open a compact dictionary drawer/modal without losing your place on the page.

---

## 3. Storage & Raspberry Pi Architecture

To keep the Raspberry Pi fast and prevent bloating our 4-hour PostgreSQL backups:

| Data Tier | Storage Engine | Why | Size / RAM Impact |
| --- | --- | --- | --- |
| **Static Reference Dictionary** (186k+ headwords + C.P. Brown / Janapada / Wiktionary definitions + FTS5 index) | Read-only local SQLite DB (`models/lexicon/telugu_dictionary.sqlite`) | Zero bloat in `pg_dump` backups; `< 5 ms` indexed prefix & FTS5 queries; near-zero RAM (~5–10 MB OS page cache); single-file `rsync` deploy to Pi | ~35–55 MB on disk; ~5–10 MB RAM |
| **User Custom Words** (words you add/edit via UI) | PostgreSQL table `custom_dictionary_words` (Alembic migration `0004`) | Durable transactional storage, automatically included in the 4-hour `pg-backup.timer` + Mac Mini sync | Tiny (KB) |

---

## 4. API Design

All endpoints live under `/api/v1/dictionary`:

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/v1/dictionary/stats` | `GET` | Total words, definitions count, per-source breakdown, custom word count |
| `/api/v1/dictionary/search?q=...&mode=auto\|telugu\|english&limit=25` | `GET` | Exact match + prefix matches + English FTS5 reverse search + fuzzy `"did_you_mean"` suggestions |
| `/api/v1/dictionary/word/{word}` | `GET` | Detailed entry: all definitions grouped by source (`C.P. Brown`, `Wiktionary`, `Janapada`, `Custom`), morphological info, related words |
| `/api/v1/dictionary/check-text` | `POST` | Check a pasted Telugu sentence/paragraph and return unknown tokens + ranked spelling suggestions |
| `/api/v1/dictionary/custom` | `GET` / `POST` | List or add a custom Telugu word (+ optional meaning/notes) in PostgreSQL |
| `/api/v1/dictionary/custom/{word_id}` | `DELETE` | Remove a custom word |

---

## 5. Implementation Options & Effort Estimates

### Option A — Full Standalone Telugu Dictionary (Recommended)
Includes **all 6 capabilities** above: SQLite definitions DB (C.P. Brown + Janapada + Wiktionary + LibreOffice), Telugu & English reverse search, spell-checker / "Did you mean?", Custom Words in PostgreSQL (integrated with Auto-Correct), standalone `📖 Dictionary` tab (`?view=dictionary`), and quick-lookup from the Proofreading Editor.

| Workstream | Details | Estimated Effort |
| --- | --- | --- |
| **1. Dictionary SQLite Builder** | Extend build pipeline (`scripts/build_telugu_dictionary_db.py`) to parse & clean Babylon HTML/markup definitions from C.P. Brown, Janapada, and Wiktionary into `models/lexicon/telugu_dictionary.sqlite` with B-tree prefix + FTS5 indexes | ~45–60 min |
| **2. Custom Words DB Migration & Service** | Alembic migration `0004_custom_dictionary_words.py`, `src/services/dictionary_service.py` (SQLite reader + PostgreSQL custom words + `lexicon_service.py` integration) | ~35–45 min |
| **3. REST API Endpoints** | 6 routes + Pydantic schemas in `src/api/routes.py` & `src/api/schemas.py` | ~25–30 min |
| **4. Standalone Web UI (`DictionaryPanel`)** | New `📖 Dictionary` tab in header + `?view=dictionary` URL sync, instant search, Telugu/English mode, definition cards, "Check Telugu Text" mode, "+ Add Custom Word" form, on-screen Telugu keyboard integration, and optional quick-lookup button in `ReviewEditorPanel` | ~50–65 min |
| **5. Automated Tests & Pi Deployment** | Backend pytest tests, Vitest component tests, Vite build, rsync SQLite DB + app to Pi, run Alembic migration on Pi, restart & verify live | ~30–40 min |
| **Total (Option A)** | **Full standalone Telugu dictionary with definitions, English reverse search, spellcheck & custom words** | **~3 to 4 hours** |

### Option B — Lightweight Word & Spelling Lookup Only (No Definitions)
Exposes a standalone `📖 Dictionary` tab over the existing 186,086-word list (`telugu_lexicon.tsv.gz`): word validation, prefix browse, "Did you mean?" suggestions, paragraph spellcheck, and PostgreSQL custom words — **without** C.P. Brown/Wiktionary definition text or English reverse search.

| Scope | Estimated Effort |
| --- | --- |
| Backend endpoints + Custom Words table + Standalone UI tab + Tests & Pi deploy | **~1.5 to 2 hours** |

---

## 6. Verification Plan
1. Verify SQLite query latency (`< 10 ms` on Raspberry Pi ARM64) and confirm `telugu_dictionary.sqlite` does not impact `pg_dump` size or `uvicorn` RAM usage.
2. Run full backend `pytest` (including PostgreSQL migration `0004`), frontend `vitest` + `npm run build`, and Flutter `dart analyze && flutter test`.
3. Deploy to Raspberry Pi (`192.168.1.13`), run `alembic upgrade head`, restart `telugu-digitizer`, and verify `https://lahari.org/telugu/?view=dictionary` live.
