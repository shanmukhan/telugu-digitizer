# 15 — UI/UX, Workflow & OCR Engine Gap Analysis and Roadmap

Comprehensive audit of functional gaps, edge-case bugs, workflow limitations, and OCR/export engine improvements across the `telugu-digitizer` repository (Web Studio, Flutter Mobile App, FastAPI Backend, OCR Pipeline, Correction Memory, and Document Export).

> **Note:** Performance, N+1 SQL query, caching, and bundle-splitting bottlenecks were audited and resolved in [docs/14-performance-audit-and-improvements.md](14-performance-audit-and-improvements.md). This document focuses on **product UI/UX, workflow completeness, OCR accuracy/engine capabilities, and specification gaps**.

---

## 1. Executive Summary of High-Priority Gaps

| # | Area | Finding / Gap | Severity | Primary Files Affected |
|---|---|---|---|---|
| 1 | **Workflow / Lifecycle** | Queued OCR runs (`status = "queued"`) are orphaned forever if the server restarts, and running OCR jobs cannot be cancelled. | **High** | `src/api/app.py`, `src/services/ocr_service.py` |
| 2 | **PDF / OCR Engine** | Legacy non-Unicode Telugu PDFs (Anu, Shree-Lipi, PUA fonts) are misclassified as `digital_text`, skipped by OCR, and rendered as garbled ASCII. | **High** | `src/pdf/rasterizer.py`, `frontend/src/components/ReviewEditorPanel.tsx` |
| 3 | **Review UI & API** | Reviewers cannot insert a missed OCR line, delete a false-positive noise box, split/merge lines, or reorder reading sequence. | **High** | `src/api/routes.py`, `src/services/review_service.py`, `frontend/src/components/ReviewEditorPanel.tsx` |
| 4 | **Export & Layout** | Every OCR text line (`text_line`) is exported as a separate Word paragraph (`<w:p>` with 6pt spacing), and reviewers cannot classify blocks as Headings (`Heading 1`/`2`) so the DOCX Table of Contents is always empty. | **High** | `src/services/export_service.py`, `src/services/review_service.py` |
| 5 | **Correction Memory** | Saving the same correction creates duplicate rows instead of incrementing `approved_count`; whitespace-only tokenization misses words adjacent to punctuation (`"పస్తకం,"`). | **Medium** | `src/services/correction_service.py` |
| 6 | **Data Architecture** | `DocumentTextBlock` is written on edit/approval but ignored during review and export; `TrainingSample` (`training_samples` table) is never populated even when `training_consent = true`. | **Medium** | `src/services/review_service.py`, `src/services/export_service.py`, `src/db/models.py` |
| 7 | **Mobile App (`mobile/`)** | Android/iOS cleartext HTTP (`http://192.168.1.13:8085`) is blocked by default OS network security policies; mobile editor lacks Undo/Redo and custom page range inputs. | **Medium** | `mobile/android/app/src/main/AndroidManifest.xml`, `mobile/ios/Runner/Info.plist`, `mobile/lib/ui/` |

---

## 2. UI/UX Gaps & Improvements

### 2.1 Web Proofreading Studio (`frontend/src/`)

1. **No Block Creation, Deletion, Split/Merge, or Reordering (`ReviewEditorPanel.tsx`, `SourcePageViewer.tsx`)**
   - **Current behavior:** Reviewers can only edit the text of existing `OCRBlock` records (`POST /api/v1/ocr-blocks/{block_id}/edits`).
   - **Real-world issue:**
     - Printed Telugu pages frequently have faded lines that the detector misses completely (no bounding box created) or ornamental borders/stains that produce false-positive garbage blocks.
     - Multi-column or verse layouts often have two columns merged into a single horizontal line or one sentence split awkwardly across blocks.
   - **Improvement:**
     - Add endpoints and UI actions to **Insert Line Below**, **Merge with Next Line**, **Split Line at Cursor**, **Delete/Ignore False-Positive Block** (soft-delete action `"ignored"` in `ReviewEdit` so raw OCR remains immutable), and **Move Line Up/Down** (`reading_order`).
     - Allow drawing a bounding box on the scan canvas in `SourcePageViewer.tsx` to add a missed region.

