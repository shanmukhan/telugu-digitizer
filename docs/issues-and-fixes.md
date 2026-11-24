# Issues and Fixes Reference

Running log of issues encountered during local setup, OCR execution, review UI usage, and DOCX export, together with their root causes and permanent fixes.

---

## 1. Empty DOCX Export Containing Only Source Page Markers

### Symptom
Uploading a 292-page scanned Telugu PDF (`2015.497167.yuva-sanputi.pdf`) and clicking **Export DOCX / TXT** produced a `.docx` file containing only the unreviewed banner (`[UNREVIEWED MACHINE OCR OUTPUT ...]`) and blank page separators (`— Source Page 1 —` through `— Source Page 292 —`) with no Telugu body text, while export validation reported `blocks_expected=0` and `passed=true`. Meanwhile, **Source Page 1** appeared blank in the viewer.

### Root Causes
1. **OCR had not been executed yet:** In PostgreSQL, the `ocr_runs` table had `0` rows for the imported book (`e39fff5d-a10b-4942-8baf-40b4b04ec25d`). On import, pages are rendered and stored, but OCR only starts when **Run Selected OCR** is triggered—and that button sat below the fold in the left sidebar.
2. **Permissive empty export path:** In `src/services/export_service.py`, `_collect_export_pages` allowed exporting scanned/mixed books when `selected_run is None` and `total_blocks == 0`.
3. **Blank cover/flyleaf first page & missing page navigation:** In the uploaded scan, `page-0001.png` (`17 KB`) is a blank flyleaf margin while Telugu text appears on later pages (e.g. `page-0005.png`, `604 KB`), and `SourcePageViewer` previously had no Prev/Next controls to move past Page 1.

### Fixes Implemented
- **Backend export guard** (`src/services/export_service.py`): `_collect_export_pages` now raises `AppError("NO_OCR_RUN_AVAILABLE", ..., status_code=409)` whenever a scanned or mixed book has no usable OCR run (`selected_run is None`) and `total_blocks == 0`.
- **Export UI warning & redirect** (`frontend/src/components/ExportPanel.tsx`): Computes `needsOcrFirst`, disables **Generate & Download Export**, renders an error banner explaining why no text can be exported yet, and provides a **Go to Page Review & Run OCR** button (`onGoToReview`).
- **Prev/Next page navigation** (`frontend/src/components/SourcePageViewer.tsx`, `frontend/src/App.tsx`): Added `← Prev`, `Page X / Y`, and `Next →` buttons (`pageCount`, `onNavigatePage`) to inspect any page in the book.
- **One-click OCR trigger in empty editor** (`frontend/src/components/ReviewEditorPanel.tsx`, `frontend/src/App.tsx`): Added a **Run Selected OCR Now** button (`onQuickStartOcr`, `ocrRunning`) directly inside the empty Proofreading Editor panel.
- **OCR page-range controls** (`frontend/src/api/client.ts`, `frontend/src/App.tsx`): Updated `startOcrRun` to pass `pageRange` (`page_range` in `POST /api/v1/books/{book_id}/ocr-runs`), and added **Start page**, **End page**, **Pages 1–5**, and **All (N)** quick buttons with CPU speed guidance.
- **Regression tests:**
  - `tests/test_phase5_export.py` (`test_phase5_export_rejected_when_no_ocr_run_exists`) verifies `409 NO_OCR_RUN_AVAILABLE` for both `raw_ocr` and `human_approved` exports before OCR runs.
  - `frontend/src/components/ExportPanel.test.tsx` verifies the disabled button, warning banner, and navigation callback when `runs=[]`.

---

## 2. Left Sidebar Scrollbar Not Working When Mouse Hovers Left Side

### Symptom
When the left sidebar (**Upload Printed Telugu PDF**, **Books**, **Run OCR Engines**) exceeded the viewport height, bottom controls such as **Run Selected OCR** were cut off below the window edge, no scrollbar appeared on the sidebar itself, and scrolling with a mouse wheel or trackpad while the cursor hovered over the left column did nothing.

