# 14. Performance Audit & Improvement Opportunities

Comprehensive audit of performance bottlenecks and optimization opportunities across the `telugu-digitizer` backend, OCR pipeline, PostgreSQL database layer, HTTP delivery, and React frontend.

---

## 1. Critical Backend & OCR Pipeline Bottlenecks

### 1.1 `POST /api/v1/books` blocks the main asyncio event loop during synchronous 300-DPI PDF rasterization
- **Locations:**
  - `src/api/routes.py` (`upload_book`, lines 120–154)
  - `src/services/book_service.py` (`import_pdf_book`, lines 25–154)
  - `src/pdf/rasterizer.py` (`classify_pdf_page`, lines 18–50)
  - `src/common/io.py` (`atomic_write_bytes`, lines 51–65)
- **Root Cause:**
  1. `upload_book` is defined as `async def` and reads the entire uploaded PDF (up to `MAX_UPLOAD_MB` = 200 MiB) into a single in-memory `bytes` buffer (`pdf_bytes = await file.read()`), then invokes synchronous `import_pdf_book(...)` **directly on Uvicorn's main event loop thread**.
  2. Inside `import_pdf_book`, every page of the PDF is synchronously rendered at 300 DPI (`page.get_pixmap`), PNG-encoded (`pix.tobytes("png")`), SHA-256 hashed, and written via `atomic_write_bytes` (which calls `os.fsync()` on every page).
  3. On a Raspberry Pi or CPU host, importing a 100–300 page PDF blocks the **entire FastAPI process** for minutes (causing `/api/v1/health` and all other requests to hang) and risks reverse-proxy 504 timeouts (`timeout=300`).
  4. `classify_pdf_page(page)` calls `page.get_text("text")`, and `import_pdf_book` (lines 122–123) immediately calls `page.get_text("text")` a **second time** on `digital_text` and `mixed` pages.
- **Recommended Improvements:**
  - Offload `import_pdf_book` from the event loop using FastAPI/Starlette `run_in_threadpool` (or stream the upload to a temporary file while computing SHA-256 incrementally).
  - **Render page PNGs lazily or in the background worker:** `OCRJobExecutor._ensure_page_image_path` (`src/services/ocr_service.py`, lines 241–270) already supports on-demand page rendering from `source.pdf`. At upload time, classify pages (and optionally render Page 1 for immediate preview) while deferring bulk 300-DPI PNG rendering.
  - Return the extracted text string directly from `classify_pdf_page()` so `page.get_text("text")` is executed only once per page.

---

### 1.2 PaddleOCR model weights are re-initialized per run and SHA-256 hashed on every single page
- **Locations:**
  - `src/ocr/paddle_provider.py` (`_model_checksums`, `_package_versions`, `provider_metadata`, `recognize`, lines 99–185)
  - `src/ocr/tesseract_provider.py` (`__init__`, `_read_version`, lines 83–115)
  - `src/services/ocr_service.py` (`build_ocr_provider`, `execute_run`, `create_or_reuse_ocr_runs`, lines 99–146, 317–321, 559–560)
- **Root Cause:**
  1. `PaddleOCRProvider.recognize()` calls `meta = self.provider_metadata()` on **every page** (`src/ocr/paddle_provider.py`, line 184).
  2. `provider_metadata()` calls `self._model_checksums()`, which streams and SHA-256 hashes both detection and recognition `inference.pdiparams` weight files from disk (`sha256_file(params_path)`), and queries `importlib.metadata.version()` three times **after every single page**.
  3. `OCRJobExecutor.execute_run()` instantiates a brand-new `PaddleOCRProvider` for every OCR run instead of caching the loaded pipeline across runs, paying the multi-second PaddleOCR cold start and reallocating inference buffers on every run.
  4. `TesseractOCRProvider.__init__` hashes `tel.traineddata` from disk and spawns `subprocess.run([self.tesseract_cmd, "--version"])` synchronously inside `POST /api/v1/books/{book_id}/ocr-runs` (`create_or_reuse_ocr_runs`, line 559) and again when the background job starts (`execute_run`, line 317).