2. **Born-Digital (`digital_text`) and Mixed Pages Are Read-Only in the Editor (`ReviewEditorPanel.tsx:588-597`)**
   - **Current behavior:** When `review.page_kind === "digital_text"`, `ReviewEditorPanel` renders `<pre>{review.digital_text_content}</pre>` with no editing controls and no way to trigger OCR for that page from the UI.
   - **Real-world issue:** Even born-digital PDFs often contain typos, broken ligatures, or legacy font encodings that need human correction or forced OCR.
   - **Improvement:**
     - Make `digital_text` pages editable (saving into `DocumentTextBlock`), and expose a **"Force OCR on Digital Pages"** (`include_digital_text_pages: true`) checkbox in the sidebar OCR panel.

3. **Backend OCR Options Hidden from the UI (`frontend/src/api/client.ts:91-110`, `App.tsx:814-929`)**
   - **Current behavior:** The backend `POST /api/v1/books/{book_id}/ocr-runs` endpoint supports `render_dpi` (150–600), `tesseract_psm` (3–13), `include_digital_text_pages`, and `force_rerun`, but `startOcrRun()` in `frontend/src/api/client.ts` hardcodes `render_dpi: 300`, `preprocessing_profile: "none"`, `force_rerun: false`, and omits `tesseract_psm` and `include_digital_text_pages`.
   - **Improvement:**
     - Add an **"Advanced OCR Options"** `<details>` disclosure in the sidebar allowing users to configure:
       - **Force re-run** (`force_rerun: true`)
       - **Include digital-text pages** (`include_digital_text_pages: true`)
       - **Render DPI** (`300 DPI` default, `400 DPI` for small print/footnotes)
       - **Tesseract Page Segmentation Mode (`--psm`)** (`6` single uniform block vs `3` fully automatic multi-column vs `4` single column of variable sizes)

4. **No Character-Level Visual Diff Between Primary & Comparator Engines (`ReviewEditorPanel.tsx:148-174`)**
   - **Current behavior:** When PaddleOCR and Tesseract disagree (`block.disagreement_flag`), the UI shows `block.raw_text` and `block.comparator_text` in two separate boxes. On long Telugu lines, spotting a single differing *matra* (*గుణింతం*) or *ottu* requires careful manual scanning.
   - **Improvement:**
     - Render an inline grapheme-cluster diff (highlighting differing Telugu *aksharas* in the comparator box) and allow clicking individual words from the comparator to splice them into the draft without replacing the entire line.

5. **No "Approve All Unflagged Lines" or Keyboard Page Navigation**
   - **Current behavior:** Reviewers can approve one block at a time (`Approve Block` / `Ctrl+Enter`) or approve the entire page (`Approve Page`), which also approves unreviewed flagged lines.
   - **Improvement:**
     - Add an **"Approve All Unflagged Lines"** button in the editor toolbar so reviewers can bulk-approve high-confidence lines where both engines agree, leaving only flagged lines for manual inspection.
     - Add keyboard shortcuts for page navigation (`Alt+Left` / `Alt+Right`) and moving between blocks (`Alt+Up` / `Alt+Down`).

6. **Book Metadata & Rights Cannot Be Viewed or Edited After Upload (`BookUploadForm.tsx`, `src/api/routes.py`)**
   - **Current behavior:** `BookUploadForm.tsx` omits `publisher`, `publication_year`, and `rights_status` (even though the database and `POST /api/v1/books` schema support them), and there is no `PATCH /api/v1/books/{book_id}` endpoint to edit title, author, orthography profile, or training consent after import.

---

### 2.2 Flutter Mobile App (`mobile/`)

