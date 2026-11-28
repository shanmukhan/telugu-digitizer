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

---

## 10. Raspberry Pi ARM64 & Public Domain Hosting (`lahari.org`) Support

### Requirements Addressed
1. **Verified Linux `aarch64` OCR wheel matrix:** Checked `https://www.paddlepaddle.org.cn/packages/stable/cpu/paddlepaddle/` and confirmed official `paddlepaddle==3.3.1` `linux_aarch64` wheels (including `cp311` and `cp313`) are published alongside PyPI `paddleocr==3.7.0`, so the pinned dual-engine stack runs natively on 64-bit Debian/Raspberry Pi OS (with an explicit `ENABLE_PADDLE_OCR=false` option for 2–4 GB boards running Tesseract-only).
2. **Dockerless native Raspberry Pi default & Debian Trixie compatibility:**
   - Native bare-metal Raspberry Pi OS / Debian 13 (`systemd` + `postgresql` + `tesseract-ocr` + `.venv` via `deploy/raspberry-pi/install.sh` and `deploy/raspberry-pi/remote-deploy.sh --mode native`) is the default deployment path; Docker (`deploy/compose.lahari.yml`) remains optional.
   - `install.sh` auto-detects `libglib2.0-0t64` vs `libglib2.0-0`, accepts `API_PORT` (deployed on `8085` on the Pi because `8000` is used by `rpi-monitor`), and leaves `APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD` unset by default for free open access with no login page.
3. **Subpath hosting on `lahari.org/telugu/` without replacing existing `lahari.org` services:**
   - Updated `frontend/vite.config.ts` (`base: "./"`), `frontend/src/api/client.ts` (`resolveAppUrl()`), `SourcePageViewer.tsx`, and `ExportPanel.tsx` so all Vite assets, PDF.js worker, API requests, and DOCX/TXT download links resolve cleanly under `/telugu/` as well as `/` (because `lahari.org/api/` is already used by `lahari-counter.service`).
   - Added `/telugu/` reverse proxy (`127.0.0.1:8085`) and Product Card `07` + nav link (`href="/telugu/"`) in sibling repo `~/Developer/repo/rpi-setup` (`scripts/apache-templates/lahari.org.conf.tmpl`, `scripts/configure-lahari.sh`, `scripts/site-content/lahari-home/index.html`, and docs/tests), preserving `/`, `/lab/`, `/api/`, `/monitor/`, `/agentic-trader/`, and `/portfolio-advisor/`.
4. **Live Pi Deployment & Verification (2026-11-24 on `lipi@192.168.1.13`):**
   - Deployed via `./deploy/raspberry-pi/remote-deploy.sh lipi@192.168.1.13 --mode native --with-paddle --port 8085` (Debian 13 `trixie` `aarch64`, Python `3.13.5`, PostgreSQL `17`, Alembic `0002_exports_table`).
   - Verified `telugu-digitizer.service` active and public HTTPS `200` responses across `https://lahari.org/`, `/lab/`, `/api/visits/stats`, `/monitor/health`, `/agentic-trader/workspace`, `/telugu/` (`302` from `/telugu`), bundled JS/CSS/PDF.js worker assets, `/telugu/api/v1/health`, `/telugu/api/v1/capabilities` (both `paddle_ppocrv5_te` and `tesseract_tel_best` available, `auth_enabled: false`), and `/telugu/api/v1/books` (`/portfolio-advisor/` `401` preserved).

---

## 11. Page Review Shows "No OCR text extracted" While Tesseract Succeeded, PaddleOCR ARM64 `SIGSEGV`/OOM, and Server Crash Observability

### Symptom
1. After running dual-engine OCR on Pages `6–20` of *Amuktamalyada Vo.1* (`4963×7017` px 300-DPI scans) on the Raspberry Pi (`192.168.1.13`), **Tesseract 5 Telugu** completed all 15 pages (`15/15`), yet the **Proofreading Editor** displayed **`No OCR text extracted for this page yet.`** on Page 7 with the top strip still showing **`Resume PaddleOCR PP-OCRv5 (0/15)`**.
2. Clicking **Resume PaddleOCR PP-OCRv5 (0/15)** triggered another `0/15` failure.
3. During standalone Raspberry Pi diagnostic testing on Page 7, unconstrained `PP-OCRv5_server_det` memory allocation exhausted system RAM and triggered a Pi reboot / temporary `503 Service Unavailable`.

### Root Causes
1. **Default primary-run selection picked an empty `0/15` partial run (`src/services/review_service.py`, `src/services/export_service.py`):**
   - `get_page_review_payload()` and `_select_ocr_run()` preferred `engine == "paddleocr"` across all `status IN ("completed", "partial")` runs without checking whether a run processed any pages (`progress_current > 0`) or had `OCRBlock` rows for the current page. As a result, Page 7 defaulted to the `0/15` partial PaddleOCR run (`0` blocks) even though the completed `15/15` Tesseract run already had `24` extracted Telugu lines for Page 7.