### Root Causes
1. **Unbounded grid height:** In `frontend/src/styles/app.css`, `.app-shell` used `min-block-size: 100dvh` with `grid-template-rows: auto 1fr` without locking to the viewport or constraining `.workspace-grid` rows with `minmax(0, 1fr)`. Grid row tracks expanded to the sidebar's full intrinsic height (`1000+ px`), so `.sidebar` never constrained vertically to become scrollable.
2. **Scroll-trapping properties on an unconstrained box:** `.sidebar` still declared `overflow-y: auto; scrollbar-gutter: stable; overscroll-behavior: contain;`. Reserving an inner gutter and setting `overscroll-behavior: contain` prevented wheel/trackpad scroll events over `.sidebar` from chaining outward to the document window while `.sidebar` itself had no bounded scroll range.
3. **Missing flex/grid shrink guards:** Direct children inside column flex `.sidebar` lacked `flex-shrink: 0`, and scrollable flex/grid containers (`.sidebar`, `.main-stage`, `.review-split`, `.pane`, `.pane-body`) lacked `min-block-size: 0`.

### Fixes Implemented (`frontend/src/styles/app.css`)
- **Desktop viewport lock (`> 1024px`):**
  - `.app-shell`: `block-size: 100dvh; grid-template-rows: auto minmax(0, 1fr); min-block-size: 0;`
  - `.workspace-grid`: `grid-template-rows: minmax(0, 1fr); min-block-size: 0;`
  - `.sidebar`: added `min-block-size: 0` plus `.sidebar > * { flex-shrink: 0; }` so cards preserve full height and `.sidebar` reliably renders and scrolls its own vertical scrollbar.
  - `.main-stage`: added `min-block-size: 0; overflow-y: auto; scrollbar-gutter: stable;`, `.main-stage > * { flex-shrink: 0; }`, and `.main-stage > .review-split { flex: 1 1 0; min-block-size: 0; }`.
  - `.review-split`, `.pane`, `.pane-toolbar`, `.pane-body`: constrained rows (`grid-template-rows: minmax(0, 1fr)`), added `min-block-size: 0` / `max-block-size: 100%`, and kept `.pane-toolbar` at `flex-shrink: 0` so both viewer and editor bodies scroll smoothly inside their panes.
- **Responsive stacked layout (`@media (max-width: 1024px)` & `960px`):** Restored natural document flow (`block-size: auto; min-block-size: 100dvh; grid-template-rows: auto auto;`, `overflow-y: visible; overscroll-behavior: auto;` on `.sidebar`, `flex: 0 0 auto` on `.main-stage > .review-split`, `max-block-size: 75dvh` on `.pane`) so single-column mobile/tablet views scroll cleanly with the browser window.

---

## 3. Environment, OCR Engine, and Workflow Gotchas

### PaddlePaddle `SIGBUS` Crash on Large Scanned Pages (`3.2.0` vs. `3.3.1`)
- **Issue:** On Apple Silicon CPU, `paddlepaddle==3.2.0` crashed with `SIGBUS` when running OCR on `2480×1500` page images.
- **Fix:** Upgrade to `paddlepaddle==3.3.1` in `.venv`.

### CPU OCR Runtime Expectations on Multi-Hundred-Page Books
- **Benchmark observations on CPU (`2480×1500` pages):**
  - **Tesseract `5.5.4`** (`models/tesseract/tessdata/tel.traineddata` from `tessdata_best`): ~`0.4 s`/page (~2 minutes for a 292-page book).
  - **PaddleOCR PP-OCRv5** (`PP-OCRv5_server_det` + `te_PP-OCRv5_mobile_rec` on Apple Silicon CPU): ~`88–101 s`/page.
- **Recommendation:** For large scanned books on CPU, start with **Pages 1–5** to verify quality and page offsets, or uncheck PaddleOCR temporarily to produce a fast full-book Tesseract draft first.