- **Recommended Improvements:**
  - Compute and cache `_model_checksums`, `_package_versions`, and Tesseract's `traineddata_sha256` / `--version` once per process (e.g., via `@functools.lru_cache` or instance attributes populated once during `ensure_loaded()`).
  - Cache instantiated `OCRProvider` instances on `OCRJobExecutor` so subsequent OCR runs reuse the warm PaddleOCR pipeline.

---

### 1.3 Custom-DPI rendering re-opens `source.pdf` and re-hashes PNGs on every page
- **Location:**
  - `src/services/ocr_service.py` (`OCRJobExecutor._ensure_page_image_path`, lines 241–270)
- **Root Cause:**
  - When `requested_dpi != page.render_dpi`, `_ensure_page_image_path` opens and closes `source.pdf` (`with pymupdf.open(source_pdf_path) as doc:`) inside the per-page loop.
  - When the custom-DPI PNG already exists on disk (lines 259–261), it reads the entire PNG into memory just to recompute `sha256_bytes(img_path.read_bytes())`.
- **Recommended Improvements:**
  - Keep `pymupdf.Document` open across the page loop in `execute_run` when custom-DPI rendering is required, or persist the custom-DPI `image_sha256` metadata.

---

### 1.4 In-process `ThreadPoolExecutor` GIL contention & unbounded `_futures` dictionary
- **Location:**
  - `src/services/ocr_service.py` (`OCRJobExecutor`, lines 212–240)
- **Root Cause:**
  - Running PaddleOCR CPU inference (~90s/page on Raspberry Pi) and large JSON serialization (`_to_json_compatible`) inside a `ThreadPoolExecutor` in the same Python process as FastAPI/Uvicorn causes GIL and CPU contention with incoming HTTP requests.
  - `self._futures[run_id] = fut` (line 231) is never cleaned up when runs finish, retaining completed `Future` objects indefinitely.