1. **Android & iOS Cleartext HTTP Policy Blocks LAN Raspberry Pi URLs (`mobile/android/`, `mobile/ios/`)**
   - **Current behavior:** `ServerSettingsSheet` (`mobile/lib/ui/features/studio/views/server_settings_sheet.dart:93-104`) provides one-tap presets for `http://192.168.1.13:8085` (Pi LAN) and `http://127.0.0.1:8000`.
   - **Issue:**
     - Android 9+ blocks cleartext `http://` connections by default unless `android:usesCleartextTraffic="true"` or a `network_security_config.xml` is declared in `mobile/android/app/src/main/AndroidManifest.xml`.
     - iOS App Transport Security (ATS) blocks non-HTTPS connections to LAN IPs unless `NSAllowsLocalNetworking` / `NSAllowsArbitraryLoads` is configured in `mobile/ios/Runner/Info.plist`.
   - **Improvement:**
     - Add `android:usesCleartextTraffic="true"` to `AndroidManifest.xml` and `NSAllowsLocalNetworking` under `NSAppTransportSecurity` in `Info.plist` so LAN connections to a local Raspberry Pi work out of the box alongside `https://lahari.org/telugu`.

2. **Parity Gaps Between Mobile and Web Proofreading Studio**
   - **Missing Undo/Redo stack:** Web `ReviewEditorPanel.tsx` maintains an in-memory `undoStack` / `redoStack`, whereas `mobile/lib/ui/features/studio/views/page_review_tab_view.dart` does not yet have Undo/Redo buttons.
   - **Missing custom page-range OCR input:** Mobile `LibraryTabView` offers `Test Pages 1–5` and `Run Full Book`, but lacks start/end page number text fields for running OCR on arbitrary chapters (e.g., pages 10–25).
   - **Auto-scroll to selected block:** Tapping a polygon in `_ScanOverlayPane` updates `viewModel.selectedBlockId`, which highlights the card border in `ListView.builder`, but does not automatically scroll the `ListView` to bring an off-screen block card into view.
   - **Phonetic Transliteration Composer on Mobile:** Mobile `PageReviewTabView` includes the quick combining signs (*గుణింతాలు*) bar, while the Web app also includes a Roman-to-Telugu phonetic composer (`teluguTranslit.ts`). Porting `transliterateTeluguPhonetic` to Dart would let mobile users type Romanized Telugu when an OS Telugu keyboard is not installed.

---

## 3. Workflow & Architecture Gaps

### 3.1 Orphaned `"queued"` Runs on Server Restart (`src/api/app.py:42-56`)
- **Location:** `src/api/app.py` (lines 42–56)
- **Issue:**
  - During startup (`lifespan`), the application recovers runs where `OCRRun.status == "running"` and `ProcessingJob.status == "running"` by setting them to `"partial"` so the user can resume them.
  - However, when a user starts dual-engine OCR (`PaddleOCR` + `Tesseract`), Run 1 transitions to `"running"` while Run 2 stays `"queued"` waiting for the single worker thread in `OCRJobExecutor`.
  - If the server or Raspberry Pi restarts while Run 1 is running, Run 1 becomes `"partial"`, **but Run 2 remains `"queued"` in PostgreSQL forever** with no active thread in `ThreadPoolExecutor`. Because the UI only shows the `Resume` button for `"partial"` or `"failed"` runs (`App.tsx:556`), Run 2 is permanently stuck in `"OCR Queued"` state!
- **Recommended Fix:**
  - In `lifespan` (`src/api/app.py:47-53`), include `status.in_(["running", "queued"])` when resetting interrupted runs to `"partial"` (or automatically re-submit `"queued"` runs to `executor.submit_runs(...)` on startup).

### 3.2 No Way to Cancel or Abort a Running/Queued OCR Job (`src/services/ocr_service.py`)
- **Location:** `src/services/ocr_service.py` (`OCRJobExecutor`, lines 212–475)
- **Issue:**
  - On Raspberry Pi CPU, PaddleOCR takes ~90 seconds per page. If a user accidentally starts a 300-page full-book PaddleOCR run (~7.5 hours), there is no `POST /api/v1/ocr-runs/{run_id}/cancel` endpoint and no `Cancel` button in the UI.
  - Because `ThreadPoolExecutor(max_workers=1)` processes runs sequentially, every subsequent job (even a 2-second Tesseract run) is blocked behind the multi-hour job.