### Frontend `npm install` Cache Permission Conflict
- **Issue:** Running `npm install` inside `frontend/` can fail if `~/.npm/_cacache` has restricted file ownership/permissions.
- **Fix:** Use a writable temporary npm cache directory:
  ```sh
  npm_config_cache=/tmp/npm-cache-telugu npm install
  ```

### Refreshing Served UI & Backend Changes
- FastAPI serves the built static assets from `frontend/dist`. After modifying frontend files, rebuild the bundle and restart the API process before reloading `http://127.0.0.1:8000`:
  ```sh
  (cd frontend && npm run build)
  .venv/bin/python scripts/run_api.py
  ```

---

## 4. `Connection refused` on `127.0.0.1:5432` When Starting `scripts/run_api.py`

### Symptom
Running `.venv/bin/python scripts/run_api.py` after a macOS reboot or environment restart failed during FastAPI lifespan startup with:
`psycopg.OperationalError: connection failed: connection to server at "127.0.0.1", port 5432 failed: could not receive data from server: Connection refused`

### Root Cause
The project uses a self-contained PostgreSQL 18 cluster in `.tools/postgres` / `.tools/pgdata` managed via `scripts/manage_local_pg.py` (no background macOS `launchd` service), so PostgreSQL stops when the host restarts. Previously, `scripts/run_api.py` did not start `.tools/pgdata` automatically when port `5432` was closed.

### Fix Implemented
- **Immediate manual start command:**
  ```sh
  .venv/bin/python scripts/manage_local_pg.py start
  ```
- **Automatic startup guard** (`scripts/run_api.py`): Added `_ensure_local_postgres(settings)`, which checks `127.0.0.1:5432` before starting Uvicorn and automatically invokes `.venv/bin/python scripts/manage_local_pg.py start` when the cluster is stopped and an initialized `.tools/pgdata` cluster exists on disk.

---

## 5. Hidden OCR Progress, Missing Status/ETA Visibility & UI Polish

### Symptom
1. Clicking **Run Selected OCR** disabled the sidebar button (`OCR Running...`) at the bottom of the left sidebar with no status indicator, page progress bar, completed/pending page breakdown, or time estimate visible at the top of the workspace.
2. Refreshing the browser mid-run lost active run progress in the header, and multi-engine batches did not show queued vs running engines.
3. Long PDFs (e.g., 292 pages) lacked direct page-number jump in the viewer toolbar, raw DB enums (`scanned_image`, `not_started`) and backticks appeared directly in badges/labels, and the upload form pushed OCR/page controls below the fold whenever a book was already selected.

### Root Causes
- `GET /api/v1/books/{book_id}/ocr-runs` (`BookOCRRunSummary`) did not include `ProcessingJob` counters (`progress_current`, `progress_total`, `started_at`, `error_summary`).
- `App.tsx` only polled a single `activeRunStatus` initiated in-session instead of syncing all running/queued runs across `runs`, and only refreshed `review` after full completion rather than incrementally as pages finished.

### Fixes Implemented
- **Backend progress fields on run summaries** (`src/api/schemas.py`, `src/services/review_service.py`): Added defaulted `progress_current`, `progress_total`, `started_at`, and `error_summary` fields to `BookOCRRunSummary` populated from `ProcessingJob` / `OCRRun`.
- **Top status pill & telemetry progress strip** (`frontend/src/components/OcrStatusBar.tsx`, `frontend/src/utils/formatters.ts`, `frontend/src/App.tsx`):
  - Sticky header `HeaderOcrStatusPill` always displays current book state (`OCR In Progress`, `OCR Queued`, `OCR Ready`, `Partial OCR · Resume Available`, or `Needs OCR`).
  - `OcrProgressStrip` above the split workspace renders a semantic styled `<progress>` bar, **`completed`** vs **`pending`** counts, percent, elapsed duration, observed **`sec/page` pace & ETA** (once ≥1 page finishes), queued follow-up engine badges, and one-click actions (`Test Pages 1–5`, `Run Full Book OCR`, `Resume`, `Export DOCX / TXT`).
  - Multi-run polling syncs all `running`/`queued` runs every `1500 ms` (including after browser refresh) and refreshes the page list and current review view live whenever a page completes.