2. **PaddleOCR `SIGSEGV` (`status=11/SEGV`) on ARM64 Raspberry Pi (`src/ocr/paddle_provider.py`, `deploy/raspberry-pi/install.sh`):**
   - PaddleX's `PaddlePredictorOption` defaults `"cpu_threads": int(os.getenv("PADDLE_PDX_CPU_NUM_THREADS", 10))` and `/etc/telugu-digitizer/env` previously set `OMP_NUM_THREADS=2`. Multi-threaded OpenBLAS execution inside `paddlepaddle==3.3.1` on `linux_aarch64` segfaulted (`exit 139`), even on a `200×400` test image, killing the worker and restarting `telugu-digitizer.service` before Page 6 could finish (`0/15`).
3. **14.6 GB tensor `MemoryError` on `4963×7017` A2-sized PDF scans (`src/ocr/paddle_provider.py`):**
   - PaddleOCR's default detection config (`text_det_limit_type="min"`, `max_side_limit=4000`) passed a huge `2829×4000` tensor to `PP-OCRv5_server_det`, triggering `ResourceExhaustedError: Fail to alloc memory of 14598144000 size` (~14.6 GB) on the 8 GB Raspberry Pi.
4. **Post-mortem crash observability gaps (`scripts/run_api.py`, `src/common/logging_utils.py`, `src/api/app.py`, `src/services/ocr_service.py`):**
   - `faulthandler` was not enabled to capture Python thread traces on native C++ `SIGSEGV` signals.
   - `ocr_service.py` only logged after `provider.recognize()` finished or threw a Python exception, leaving no record of which `run_id`, `page_number`, or pixel dimensions caused a hard C++ crash or OOM `SIGKILL`.
   - Structured logs went only to `stderr`/`journald` (not persisted to `workspace/logs/` across reboots), and startup recovery + provider initialization failures did not emit structured warning/error logs.

### Fixes Implemented
- **Page-aware primary-run & export-run selection (`src/services/review_service.py`, `src/services/export_service.py`):**
  - `get_page_review_payload()` now queries `OCRBlock` counts on the target page per usable run and prioritizes runs that actually have extracted blocks on that page (`block_count > 0`) and non-zero progress before preferring `paddleocr` over `tesseract`.
  - `_select_ocr_run()` in `export_service.py` similarly prioritizes `completed` / non-zero-progress runs over `0`-progress partial runs.