- **Recommended Fix:**
  - Track a thread-safe `_cancelled_runs: set[uuid.UUID]` in `OCRJobExecutor`, check it before each page in `execute_run()`, cancel pending `Future` objects for queued runs, mark the run `"partial"` (preserving pages completed so far), and expose a `Cancel / Pause OCR` button in `OcrProgressStrip`.

### 3.3 `DocumentTextBlock` Is Written on Edit/Approve, But Ignored by Review and Export
- **Locations:**
  - `src/services/review_service.py` (`submit_block_edit` lines 391–411, `update_page_review_status` lines 490–536)
  - `src/services/export_service.py` (`_collect_export_pages` lines 162–264)
- **Issue:**
  - Whenever a reviewer edits a block or approves a page, `review_service.py` creates a `DocumentTextVersion` (`origin="human_approved"`) and upserts `DocumentTextBlock` rows containing `final_text`, `reading_order`, and `block_role`.
  - Yet `_collect_export_pages()` in `export_service.py` only looks up `DocumentTextVersion` to record `version_row.id` in the export manifest—**it never queries `DocumentTextBlock`**! Instead, it queries `OCRBlock` and `ReviewEdit` for a single `selected_run`.
  - If a reviewer edited blocks on Run A (e.g., Tesseract) on pages 1–5 and edited blocks on Run B (e.g., PaddleOCR) on pages 6–10, `DocumentTextBlock` has the unified human transcript across all pages, whereas `_collect_export_pages()` only exports edits attached to whichever single `OCRRun` was selected as `selected_run`.
- **Recommended Fix:**
  - Use `DocumentTextBlock` as the authoritative source for approved pages when `text_version == "human_approved"`, falling back to `OCRBlock` + `ReviewEdit` only for unapproved pages.

### 3.4 `TrainingSample` Collection (`training_samples` Table) Is Unimplemented
- **Locations:**
  - `src/db/models.py` (`TrainingSample`, lines 273–292)
  - `docs/08-correction-memory-and-learning.md` (§3 & §7)
- **Issue:**
  - Users can opt into `"Allow verified crops for future OCR training"` (`Book.training_consent = True`), and the database schema includes the `training_samples` table (`image_crop_storage_key`, `image_crop_sha256`, `ocr_text`, `verified_text`, `annotation_status`, `allowed_for_training`).
  - However, no service code ever crops the polygon/bbox from the page PNG or inserts rows into `training_samples` when a reviewer corrects or approves a block on a consented book.
- **Recommended Fix:**
  - When a page or block is approved on a book with `book.training_consent == True` and a valid `bbox`/`polygon`, crop the line region from the 300-DPI page PNG using Pillow, save it under `workspace/training_crops/{book_id}/{block_id}.png`, and upsert a `TrainingSample` row.

### 3.5 Correction Memory Deduplication, Punctuation Matching & Scope Promotion (`src/services/correction_service.py`)
- **Locations:**
  - `src/services/correction_service.py` (`create_correction_memory_entry` lines 108–167, `find_block_suggestions_from_index` lines 259–327)
- **Issues:**
  1. **Duplicate rows on repeated saves:** Calling `create_correction_memory_entry()` with an existing `(language_code, incorrect_text, corrected_text, left_context, right_context, scope, book_id)` always inserts a duplicate `CorrectionMemory` row with `approved_count = 1` instead of incrementing `approved_count` on the existing active record.
  2. **Punctuation prevents token matching:** `find_block_suggestions_from_index()` splits `block_text` purely on whitespace (`tokens = block_text.split()`). If `incorrect_text` in memory is `"పస్తకం"`, it will **not** match `"పస్తకం,"`, `"పస్తకం."`, or `"(పస్తకం)"` in a line of prose.
  3. **No scope promotion (`book_only` → `global_suggestion`):** `PATCH /api/v1/corrections/{id}/status` only updates `status`, with no way to promote a useful `book_only` rule to `global_suggestion`.