- **Recommended Improvements:**
  - Add a completion callback (`fut.add_done_callback(lambda _: self._futures.pop(run_id, None))`).
  - Run heavy OCR jobs in a separate process (`ProcessPoolExecutor(max_workers=1)` or a dedicated systemd worker) and constrain native thread counts (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`) so the web server remains responsive during OCR.

---

## 2. Database & SQLAlchemy N+1 Query Bottlenecks

### 2.1 Severe nested N+1 query explosion during DOCX/TXT export (`1 + P + (P × B)` queries)
- **Location:**
  - `src/services/export_service.py` (`_collect_export_pages`, lines 128–247)
- **Root Cause:**
  1. For every scanned/mixed page (`P` pages), `_collect_export_pages` executes a separate `SELECT` on `ocr_blocks` (lines 194–203).
  2. Inside that loop, for every block (`B` blocks per page), it executes another `SELECT` on `review_edits` to get the latest edit (lines 208–212). For a 300-page book with 35 blocks/page, generating an export triggers **~10,800 individual SQL queries**.
  3. Lines 156–161 open `source.pdf` with PyMuPDF and load every page (`for idx in range(pdf_doc.page_count): pdf_doc.load_page(idx).rect`) to populate `page_dims`, even though `_build_docx_bytes` (lines 282–284) **only ever reads `pages[0].width_pt` and `pages[0].height_pt`** (and only when `layout_mode == "page_preserving"`). Moreover, `BookPage` already stores `width_px`, `height_px`, and `render_dpi`, from which point dimensions can be computed directly (`width_px * 72.0 / render_dpi`).
- **Recommended Improvements:**
  - Fetch all `OCRBlock` rows for `selected_run.id` across the book in **one query** ordered by `(book_page_id, reading_order, block_index)`.
  - Fetch the latest `ReviewEdit` per block in **one query** (e.g., using PostgreSQL `DISTINCT ON (ocr_block_id)` ordered by `ocr_block_id, created_at DESC, id DESC`, or querying `DocumentTextBlock` for the active draft version).
  - Compute page dimensions from `BookPage.width_px / render_dpi` (or only inspect page 0 of `source.pdf` when needed).

---

### 2.2 N+1 queries and redundant work on every page review load (`GET /api/v1/books/{id}/pages/{page}/review`)
- **Locations:**
  - `src/services/review_service.py` (`list_book_ocr_runs`, `get_page_review_payload`, lines 129–331)
  - `src/services/correction_service.py` (`find_block_suggestions`, lines 243–320)
- **Root Cause:**
  1. `list_book_ocr_runs` (lines 141–143) executes 2 queries per run (`db.get(ModelRegistry, ...)` and `db.get(ProcessingJob, ...)`) instead of a single query with `outerjoin`.
  2. For each primary `OCRBlock` on the page (lines 252–259), `get_page_review_payload` executes a separate `SELECT * FROM review_edits WHERE ocr_block_id = ...` query (30–50 queries per page view).
  3. `find_block_suggestions` is called inside `for idx, blk in enumerate(primary_blocks):` (line 272) and **rebuilds `visible_entries`, `by_incorrect`, and `books_by_pair` (calling `normalize_nfc()` on every active `CorrectionMemory` row in the database) once per block** (30–50× redundant dictionary construction per page request).
  4. `_match_comparator_block` (lines 69–98) recomputes `_bbox_from_block(comp)` for every comparator block on every primary block iteration ($O(N \times M)$).
- **Recommended Improvements:**
  - Join `ModelRegistry` and `ProcessingJob` directly in `list_book_ocr_runs`.
  - Batch-load `ReviewEdit` rows for all primary block IDs on the page in a single query (`WHERE ReviewEdit.ocr_block_id.in_(block_ids)`).
  - Precompute the normalized correction memory lookup map (`by_incorrect`, `books_by_pair`) and comparator bounding boxes **once per page request** before iterating over `primary_blocks`.

---

### 2.3 N+1 full-table `BookPage` loads in `GET /api/v1/books` and filesystem `stat()` storm in `GET /api/v1/books/{id}/pages`
- **Locations:**
  - `src/services/book_service.py` (`list_books_with_counts`, `get_book_with_counts`, lines 166–183)
  - `src/api/routes.py` (`list_book_pages`, lines 201–231)
- **Root Cause:**
  1. `list_books_with_counts` queries all `Book` rows, then runs `SELECT * FROM book_pages WHERE book_id = ...` for each book (loading full `BookPage` ORM models including `digital_text_content`) just to count `scanned_image`, `digital_text`, and `mixed` pages in Python.
  2. `list_book_pages` loads all `BookPage` rows for a book (including `digital_text_content`, which is not part of `PageSummaryResponse`) and calls `storage.exists(p.image_storage_key)` for every page. Each `storage.exists()` call invokes `Path.resolve()` twice plus `Path.is_file()` — resulting in hundreds of filesystem syscalls on every 1.5-second OCR progress poll.
- **Recommended Improvements:**
  - Replace per-book page queries in `list_books_with_counts` and `get_book_with_counts` with a single SQL aggregate query (`GROUP BY book_id, page_kind` or `COUNT(*) FILTER (WHERE page_kind = ...)`).
  - Exclude `BookPage.digital_text_content` via `orm.defer(BookPage.digital_text_content)` in `list_book_pages`, and determine `has_image` from `bool(p.image_storage_key)` (or a single `os.listdir()` set lookup on `workspace/pages/{book_id}`).

---

### 2.4 N+1 queries on page approval (`PATCH /api/v1/books/{id}/pages/{page}/review-status`)
- **Location:**
  - `src/services/review_service.py` (`update_page_review_status`, lines 480–517)
- **Root Cause:**
  - When a page is marked `"approved"`, it loops over `run_blocks` and executes 2 SQL queries per block (`SELECT` on `DocumentTextBlock` and `SELECT` on `ReviewEdit`).
- **Recommended Improvements:**
  - Fetch existing `DocumentTextBlock` rows and latest `ReviewEdit` rows for the page's blocks in two batched `WHERE ocr_block_id IN (...)` queries before the loop.

---

### 2.5 Full-table scan in `search_corrections` & `list_corrections` + missing database indexes
- **Locations:**
  - `src/services/correction_service.py` (`search_corrections`, `list_corrections`, lines 170–200, 373–397)
  - `src/db/models.py` / `alembic/versions/`
- **Root Cause:**
  - `correction_memory` defines index `ix_correction_memory_incorrect` on `(language_code, incorrect_text, status)`, but `search_corrections` loads **all** active rows for `language_code` into Python and filters them in a loop (`normalize_nfc(row.incorrect_text).strip() == target_nfc`).
  - `list_corrections` loads all rows into Python and performs substring search (`q_nfc in ...`) in memory without pagination.
  - Frequently queried foreign-key and filter columns lack indexes:
    - `ocr_runs(book_id, created_at)`
    - `processing_jobs(book_id)` and `processing_jobs(status)`
    - `document_text_blocks(version_id, ocr_block_id)` and `document_text_blocks(version_id, book_page_id)`
    - `correction_memory(book_id)`
- **Recommended Improvements:**
  - Normalize `incorrect_text` and `corrected_text` with `normalize_nfc(...).strip()` before inserting into `correction_memory`, then filter directly in SQL (`WHERE language_code = :lang AND incorrect_text = :target AND status = 'active'`) to hit `ix_correction_memory_incorrect`.
  - Add an Alembic migration creating the missing indexes above.

---

## 3. HTTP Streaming, Caching & Compression

- **Locations:**
  - `src/api/routes.py` (`get_book_pdf` lines 178–190, `get_page_image` lines 234–255, `download_export_file` lines 623–649)
  - `src/api/app.py` (`create_app`, lines 62–161)
- **Issues & Recommended Improvements:**
  1. **Stream files with `FileResponse` instead of `Response(content=storage.read_bytes(...))`:**
     - `get_book_pdf`, `get_page_image`, and `download_export_file` read entire files (up to 200 MiB for PDFs) into a Python `bytes` object in RAM on every request.
     - Returning `FileResponse(path=storage.resolve_key(...), media_type=...)` streams the file from disk without buffering it in memory, automatically attaches `ETag` and `Last-Modified` headers, and enables HTTP Range requests (`Accept-Ranges: bytes`) for `PDF.js`.
  2. **Add `Cache-Control` / `ETag` headers to page images:**
     - `GET /api/v1/books/{book_id}/pages/{page_number}/image` returns 300-DPI PNGs with no cache headers, forcing the browser to re-download multi-megabyte PNGs every time a reviewer navigates back and forth between pages.
     - Add `Cache-Control: public, max-age=31536000, immutable` (or validate `If-None-Match` against `page.image_sha256` before reading disk).
  3. **Enable GZip compression for JSON responses:**
     - Add `app.add_middleware(GZipMiddleware, minimum_size=1000)` in `src/api/app.py` to compress large JSON responses (`/review` with block polygons and edit history, `/pages`, `/corrections`).

---

## 4. Frontend Performance Issues

### 4.1 PDF.js destroys and re-downloads the entire book PDF on every page flip or zoom change
- **Location:**
  - `frontend/src/components/SourcePageViewer.tsx` (lines 119–175)
- **Root Cause:**
  - The PDF.js `useEffect` depends on `[bookId, pageNumber, viewMode, zoom]`. Inside the effect, it calls `pdfjsLib.getDocument(resolveAppUrl('/api/v1/books/${bookId}/pdf'))`, renders the page, and in its cleanup function calls `loadedDoc.destroy()`.
  - Every time the user clicks **Next / Prev Page** or clicks **`+` / `-` Zoom** while in `PDF.js` mode, the component destroys the `PDFDocumentProxy` and **re-downloads and re-parses the entire book PDF**.
- **Recommended Improvements:**
  - Cache the loaded `PDFDocumentProxy` in a ref keyed by `bookId` (loading it only when `bookId` changes while `viewMode === "pdfjs"`, and destroying it only when `bookId` changes or `SourcePageViewer` unmounts).
  - Have the `[pageNumber, zoom]` effect reuse the cached `PDFDocumentProxy` to call `pdfDoc.getPage(pageNumber)` and render the viewport.

---

### 4.2 `pdfjs-dist` is eagerly bundled into the main JS chunk (632 KB)
- **Locations:**
  - `frontend/src/components/SourcePageViewer.tsx` (lines 2–8)
  - `frontend/vite.config.ts`
- **Root Cause:**
  - `import * as pdfjsLib from "pdfjs-dist"` is statically imported at the top level of `SourcePageViewer.tsx`, producing a **632 KB** main `index-*.js` bundle even though `"overlay"` (`<img>` + `<svg>`) is the default view mode.
- **Recommended Improvements:**
  - Dynamically `import("pdfjs-dist")` and `import("pdfjs-dist/build/pdf.worker.min.mjs?url")` only when the user switches `viewMode` to `"pdfjs"`, reducing the initial JS bundle size by ~70% (~632 KB → ~185 KB).

---

### 4.3 Aggressive polling cascade during active OCR runs + clobbering unsaved user drafts
- **Locations:**
  - `frontend/src/App.tsx` (lines 205–264, 393–429)
  - `frontend/src/components/ReviewEditorPanel.tsx` (lines 83–89)
- **Root Cause:**
  1. While an OCR run is active, `App.tsx` polls `getOcrRunStatus` every 1.5s via `window.setInterval` without waiting for the previous poll cycle to finish, which can stack overlapping requests when the Pi CPU is saturated.
  2. Whenever `st.progress_current > prevEntry.progress` (every completed page), `pollOnce()` calls both `refreshBookDetail(currentBookId)` (fetching `/pages` and `/ocr-runs`) **and** `refreshReview(currentBookId, selectedPageNumber, selectedPrimaryRunId)` — even when the user is viewing Page 1 (already completed) and OCR is processing Page 50.
  3. Because the polling `useEffect` depends on `selectedPageNumber`, navigating to a different page tears down and immediately restarts the polling effect, firing duplicate requests.
  4. When `refreshReview` resolves, `ReviewEditorPanel`'s `useEffect` (`[review.book_id, review.page_number, review.primary_run_id, review.blocks]`, lines 83–89) overwrites `drafts` for every block on the page, **wiping out any unsaved text edits the reviewer is currently typing**!
  5. Saving a single block edit in `handleSaveBlockEdit` (`App.tsx`, lines 411–414) also triggers a full `refreshBookDetail` + `refreshReview` round-trip instead of applying the returned `BlockEditResult` to local state.
- **Recommended Improvements:**
  - Replace `setInterval` with a self-scheduling `setTimeout` after `pollOnce()` completes.
  - During polling, only call `refreshReview` if the currently selected page had no OCR blocks yet (or matches the newly completed page).
  - In `ReviewEditorPanel`, preserve dirty draft values when `review.blocks` updates for the same `(book_id, page_number, primary_run_id)`.

---

### 4.4 Full-page block re-renders on every keystroke & un-debounced search in `CorrectionMemoryPanel`
- **Locations:**
  - `frontend/src/components/ReviewEditorPanel.tsx` (lines 70, 361–618)
  - `frontend/src/components/CorrectionMemoryPanel.tsx` (lines 22–43, 87–94)
- **Root Cause:**
  1. In `ReviewEditorPanel`, `drafts` is stored in a single parent state map (`Record<string, string>`). Typing a character in one block's `<textarea>` updates `drafts` and re-renders **all 40–60 `<article className="block-card">` elements** and their suggestion lists on every keystroke.
  2. In `CorrectionMemoryPanel`, `load` depends on `query`, and `useEffect(() => { void load(); }, [load])` triggers an un-debounced `GET /api/v1/corrections?q=...` request on every character typed into the search input (without an `AbortController`), even though the form also has a "Search" submit button.
- **Recommended Improvements:**
  - Extract each block card into a memoized `<BlockCard />` component (`React.memo`) or manage draft input state locally within each block card.
  - Debounce `query` changes (250–300ms) and cancel stale in-flight requests with `AbortController` in `CorrectionMemoryPanel`.