- **ARM64 thread safety & bounded detection size (`src/ocr/paddle_provider.py`, `deploy/raspberry-pi/install.sh`, `deploy/raspberry-pi/telugu-digitizer.service`):**
  - Set `cpu_threads=1` and `PADDLE_PDX_CPU_NUM_THREADS=1` by default on Linux `aarch64`/`arm64` (and `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, `MKL_NUM_THREADS=1` in `install.sh`).
  - Set `text_det_limit_type="max"` and `text_det_limit_side_len=1280` on Linux ARM64 (`1920` otherwise, configurable via env) so large `4963×7017` pages never trigger multi-GB `server_det` allocations.
  - Added `MemoryHigh=3500M` and `MemoryMax=4500M` to `deploy/raspberry-pi/telugu-digitizer.service` so runaway allocations cannot starve `sshd` or lock up the Pi.
- **UI engine-fallback ergonomics (`frontend/src/components/ReviewEditorPanel.tsx`, `frontend/src/App.tsx`):**
  - Shows `(partial X/Y)` in the engine dropdown, surfaces partial-run `error_summary`, renders a one-click **Switch to `<Engine>`** button when an empty partial run is selected alongside a populated run, and reports `0`-progress partial runs as error banners rather than green success notices.
- **Crash & server observability (`src/common/logging_utils.py`, `scripts/run_api.py`, `src/api/app.py`, `src/services/ocr_service.py`):**
  - Enabled `faulthandler.enable(all_threads=True)` at API startup (`scripts/run_api.py`).
  - Added rotating disk log persistence (`WORKSPACE_DIR/logs/telugu-digitizer.log`, 10 MB × 5 backups) in `configure_logging()` / `create_app()`.
  - Added `"Starting OCR page in backend job"` logs with `run_id`, `page_number`, `width_px × height_px`, `render_dpi`, and `rss_mb` before `provider.recognize()`, plus `elapsed_ms` + `peak_rss_mb` on completion, provider-init `ERROR` logs, startup crash-recovery `WARNING` logs with interrupted `run_ids`, and a catch-all unhandled HTTP `500` exception logger.
- **Regression Tests:**
  - `tests/test_phase3_review_api.py` (`test_phase3_review_prefers_populated_run_over_empty_partial_paddle_run`)
  - `tests/test_ocr_providers_and_integration.py` (`test_paddle_provider_rejects_non_telugu_or_wrong_version`)
  - `tests/test_deployment_and_security.py` (rotating log file + crash recovery log verification)
  - `frontend/src/components/ReviewEditorPanel.test.tsx` (engine switch CTA)


---

## 2026-11-28 — `502 Proxy Error` on Large PDF Import (406-Page Book)

- **Symptom:** Importing a 406-page PDF via `https://lahari.org/telugu/` failed in the browser with Apache `502 Proxy Error (Error reading from remote server)`, even though the book eventually appeared in the database.
- **Root Cause:** `import_pdf_book` in `src/services/book_service.py` rasterized every page synchronously at 300 DPI to PNG during the HTTP `POST /api/v1/books` request (~16 minutes for 406 pages on Raspberry Pi 5), exceeding Apache's reverse-proxy read timeout.
- **Fix:**
  - Added thread-safe on-demand page rasterization (`ensure_page_image_rendered`) in `src/services/book_service.py`.
  - For books with `> 10` pages (`EAGER_RENDER_MAX_PAGES = 10`), `import_pdf_book` classifies all pages and pre-renders only Page 1 synchronously (completing upload in ~2 seconds), deferring remaining 300 DPI PNG renders until first page view (`GET /api/v1/books/{book_id}/pages/{page_number}/image`), OCR (`src/services/ocr_service.py`), or training crop extraction (`src/services/review_service.py`).
  - Added regression test `test_large_pdf_import_uses_lazy_page_rendering_on_demand` in `tests/test_lexicon_and_autocorrect.py` (32/32 backend tests passing against PostgreSQL).

---

## 12. 2026-11-28 — UI/UX Redesign, Telugu *Vattu* Auto-Correction, `global_suggestion` Default, and Partial-Book OCR Continuation + Stitched Export

### Issues Addressed
1. **Cluttered multi-banner shell & proofreading fatigue:** Implemented all 4 phases of [UI_UX_REDESIGN_PROPOSAL.md](UI_UX_REDESIGN_PROPOSAL.md) — slim `52 px` `TopNavBar` with searchable Book Switcher, `44 px` unified page sub-toolbar, virtualized `PageRail`, Two-Density `ReviewEditorPanel` with inline Telugu grapheme diff, `ImportBookDialog`, `OcrRunnerDrawer`, `ShortcutsDialog`, `ToastRegion`, `PinnedLineCrop` for tablets/mobile, and `@layer`-structured `app.css`.
2. **Broken Telugu display headings (`(పగమబాగం- 1` → `ప్రథమభాగం- 1`) & noisy comparator chips:**
   - Expanded `_CONFUSION_GROUPS`, `_TIGHT_CONFUSION_PAIRS`, and `_SKELETON_MAP` in `src/services/lexicon_service.py` with aspirated/visual Telugu pairs (`బ ↔ భ`, `థ ↔ గ`, `ప ↔ ఫ`, `క ↔ ఖ`, `గ ↔ ఘ`, `ట ↔ ఠ`, `డ ↔ ఢ`, `చ ↔ ఛ`).
   - Added a *vattu*-stripped consonant skeleton index (`vattu_skeleton_index`), single-miss DP cost (`0.40`) for 2-codepoint conjuncts (`్ + consonant`), and unmatched leading `(` → `్ర` recovery in `_autocorrect_single_block`.
   - Added the `textured_bold` OCR preprocessing profile (`src/services/ocr_service.py`, `OcrRunnerDrawer.tsx`) combining deskew + CLAHE + `2×2` morphological opening + unsharp sharpening for halftone/stippled headings.
   - Collapsed noisy comparator mismatches (`> 18` changed tokens / `> 28` tokens) behind an expandable summary in `ReviewEditorPanel.tsx`.
3. **Default correction memory scope:** Changed the default `memory_scope` from `"book_only"` to `"global_suggestion"` across `ReviewEditorPanel.tsx`, `App.tsx`, `src/api/schemas.py`, `src/services/review_service.py`, and `src/services/correction_service.py`.
4. **No clear path to continue remaining pages after a Pages 1–5 sample OCR run (and single-run export gap):**
   - Added interval-merging coverage detection (`computeBookOcrCoverage` in `frontend/src/utils/formatters.ts`) so books with only a sample range completed (`1–5` of `406`) display **`OCR 5/406p · Continue`** in `TopNavBar` instead of misleadingly showing green `✓ OCR Ready`.
   - Surfaced a direct **`▶ Continue Remaining (Pages 6–406)`** / **`⚡ Fast Draft (6–406)`** continuation strip in `OcrProgressStrip`, direct **`Continue Remaining Pages (6–406)`** + **`OCR Page N Only`** actions on uncovered pages in `ReviewEditorPanel`, and pre-filled remaining-page presets in `OcrRunnerDrawer`.
   - Upgraded `_collect_export_pages` in `src/services/export_service.py` so default full-book exports (`primary_run_id=None`) stitch blocks per page across all usable runs while prioritizing human-approved/edited blocks — preserving approved Pages 1–5 edits seamlessly when continuing Pages 6–406 in a second run.
   - Added regression tests in `tests/test_phase5_export.py`, `tests/test_lexicon_and_autocorrect.py`, `frontend/src/components/OcrStatusBar.test.tsx`, and `frontend/src/components/RedesignComponents.test.tsx`.

