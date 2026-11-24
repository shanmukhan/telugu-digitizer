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