- **UI & ergonomics refinements** (`frontend/src/App.tsx`, `frontend/src/components/SourcePageViewer.tsx`, `frontend/src/components/ReviewEditorPanel.tsx`, `frontend/src/components/ExportPanel.tsx`, `frontend/src/styles/app.css`):
  - Auto-collapsible **Import PDF** card once a book is loaded (`+ Import PDF` toggle) so **Books**, **Run OCR Engines**, and **Pages** appear above the fold.
  - Direct page-number jump input (`Page [N] / Total`), page status filter (`All` / `Pending` / `Approved`), human-readable badges/labels (`Scanned`, `Pending Review`, `PaddleOCR PP-OCRv5`, `Tesseract 5 Telugu`), compact toolbar controls (`role="toolbar"`), elevated studio styling, and `forced-colors` / `prefers-reduced-motion` support.
- **Tests added:** `frontend/src/components/OcrStatusBar.test.tsx`.

---

## 6. Bidirectional Block Sync Between Scan Viewer and Proofreading Editor

### Feature Added
Added IntelliJ "Select Opened File"-style navigation between text boxes on the left scan viewer and corresponding line cards in the right proofreading editor:
- **Toolbar sync controls (`SourcePageViewer.tsx`, `ReviewEditorPanel.tsx`):**
  - `⌖ Sync → Editor` in `SourcePageViewer` scrolls the Proofreading Editor smoothly to the currently selected scan box (turning off `Flagged Only` if the target line was hidden).
  - `⌖ Sync → Scan` in `ReviewEditorPanel` (plus a per-card `⌖ Find on scan` button) switches back to `Scan + Boxes` if needed and scrolls the scan viewport to center the target OCR polygon at the current zoom scale.
  - `Auto-Sync` (`aria-pressed`) toggle synchronizes selection automatically in both directions when enabled.
- **Scroll completion & reduced motion (`frontend/src/utils/scrollSync.ts`, `frontend/src/styles/app.css`):**
  - Uses native scroll promises where available with a `scrollend` + idle-timer fallback (`scrollIntoViewAsync` / `scrollContainerToAsync`), pulsing `.sync-flash` highlights once scrolling settles, `prefers-reduced-motion` safety, and polite ARIA `role="status"` announcements.
- **Tests:** `frontend/src/components/BlockSync.test.tsx`.

---

## 7. On-Screen Telugu InScript & Phonetic Virtual Keyboard

### Feature Added
Added a toggleable on-screen **Telugu Virtual Keyboard** dock (`⌨ Telugu Keyboard` in the top header and `⌨ Keyboard` in the Proofreading Editor toolbar) so users can edit/search Telugu text without changing OS keyboard layouts:
- **InScript (Standard) tab** (`frontend/src/utils/teluguInscript.ts`, `frontend/src/components/TeluguKeyboard.tsx`):
  - Complete BIS/CDAC QWERTY-mapped Telugu layout (dependent vowel signs on Normal keys, independent vowels on Shift keys, plus a 1-tap `Signs` strip for `్ ా ి ీ ు ూ ృ ె ే ై ొ ో ౌ ం ః ఁ`), `⇧ Shift`, `Space`, `⌫ Backspace`, `↵ New Line`, and an optional **Physical Keys: On/Off** capture mode.
- **Phonetic (Type / Tap) tab** (`frontend/src/utils/teluguTranslit.ts`):
  - Live Romanized-to-Telugu converter (`transliterateTeluguPhonetic`: e.g. `telugu` → `తెలుగు`, `pustakaM` → `పుస్తకం`, `ksha` → `క్ష`) with 1-click **Insert Telugu**, plus clickable vowel, matra, and varga consonant grids with transliteration hints.