- **Recommended Fixes:**
  - Upsert in `create_correction_memory_entry()` when an identical active rule already exists.
  - Strip leading/trailing punctuation (`.,!?;:"'()[]{}—–`) when matching candidate n-gram spans while preserving the punctuation when constructing `proposed_block_text`.
  - Allow updating `scope` in `PATCH /api/v1/corrections/{id}/status` (or a dedicated `scope` field).

---

## 4. OCR Engine, PDF Classification & Export Quality Gaps

### 4.1 Legacy Non-Unicode Telugu Font PDFs Are Misclassified as Valid `digital_text` (`src/pdf/rasterizer.py:18-49`)
- **Location:** `src/pdf/rasterizer.py` (`classify_and_extract_pdf_page`, lines 18–49)
- **Issue:**
  - `classify_and_extract_pdf_page()` classifies any PDF page with `char_count >= 25` and `image_coverage_ratio < 0.15` as `"digital_text"`.
  - A large proportion of pre-2015 digital Telugu PDFs use **legacy proprietary font encodings** (Anu Script Manager, Shree-Tel, Apple/Priya, or PUA glyphs) where the PDF text layer contains dozens of Latin/ASCII or Private Use Area characters (`char_count >= 25`) that render visually as Telugu in the PDF viewer, **but contain zero Unicode Telugu codepoints (`U+0C00..U+0C7F`)** when extracted via `page.get_text("text")`!
  - Currently, these pages are marked `"digital_text"`, skipped by OCR, and exported directly into DOCX/TXT as unreadable Latin gibberish.
- **Recommended Fix:**
  - In `classify_and_extract_pdf_page()`, compute the Telugu Unicode character ratio (`sum(1 for ch in extracted if '\u0c00' <= ch <= '\u0c7f') / max(char_count, 1)`).
  - If `char_count >= 25` but the Telugu Unicode ratio is below a threshold (e.g. `< 0.20` on a `language_code == "te"` book), classify the page as `"scanned_image"` (or `"legacy_font_scan"`) so it is automatically routed through 300-DPI rasterization and visual Telugu OCR!

### 4.2 Image Preprocessing Profiles Are Stubbed Out (`src/services/ocr_service.py:485-490`)
- **Location:** `src/services/ocr_service.py` (lines 485–490)
- **Issue:**
  - `create_or_reuse_ocr_runs()` rejects any `preprocessing_profile != "none"` with `400 UNSUPPORTED_PREPROCESSING`.
  - Old printed Telugu books often suffer from page skew (tilted scans), uneven illumination/shadow near the book spine, or low contrast on yellowed paper. Skewed lines degrade both Tesseract's LSTM line finder and PaddleOCR's horizontal bounding boxes.
- **Recommended Fix:**
  - Implement non-destructive OpenCV preprocessing profiles (saving derived images under `workspace/pages/{book_id}/pre-{profile}/page-NNNN.png` without touching the original render):
    - `deskew`: Estimate page skew angle via projection profile or `cv2.minAreaRect` on text contours and rotate only when `|angle| > 0.5°`.
    - `contrast_clahe`: Grayscale + mild CLAHE contrast normalization without hard binarization (preserving delicate Telugu *talakattu*, *ottulu*, and vowel signs).

### 4.3 Multi-Column Reading Order & Paragraph Reconstruction in DOCX Export (`src/services/export_service.py:341-358`)
- **Locations:**
  - `src/ocr/paddle_provider.py` (lines 171–182)
  - `src/ocr/tesseract_provider.py` (lines 55–75)
  - `src/services/export_service.py` (`_build_docx_bytes`, lines 341–358)