- **Caret-preserving React input integration** (`frontend/src/utils/teluguInput.ts`, `frontend/src/App.tsx`):
  - Pointer clicks keep cursor focus in the active `<textarea>`/`<input>` (`onMouseDown` `preventDefault`) and update React 19 controlled values cleanly at the exact caret index (`insertTextAtCursor` / `backspaceAtCursor`), falling back cleanly to the selected OCR block when clicked after scan selection.
  - Docked inside `.app-shell.has-keyboard` so sidebar cards and proofreading blocks remain visible and scrollable above the keyboard.
- **Tests:** `frontend/src/components/TeluguKeyboard.test.tsx`.

---

## 8. Studio Visual Redesign (Header, Cards, Stepper, Welcome Hero)

### Goal
Move the UI from a basic utility look to a polished product look while keeping the core commitments visible and enforced (local-first, raw OCR never overwritten, no silent Telugu correction, read-only source PDF). Layout ideas were inspired by common OCR/SaaS dashboard patterns (sticky top bar, hero + bento feature cards, stat cards, workflow stepper); nothing is copied from any third-party site, and no external fonts/CDNs are loaded so the app still works fully offline.

### Changes
- **Commitment bar + top header** (`frontend/src/components/StudioChrome.tsx`, `frontend/src/App.tsx`): thin indigo bar stating the four core commitments, above a translucent sticky header with a gradient brand mark, `Local Studio` badge, OCR status pill, `⌨ Telugu Keyboard`, `＋ Import PDF` CTA and icon-labelled view tabs.
- **Workflow stepper** (`deriveWorkflowSteps`, `WorkflowStepper`): Import → OCR → Review → Export, derived from real state (runs, approved pages, active view) with `aria-current="step"`, shape + text state (not color alone), and clickable Review/Export steps.
- **Stat cards** (`OverviewCards`): Book, OCR Engines, Review Progress (native `<progress>`), This Page (lines/flagged/status); collapsible via `Hide stats`.
- **Welcome hero** (`WelcomeHero`): shown on an empty library with the product promise, a 4-step pipeline, an `Import your first PDF` CTA (opens the file picker) and six feature cards that restate the commitments.
- **Theme** (`frontend/src/styles/app.css`): indigo/saffron palette tokens, soft shadows, rounded cards, card icons, pane toolbars; review split keeps a minimum height (`min(36rem, 72dvh)`) and the main stage scrolls instead of squeezing the panes; `forced-colors` and `prefers-reduced-motion` handled.
- **Tests:** `frontend/src/components/StudioChrome.test.tsx`.

---

## 9. Theme Refresh: "Palm-leaf & Turmeric" (replaces the indigo/blue palette)

### Why
The first redesign used a generic indigo/blue that felt like a stock SaaS template and did not suit a Telugu book-digitization tool.

### Theme
- **Palm-leaf teal** primary (`#0f6b5c`, hover `#0a5448`, soft tint `#e5f3ef`) — evokes palm-leaf manuscripts and gives a calm, scholarly feel.
- **Turmeric** accent (`#e0a100`, soft `#fff2cc`) for highlights, badges and sync flashes; amber stays reserved for "needs attention".
- **Warm paper** neutrals (`--bg #f6f2e8`, cream surfaces, green-black ink `#1b2b28`) with a very faint ruled-line texture and teal/turmeric glows in the page background.
- Deep teal commitment bar and brand mark; hero accent text runs teal → copper.
- Scan overlay boxes switched from blue to teal (selected = dark teal, flagged = amber).

### Accessibility checks (computed WCAG contrast)
White on primary 6.41:1 (hover 8.84:1); ink on page 13.2:1; muted text 5.75–6.43:1; info text on tint 8.9:1; commitment-bar text 5.55–12.4:1; focus ring 4.4–4.9:1. Control/input borders were darkened (`--border-strong #8c8672`, 3.26–3.64:1) so form field boundaries meet the 3:1 non-text contrast guideline.

### Implementation
All colours are CSS custom properties in `:root` of `frontend/src/styles/app.css`; the remaining literals were remapped and no blue/indigo literals remain. Retheming again only requires editing the `:root` tokens plus the few gradient literals in the "Studio theme v2" block.