- **Issues:**
  1. **Every OCR line becomes a separate paragraph in Word:** Each `OCRBlock` has `block_type = "text_line"`. In `_build_docx_bytes()`, every block calls `doc.add_paragraph()` with `space_after = Pt(6)`. A 35-line printed prose page produces 35 separate single-line paragraphs in Word instead of flowing continuous prose paragraphs!
  2. **Heading styles and Table of Contents:** Even when `include_table_of_contents=True` is selected in `editable_flow` mode, `_build_docx_bytes()` never emits `Heading 1`, `Heading 2`, or `Heading 3` paragraphs for book chapters/sections because `OCRBlock` / `ReviewBlock` has no UI or API to set `block_role` (`heading_1`, `heading_2`, `paragraph`, `verse`, `footnote`, `page_header_footer`).
  3. **Running headers / page numbers merged into body flow:** In `editable_flow` DOCX mode, running page headers and printed page numbers at the top/bottom of each scanned page are exported inline in the middle of sentences spanning page boundaries.
- **Recommended Fixes:**
  - Add a `block_role` selector (`paragraph`, `heading_1`, `heading_2`, `verse`, `header_footer_ignore`) on each block in the Review UI and `POST /api/v1/ocr-blocks/{block_id}/edits`.
  - In `_build_docx_bytes()`:
    - Skip `header_footer_ignore` blocks in `editable_flow` mode.
    - Render `heading_1` / `heading_2` blocks using `doc.add_heading(..., level=1|2)` so the Word Table of Contents populates automatically.
    - In `editable_flow` mode, join consecutive `paragraph` lines using vertical spacing / indentation and terminal punctuation heuristics (while keeping `verse` lines separate).

### 4.4 Phase 1 Gold Benchmark Dataset Is Empty (`data/gold/`)
- **Locations:**
  - `data/gold/` (currently contains only `.gitkeep`)
  - `docs/05-benchmark-methodology.md`, `docs/12-acceptance-criteria.md`
- **Issue:**
  - The Phase 1 evaluation harness (`scripts/benchmark.py`, `src/evaluation/metrics.py`, `src/evaluation/report.py`) is fully implemented and tested on synthetic fixtures, but `data/gold/` has zero real multi-book gold transcription files committed, so there is no baseline multi-book accuracy benchmark report (`20–30 pages across >= 3 books`) checked into the repository to measure future model or preprocessing improvements against.
- **Recommended Fix:**
  - Populate `data/gold/v1/` with a curated 20–30 page Telugu gold dataset across clean modern print, older literary print, and degraded scans so every OCR or preprocessing change can be regression-tested with `scripts/benchmark.py`.

---

## 5. Suggested Implementation Roadmap

1. **Milestone 1 — Reliability & Lifecycle Hardening (Quick Wins)**
   - Recover `"queued"` runs on startup in `src/api/app.py`.
   - Add `POST /api/v1/ocr-runs/{run_id}/cancel` and a `Cancel` button in the Web and Mobile progress strips.
   - Add legacy non-Unicode Telugu font detection (Unicode `U+0C00..U+0C7F` ratio check) in `classify_and_extract_pdf_page()`.
   - Enable Android/iOS LAN HTTP support (`usesCleartextTraffic` / `NSAllowsLocalNetworking`) in `mobile/`.

2. **Milestone 2 — Proofreading & Export Fidelity**
   - Add `block_role` classification (`paragraph`, `heading_1`, `heading_2`, `verse`, `ignore`) and paragraph merging in `editable_flow` DOCX export.
   - Support inserting missed blocks, ignoring false-positive blocks, and editing `digital_text` pages.
   - Expose Advanced OCR Options (`force_rerun`, `include_digital_text_pages`, `render_dpi`, `tesseract_psm`) in Web and Mobile UIs.
   - Add inline character/akshara diff highlighting for engine disagreements and an `"Approve All Unflagged Lines"` bulk action.

3. **Milestone 3 — Learning Loop & Preprocessing**
   - Deduplicate `CorrectionMemory` entries on creation, strip punctuation during n-gram token matching, and allow promoting `book_only` entries to `global_suggestion`.
   - Implement `TrainingSample` line-image cropping on consented books (`training_consent == True`).
   - Add `deskew` and `contrast_clahe` preprocessing profiles in `src/services/ocr_service.py` and validate against a 20–30 page gold dataset in `data/gold/`.
