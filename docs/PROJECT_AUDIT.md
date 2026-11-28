# Comprehensive Engineering Audit — Telugu Digitizer

**Audit Date:** 2026-11-28  
**Audit Mode:** Strictly Read-Only Static & Architectural Review  
**Scope:** Full repository (`/Users/shanmukhan/Developer/repo/telugu-digitizer`) — Backend (FastAPI/SQLAlchemy/PostgreSQL), PDF & OCR Pipelines (PyMuPDF/PaddleOCR/Tesseract), Telugu NLP & Dictionary Services, DOCX/TXT Exporter, Web Studio (React/TypeScript/Vite/PDF.js), Mobile Client (Flutter/Dart), Deployment & Backup Tooling, and Test Suite.

---

## 1. Executive Summary

`telugu-digitizer` is a thoughtfully engineered, local-first Telugu book digitization studio built around strong foundational invariants: source PDFs are stored read-only and deduplicated by SHA-256, raw machine OCR outputs are treated as immutable, human edits are recorded in an append-only audit log (`review_edits`), and correction memory is designed around opt-in contextual suggestions rather than silent global find-and-replace. The codebase spans ~16,200+ lines of core application source across Python (`src/`, `scripts/`, `alembic/`), TypeScript (`frontend/src/`), and Dart (`mobile/lib/`).

Despite its solid product philosophy, this audit identified **32 substantiated findings** (**1 Critical, 13 High, 14 Medium, 3 Low, 1 Informational**) across security, performance, Telugu OCR quality, architecture, and verification:

- **Most urgent security & data-integrity risk (`SEC-01`, `SEC-02`, `SEC-03`):** While localhost-only single-user operation is safe without login, the repository ships Raspberry Pi and public-internet hosting templates (`deploy/raspberry-pi/install.sh`, `deploy/.env.lahari.example`) configured with **zero authentication by default**, exposing destructive endpoints (`DELETE /api/v1/books/{id}`, OCR job launching, transcript editing, custom dictionary mutation) to anonymous visitors on `https://lahari.org/telugu/`. Compounding this, `POST /api/v1/books` buffers the entire uploaded PDF into RAM (`await file.read()`) *before* enforcing `MAX_UPLOAD_MB`, enabling trivial OOM kills on constrained hosts such as a 4–8 GB Raspberry Pi.
- **Confirmed functional & deployment defects (`ARCH-01`, `ARCH-02`, `ARCH-03`):** The frontend's `Save Digital Text` action sends `{ digital_text_content }` to an endpoint expecting `{ text }`, causing a guaranteed HTTP `422 VALIDATION_ERROR`. Deleting a book leaves orphaned files in `workspace/training_crops/{book_id}` and does not cancel in-flight OCR jobs. Fresh Docker and Raspberry Pi installs fail to copy or generate the 186k-word Telugu lexicon (`telugu_lexicon.tsv.gz`) and 167 MB dictionary (`telugu_dictionary.sqlite`), shipping with degraded auto-correct and empty dictionary definitions.
- **Highest-impact performance bottlenecks (`PERF-01`–`PERF-04`):** Every `POST .../autocorrect` request performs an uncached 3-table join scanning up to 15,000 `document_text_blocks` plus all active `correction_memory` and `custom_dictionary_words` to rebuild Python bigram/skeleton structures from scratch. Full-table loads and N+1 queries occur in review, batch-save, dictionary search, and OCR resume paths. OCR inference runs inside the web API process without per-page timeouts, creating both single-worker hang hazards and process-wide crash blast radius.
- **Telugu OCR & script quality gaps (`OCR-01`–`OCR-03`):** Neither OCR provider performs geometric reading-order sorting, multi-column segmentation, or header/footer filtering; DOCX export emits every OCR line as an isolated paragraph, silently drops the `verse` block role, omits run-level Complex Script (`w:cs`) font settings, and lacks NFC normalization / XML control-character sanitization. In Telugu NLP, `is_telugu_word` rejects tokens containing `\u200c` (ZWNJ), causing Tesseract's most frequent Telugu conjunct artifact (spurious ZWNJ injection) to bypass auto-correct and spell-check completely, while `.split()` / `" ".join()` collapses multi-line breaks in edited blocks.
- **Verification gap (`TEST-01`):** Although the evaluation framework (`src/evaluation/metrics.py`, `scripts/benchmark.py`) is well structured, only **1 synthetic 3-line page** (`demo_book`) has been benchmarked (`artifacts/benchmark/demo-run/benchmark_report.md`). No real printed multi-book Telugu ground-truth benchmark or p95/peak-RAM telemetry exists yet.

---

## 2. Repository Overview

### Component Inventory & Scale

| Layer | Location | Primary Technologies | Approximate Scale |
|---|---|---|---|
| **Backend API** | `src/api/` (`app.py`, `routes.py`, `schemas.py`, `errors.py`) | FastAPI, Pydantic v2, Uvicorn, Starlette | ~1,748 LOC (4 files) |
| **Domain Services** | `src/services/` (`book`, `ocr`, `review`, `correction`, `lexicon`, `dictionary`, `export`) | SQLAlchemy 2.x, PyMuPDF, OpenCV, Pillow, `python-docx`, `sqlite3` | ~5,014 LOC (7 files) |
| **PDF & OCR Core** | `src/pdf/`, `src/ocr/`, `src/common/`, `src/evaluation/` | PyMuPDF, PaddleOCR PP-OCRv5 (`te`), Tesseract 5 (`tel`), `regex`, `rapidfuzz`, `pandas` | ~1,580 LOC (12 files) |
| **Persistence & Config** | `src/db/`, `src/core/`, `alembic/versions/` | PostgreSQL (`psycopg` v3), Alembic (4 revisions), local filesystem storage | ~900 LOC |
| **Web Review Studio** | `frontend/src/` | React 19, TypeScript, Vite 6, `pdfjs-dist`, Vitest | ~6,200+ LOC (main `App.tsx`: 1,489; `ReviewEditorPanel.tsx`: 1,254) |
| **Mobile Companion** | `mobile/lib/` | Flutter / Dart, `http`, `shared_preferences`, `file_picker` | 12 Dart source files + 1 widget test file |
| **CLI & Ops Scripts** | `scripts/` | Python CLI utilities, shell backup & launchd installers | 9 scripts |
| **Deployment** | `deploy/`, `docker-compose.yml` | Docker, Caddy, `systemd`, Cloudflare Tunnel, Raspberry Pi scripts | 10 config/script files |
| **Static/Model Assets** | `models/` (git-ignored) | `tel.traineddata` (8.7 MB), `telugu_lexicon.tsv.gz` (903 KB, 186,086 words), `telugu_dictionary.sqlite` (167 MB) | Local runtime artifacts |
| **Automated Tests** | `tests/`, `frontend/src/**/*.test.tsx`, `mobile/test/` | `pytest`, `vitest`, `flutter_test` | 10 Python test files, 6 Vitest suites, 1 Flutter test file |

### Application Entry Points

1. **Web API & Bundled SPA:** `scripts/run_api.py` → `src.api.app:create_app()` (binds `127.0.0.1:8000` by default; serves `frontend/dist/` SPA when built).
2. **CLI Pipeline & Benchmark Tools:** `scripts/render_pdf.py`, `scripts/run_ocr.py`, `scripts/benchmark.py`.
3. **Lexicon & Dictionary Builders:** `scripts/build_telugu_lexicon.py`, `scripts/build_telugu_dictionary_db.py`.
4. **Local DB & Backup Utilities:** `scripts/manage_local_pg.py`, `scripts/backup_pi_to_mac.sh`, `scripts/install_mac_backup_agent.sh`.
5. **Mobile App:** `mobile/lib/main.dart` → `StudioViewModel` → `DigitizerRepository` → `DigitizerApiService`.

---

## 3. Architecture and Data Flow

### Actual Implemented Pipeline

```text
[Client: React Web Studio / Flutter Mobile / CLI]
        │
        ▼  POST /api/v1/books (multipart PDF; buffered fully in RAM via await file.read())
[Book Ingestion: src/services/book_service.py]
  ├─ SHA-256 deduplication check against books.source_sha256
  ├─ Store read-only PDF (0o444) at workspace/originals/{book_id}/source.pdf
  ├─ PyMuPDF per-page classification (scanned_image | mixed | digital_text)
  │    └─ has_legacy_font_encoding() checks PUA / Latin-1 heuristics
  └─ Insert books + book_pages rows (page PNGs rendered lazily on demand)
        │
        ▼  POST /api/v1/books/{id}/ocr-runs
[In-Process Background Worker: OCRJobExecutor (ThreadPoolExecutor, max_workers=1)]
  ├─ Render page PNG on demand via PyMuPDF (default 300 DPI) → workspace/pages/{book_id}/
  ├─ Optional OpenCV preprocessing: none | contrast_clahe | deskew
  ├─ Engine Inference (reused provider instance per (engine, psm)):
  │    ├─ PaddleOCRProvider: PP-OCRv5_server_det + te_PP-OCRv5_mobile_rec (in-process)
  │    └─ TesseractOCRProvider: tesseract CLI subprocess per page (-l tel --oem 1)
  ├─ Persist raw payloads (*.raw.json / *.raw.tsv / *.raw.txt) + structured page JSON
  └─ Insert immutable ocr_blocks rows (raw_text, normalized_text, polygon, confidence)
        │
        ▼  GET /pages/{n}/review  |  POST /pages/{n}/autocorrect  |  POST /edits & /batch-save
[Proofreading, Correction Memory & Telugu Lexicon Layer]
  ├─ Comparator matching (vertical bbox overlap + index fallback) & low-conf flags
  ├─ Contextual suggestions from correction_memory (book_only + global_suggestion)
  ├─ Opt-in Auto-Correct: correction_memory + 186k Telugu lexicon + uncached DB bigram model
  ├─ Standalone Telugu Dictionary: read-only SQLite FTS5 (167 MB) + PostgreSQL custom_dictionary_words
  └─ Append-only review_edits + mutable document_text_blocks + optional training_samples crops
        │
        ▼  POST /api/v1/books/{id}/exports
[Export Service: src/services/export_service.py]
  ├─ Resolve human_approved (document_text_blocks / latest review_edits) or raw_ocr
  ├─ Generate DOCX (editable_flow | page_preserving via python-docx) or UTF-8 TXT
  ├─ Re-open generated DOCX in memory to validate round-trip integrity
  └─ Save artifact + export-manifest.json under workspace/exports/{book_id}/{export_id}/
```

### Architectural Observations

- **Stateful In-Process Job Queue:** `OCRJobExecutor` (`src/services/ocr_service.py`) runs a single-thread `ThreadPoolExecutor` inside the FastAPI process. Startup recovery (`src/api/app.py:48-73`) cleanly marks interrupted `running`/`queued` runs as `partial`, enabling page-level resume, but in-process execution couples web availability directly to native ML C++ runtime stability.
- **Dual Persistence Stores:** Operational state lives in PostgreSQL (`books`, `book_pages`, `model_registry`, `processing_jobs`, `ocr_runs`, `ocr_blocks`, `review_edits`, `correction_memory`, `training_samples`, `document_text_versions`, `document_text_blocks`, `exports`, `custom_dictionary_words`), while large binary artifacts live under `WORKSPACE_DIR` and static Telugu dictionary data lives in a local read-only SQLite file (`models/lexicon/telugu_dictionary.sqlite`) plus gzipped TSV (`models/lexicon/telugu_lexicon.tsv.gz`).
- **Reverse-Proxy Subpath Support:** Frontend URL resolution (`resolveAppUrl` in `frontend/src/api/client.ts:40-45`) and relative Vite base (`base: "./"` in `frontend/vite.config.ts`) allow hosting under subpaths such as `/telugu/`.

---

## 4. Overall Risk Assessment

| Domain | Risk Level | Summary |
|---|---|---|
| **Security (Public / Network Hosting)** | **Critical** | Default Raspberry Pi / `lahari.org` configs ship without authentication while exposing destructive CRUD & heavy compute APIs; unbounded RAM upload buffering enables trivial OOM DoS; Docker container runs as `root` with `FORWARDED_ALLOW_IPS=*`. |
| **Security (Localhost-Only Use)** | **Medium** | Local loopback binding (`127.0.0.1:8000`) and workspace path containment mitigate remote threats, but malformed PDF pixel-bombs, unverified external downloads, and `--auth=trust` local Postgres remain addressable risks. |
| **Performance & Scalability** | **High** | Acceptable for single-user small books, but degrades sharply under multi-book corpora (uncached 15k-row bigram rebuild per autocorrect, full-table scans in review/dictionary/corrections) and 300–500+ page books (double-RAM DOCX export, no OCR timeouts, N+1 DB writes). |
| **Telugu OCR & Script Fidelity** | **High** | Immutable raw OCR and NFC evaluation metrics are strong, but missing column/reading-order sorting, ZWNJ/ZWJ handling mismatch with Tesseract output, newline stripping in auto-correct, and DOCX `verse` / `w:cs` / control-char gaps directly affect digitized book accuracy. |
| **Reliability & Maintainability** | **High** | Confirmed broken `Save Digital Text` API contract (HTTP 422), incomplete book cleanup + uncancelled active jobs on delete, missing dictionary artifacts in fresh Docker/Pi builds, and monolithic React files hinder reliable operation and iteration. |
| **Testing & Verification** | **Medium-High** | Good unit/API test coverage for happy paths across Phases 1–5, but lacks a real multi-book printed Telugu benchmark, contract tests between TS client and Pydantic schemas, security/DoS tests, and shared DB test fixtures. |

---

## 5. Findings Summary Table

Sorted by **Severity** (`Critical` → `High` → `Medium` → `Low` → `Informational`) and **Priority** (`P0` → `P1` → `P2` → `P3`).

| ID | Category | Severity | Finding | File | Priority |
|---|---|---|---|---|---|
| `SEC-01` | Security | Critical | Public/network deployment defaults to zero authentication on destructive & compute-heavy endpoints | `deploy/raspberry-pi/install.sh` | P0 |
| `SEC-02` | Security | High | Entire PDF upload buffered in RAM before `MAX_UPLOAD_MB` size enforcement (OOM DoS) | `src/api/routes.py` | P0 |
| `ARCH-01` | Architecture / Correctness | High | Broken `Save Digital Text` API payload contract (guaranteed HTTP 422) & dropped manual block `bbox` | `frontend/src/api/client.ts` | P0 |
| `ARCH-02` | Architecture / Reliability | High | `delete_book_and_artifacts` leaks `training_crops/` and fails to cancel active OCR jobs | `src/services/book_service.py` | P0 |
| `PERF-04` | Performance / Reliability | High | No per-page OCR inference timeout, in-process C++ crash blast radius, and per-page Tesseract cold starts | `src/ocr/tesseract_provider.py` | P0 |
| `SEC-03` | Security | High | Docker image runs as `root` and trusts arbitrary `X-Forwarded-*` headers (`FORWARDED_ALLOW_IPS=*`) | `deploy/Dockerfile` | P1 |
| `PERF-01` | Performance | High | Uncached full-DB `SentenceContextModel` rebuild (up to 15k blocks + corrections) on every `/autocorrect` call | `src/services/lexicon_service.py` | P1 |
| `PERF-02` | Performance | High | Unbounded full-table loads and N+1 SQL queries across review, batch-save, dictionary, corrections, and OCR resume | `src/services/review_service.py` | P1 |
| `PERF-03` | Performance | High | Full-book `OCRBlock` JSONB hydration and double-RAM DOCX generation + round-trip re-parsing | `src/services/export_service.py` | P1 |
| `OCR-01` | Telugu OCR Quality | High | Missing geometric reading-order sorting, multi-column segmentation, paragraph reconstruction, and header/footer filtering | `src/ocr/paddle_provider.py` | P1 |
| `OCR-02` | Telugu OCR Quality | High | Auto-correct/suggestions collapse newlines; ZWNJ mismatch bypasses Tesseract conjunct fixes; substring replace bug | `src/services/lexicon_service.py` | P1 |
| `OCR-03` | Telugu OCR Quality | High | DOCX export drops `verse` role, omits run-level Complex Script (`w:cs`) font, skips NFC, and allows XML control chars | `src/services/export_service.py` | P1 |
| `ARCH-03` | Architecture / Deployment | High | Fresh Docker and Raspberry Pi install scripts omit Telugu lexicon and SQLite dictionary artifacts | `deploy/Dockerfile` | P1 |
| `TEST-01` | Testing / Benchmarking | High | No real multi-book printed Telugu ground-truth benchmark (only 1 synthetic page); missing p95 latency & peak RAM | `artifacts/benchmark/demo-run/benchmark_report.md` | P1 |
| `SEC-04` | Security | Medium | Malformed/adversarial PDF pixel-bomb exposure with no max page pixel-area limit or render timeout | `src/services/book_service.py` | P1 |
| `PERF-05` | Performance / Concurrency | Medium | Blocking ~5.4s cold-start lexicon indexing under global lock and unsafe `_PAGE_RENDER_LOCKS.clear()` race | `src/services/book_service.py` | P2 |
| `PERF-06` | Performance / Concurrency | Medium | Redundant PNG decoding, 3-channel CLAHE bloat, unsynchronized provider cache, and duplicate OCR run submission | `src/services/ocr_service.py` | P2 |
| `PERF-07` | Performance | Medium | High-frequency frontend full-page-list polling and sequential per-block HTTP loop in `handleBatchApproveUnflagged` | `frontend/src/App.tsx` | P2 |
| `SEC-05` | Security | Medium | Hardcoded default weak DB password, `--auth=trust` local PostgreSQL, and cleartext HTTP LAN preset in mobile app | `src/core/config.py` | P2 |
| `SEC-06` | Security | Medium | Unpinned external model/dictionary downloads without SHA-256 verification and dual OpenCV packages in lockfile | `scripts/build_telugu_lexicon.py` | P2 |
| `SEC-07` | Security | Medium | Missing HTTP security headers in FastAPI, wildcard CORS methods/headers, exposed `/docs`, and path leak in `/health` | `src/api/app.py` | P2 |
| `OCR-04` | Telugu OCR Quality | Medium | 7-bit ASCII legacy Telugu font PDFs bypass `has_legacy_font_encoding` and export garbled text | `src/pdf/rasterizer.py` | P2 |
| `OCR-05` | Telugu OCR Quality | Medium | Fragile full-page `deskew`, naive index comparator fallback, and ARM64 `1280px` detection downscaling tradeoff | `src/services/ocr_service.py` | P2 |
| `OCR-06` | Telugu OCR Quality | Medium | Lexicon index truncation (`skeleton_index` / top-60k `delete1_index`) and uncalibrated hardcoded confidence thresholds | `src/services/lexicon_service.py` | P2 |
| `ARCH-04` | Maintainability | Medium | Monolithic React components (`App.tsx` 1,489 LOC; `ReviewEditorPanel.tsx` 1,254 LOC) and mobile client feature drift | `frontend/src/App.tsx` | P2 |
| `ARCH-05` | Maintainability | Medium | Silent exception swallowing in training crop capture, process-global `os.environ` mutation, and fragmented dependency manifests | `src/services/review_service.py` | P2 |
| `TEST-02` | Testing | Medium | Missing API contract tests between frontend client & Pydantic schemas and missing coverage for digital-text edit endpoint | `tests/test_phase3_review_api.py` | P2 |
| `TEST-03` | Testing | Medium | Missing security, streaming upload-limit, adversarial-PDF, and concurrent OCR cancellation/resume tests | `tests/test_deployment_and_security.py` | P2 |
| `SEC-08` | Security | Low | Missing `max_length`/`max_items` bounds on API text/batch schemas, raw XML helper interpolation, and TOFU SSH backup check | `src/api/schemas.py` | P3 |
| `ARCH-06` | Maintainability | Low | Stale Phase-1-only notice and private LAN IP/user in `README.md`; lack of request correlation IDs & structured metrics | `README.md` | P3 |
| `TEST-04` | Testing | Low | Duplicated PostgreSQL reset fixture across 6 test files and missing Telugu Unicode/DOCX edge-case tests | `tests/test_phase2_api_and_db.py` | P3 |
| `PERF-08` | Performance | Informational | Hardware acceleration evaluation: CPU vs GPU/NPU suitability for PaddleOCR PP-OCRv5 & Tesseract 5 workloads | `src/ocr/paddle_provider.py` | P3 |

---

## 6. Detailed Performance Findings

### PERF-01 — Uncached Full-Database `SentenceContextModel` Rebuild on Every `/autocorrect` Request
- **Category:** Performance (Backend & NLP)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/lexicon_service.py`
- **Relevant Function / Component:** `build_sentence_context_model`, `propose_page_autocorrections`
- **Line Numbers:** `613–670`, `797`
- **Description:** Every call to `POST /api/v1/books/{book_id}/pages/{page_number}/autocorrect` builds a fresh `SentenceContextModel` from scratch by joining `document_text_blocks`, `document_text_versions`, and `books` (fetching up to `15,000` rows), loading *all* active `correction_memory` rows for the language, loading *all* `custom_dictionary_words`, and running NFC normalization, whitespace tokenization, punctuation stripping, `Counter` accumulation, and `visual_skeleton` indexing in Python.
- **Evidence from Implementation:** `propose_page_autocorrections` calls `build_sentence_context_model(db=db, book_id=book.id, language_code=book.language_code)` directly at line `797` with no TTL cache, version stamp, or per-book memoization. Inside `build_sentence_context_model` (`624–668`), all 3 queries execute unconditionally on every request.
- **Why It Matters:** Proofreaders trigger auto-correct page by page during active editing. As the database grows across several digitized books (reaching the 15,000-block cap), every click triggers thousands of Python string operations and large PostgreSQL result transfers.
- **Actual or Potential Impact:** Hundreds of milliseconds to multiple seconds of CPU spike and DB I/O per page click on Raspberry Pi ARM64; rapid memory churn from repeatedly allocating/freeing large `Counter` and `defaultdict(set)` objects.
- **Recommended Solution:** Introduce a bounded, thread-safe in-memory cache (e.g., keyed by `(language_code, book_id)` with a lightweight invalidation token bumped on `submit_block_edit`, `batch_save_and_approve_page`, correction memory updates, or custom dictionary mutations, or a short TTL + explicit invalidation). Split the model into a shared cross-book base model (refreshed infrequently) plus a small per-book overlay.
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** None.

---

### PERF-02 — Unbounded Full-Table Loads and N+1 SQL Queries Across Core Services
- **Category:** Performance (Database & API)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/review_service.py`, `src/services/dictionary_service.py`, `src/services/correction_service.py`, `src/services/ocr_service.py`
- **Relevant Function / Component:** `get_page_review_payload`, `batch_save_and_approve_page`, `search_dictionary`, `_load_custom_context`, `list_corrections`, `OCRJobExecutor.execute_run`
- **Line Numbers:** `src/services/review_service.py:284–290, 906–1012`; `src/services/dictionary_service.py:77–84, 240–245`; `src/services/correction_service.py:552–580`; `src/services/ocr_service.py:493–506`
- **Description:** Multiple hot paths fetch entire tables into Python memory for filtering or execute per-item queries inside loops:
  1. `get_page_review_payload` (`review_service.py:284–290`) fetches *every* active `CorrectionMemory` row across *all* books for `language_code` on every page navigation, relying on Python's `build_suggestion_index` to discard other books' `book_only` rows.
  2. `batch_save_and_approve_page` (`review_service.py:906–973`) executes `db.get(OCRBlock, blk_id)`, a `ReviewEdit` lookup, and a `DocumentTextBlock` lookup inside the `for item in edits_list:` loop (3N+ queries per page save). Worse, if `primary_run_id` is omitted (`1010–1012`), it invokes the full `get_page_review_payload()` (recomputing comparator matches and correction suggestions) solely to discover `primary_run_id`.
  3. `search_dictionary` (`dictionary_service.py:240–245`) loads *all* `CustomDictionaryWord` rows from PostgreSQL into Python on every debounced keystroke (280 ms in UI) and filters substring matches in Python; `_load_custom_context` (`77–84`) loads all custom words again whenever fallback suggestions run.
  4. `list_corrections` (`correction_service.py:552–580`) returns the entire `correction_memory` table with no `LIMIT`/`OFFSET` pagination and performs case-insensitive substring search in Python.
  5. `OCRJobExecutor.execute_run` (`ocr_service.py:493–506`) checks whether each page already has `OCRBlock`s via a per-page `SELECT` + `db.commit()` inside the page loop; resuming page 390 of a 406-page book executes 389 sequential queries and 389 commits before processing page 390.
- **Evidence from Implementation:** Verified directly in the cited lines of all four service files.
- **Why It Matters:** Latency scales linearly with total historical corpus size rather than the current page size, degrading review snappiness and database health over time.
- **Actual or Potential Impact:** Noticeable UI lag during page turns, slow batch page saves, high PostgreSQL transaction overhead on resume, and excessive JSON payloads on the Corrections tab when thousands of rules accumulate.
- **Recommended Solution:**
  - Push `OR (scope = 'global_suggestion', book_id = :book_id)` into SQL in `get_page_review_payload`.
  - Preload target `OCRBlock`s, latest `ReviewEdit`s (using `DISTINCT ON` or a single grouped query), and `DocumentTextBlock`s in bulk inside `batch_save_and_approve_page`, and resolve `primary_run_id` via a lightweight helper instead of calling `get_page_review_payload`.
  - Filter `CustomDictionaryWord` in SQL using `ILIKE` / PostgreSQL trigram (`pg_trgm`) index or an in-memory cached index, and add `limit`/`offset` pagination to `GET /api/v1/corrections`.
  - In `execute_run`, preload all completed `book_page_id`s for `ocr_run.id` in one `SELECT DISTINCT book_page_id` query and update `job.progress_current` once for skipped pages.
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** Adding pagination to `GET /api/v1/corrections` requires a minor coordinated update in `frontend/src/components/CorrectionMemoryPanel.tsx` and `mobile/lib/`.

---

### PERF-03 — Memory-Heavy Full-Book Export Hydration and Double-RAM DOCX Round-Trip Validation
- **Category:** Performance (Export & Memory)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/export_service.py`
- **Relevant Function / Component:** `_collect_export_pages`, `_build_docx_bytes`, `_validate_docx_bytes`
- **Line Numbers:** `197–226`, `419–467`
- **Description:** Exporting a book loads all `OCRBlock` ORM entities for the entire run (`197–203`)—including large `raw_engine_payload` and `polygon` JSONB columns that export never reads—then passes every block UUID into two `IN (...)` queries on `ReviewEdit` (`209–215`, loading *all historical revisions* of every block across the book, not just the latest!) and `DocumentTextBlock` (`218–225`). Subsequently, `_build_docx_bytes` serializes the entire DOCX to an in-memory `io.BytesIO` buffer (`419–422`), and `_validate_docx_bytes` (`432–467`) immediately parses that full buffer back into a second complete `python-docx` / `lxml` XML DOM in RAM while the first `Document` object (`doc`) is still referenced in the calling frame!
- **Evidence from Implementation:** `select(OCRBlock)` at line `199` does not `defer()` `raw_engine_payload` or `polygon`; `select(ReviewEdit)` at line `210` fetches full edit history for every block; line `424` calls `_validate_docx_bytes(raw_bytes=raw_bytes, ...)` while `doc` (`328`) and `buf` (`419`) are still in scope.
- **Why It Matters:** On a 400–600 page book (~15,000+ OCR lines with multi-revision edit history), hydrating JSONB payloads + full edit history + two simultaneous `lxml` XML trees can easily spike RSS by hundreds of megabytes inside the API process (which shares a `4500M` cgroup limit on Raspberry Pi alongside PaddleOCR and the lexicon).
- **Actual or Potential Impact:** High GC pressure, slow export latency, HTTP reverse-proxy timeouts, or cgroup OOM kills when exporting large books concurrently with OCR.
- **Recommended Solution:**
  1. Select only required scalar columns (`OCRBlock.id`, `book_page_id`, `block_type`, `raw_text`, `reading_order`, `block_index`) instead of full ORM rows with JSONB columns.
  2. Query only the latest `ReviewEdit` per block using PostgreSQL `DISTINCT ON (ocr_block_id)` joined to `ocr_blocks` (eliminating huge `IN (...)` lists and historical edit rows).
  3. Stream DOCX bytes directly to a temporary file on disk, explicitly `del doc` before opening the file for validation, and validate XML structure via lightweight `zipfile` + streaming `iterparse` (or bounded re-open after freeing the builder DOM).
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** None.

---

### PERF-04 — Missing Per-Page OCR Timeouts, In-Process Crash Blast Radius, and Per-Page Tesseract Subprocess Cold Starts
- **Category:** Performance & Reliability (OCR Inference)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/ocr/tesseract_provider.py`, `src/ocr/paddle_provider.py`, `src/services/ocr_service.py`, `deploy/raspberry-pi/telugu-digitizer.service`
- **Relevant Function / Component:** `TesseractOCRProvider.recognize`, `PaddleOCRProvider.recognize`, `OCRJobExecutor`, `systemd` unit
- **Line Numbers:** `src/ocr/tesseract_provider.py:158–178`; `src/ocr/paddle_provider.py:208`; `src/services/ocr_service.py:236, 551`; `deploy/raspberry-pi/telugu-digitizer.service:18`
- **Description:**
  1. Neither `subprocess.run(cmd, capture_output=True)` (`tesseract_provider.py:178`) nor `self._ocr.predict(str(img))` (`paddle_provider.py:208`) enforces a per-page timeout. A pathological/corrupt page image that hangs OCR blocks the sole `ThreadPoolExecutor(max_workers=1)` (`ocr_service.py:236`) indefinitely—stalling every queued OCR job across all books until the server is restarted.
  2. PaddleOCR runs in-process inside the FastAPI server thread. Native C++ memory corruption, OpenBLAS/oneDNN crashes, or OOM spikes (`MemoryMax=4500M` in `telugu-digitizer.service:18`) terminate the entire web server, dropping all active proofreading sessions.
  3. `TesseractOCRProvider.recognize` spawns a new `tesseract` OS subprocess and temporary directory for every page (`158–178`), cold-loading the 8.7 MB `tel.traineddata` LSTM weights 400+ times for a 400-page book.
- **Evidence from Implementation:** `subprocess.run(cmd, capture_output=True)` has no `timeout=` argument; `OCRJobExecutor.__init__` initializes `ThreadPoolExecutor(max_workers=1)` in-process; PaddleOCR runs inside the same worker thread.
- **Why It Matters:** Long-running book digitization jobs (hours on Raspberry Pi ARM64) must isolate native OCR failures from the interactive HTTP studio and must recover gracefully from a single hung page.
- **Actual or Potential Impact:** A single stuck page freezes all OCR processing permanently; any native PaddlePaddle segfault or OOM takes down the entire web app and dictionary service; per-page Tesseract startup adds avoidable CPU/disk overhead.
- **Recommended Solution:**
  1. Add a configurable `timeout` (e.g., `OCR_PAGE_TIMEOUT_SEC`, default 120–180s) to `TesseractOCRProvider` immediately.
  2. Run OCR execution in an isolated worker subprocess (or dedicated `telugu-digitizer-worker` systemd service polling `ocr_runs` from PostgreSQL) so per-page timeouts can cleanly terminate stuck PaddleOCR calls and native crashes cannot take down the FastAPI web UI.
  3. Keep `max_workers=1` for PaddleOCR (which already multi-threads via `PADDLE_CPU_THREADS`), and evaluate persistent `tesserocr` (or multi-page list/batching) for Tesseract if Tesseract throughput becomes a bottleneck on multi-hundred-page books.
- **Estimated Implementation Complexity:** Large (for full separate worker process); Small (for Tesseract timeout alone)
- **Dependencies / Prerequisites:** Separate worker process requires updating `deploy/raspberry-pi/telugu-digitizer.service`, `deploy/compose.lahari.yml`, and `scripts/run_api.py`.

---

### PERF-05 — Blocking Cold-Start Lexicon Indexing Under Global Lock and Unsafe `_PAGE_RENDER_LOCKS.clear()` Race
- **Category:** Performance & Concurrency
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/lexicon_service.py`, `src/services/book_service.py`
- **Relevant Function / Component:** `get_telugu_lexicon`, `_get_page_render_lock`
- **Line Numbers:** `src/services/lexicon_service.py:594–610`; `src/services/book_service.py:30–43`
- **Description:**
  1. `get_telugu_lexicon()` lazily decompresses and indexes 186,086 words (`skeleton_index` + `delete1_index` over 60,000 words) synchronously on the first `/autocorrect` or `/dictionary/search` typo request while holding `_LEXICON_LOCK`. On Raspberry Pi ARM64 (as documented in `docs/17-telugu-lexicon-autocorrect-and-backup-plan.md`), this blocks for ~5.4 seconds on cold start, stalling concurrent dictionary/autocorrect requests waiting on the lock.
  2. `_get_page_render_lock` (`book_service.py:39–40`) resets the lock table with `if len(_PAGE_RENDER_LOCKS) > 512: _PAGE_RENDER_LOCKS.clear()`. Clearing the dictionary while another worker thread holds one of those locks allows a concurrent request for the same `(book_id, page_number)` to create a *second* distinct `threading.Lock` and race on rendering/writing the same PNG and updating `BookPage` columns.
- **Evidence from Implementation:** `book_service.py:39–42` clears `_PAGE_RENDER_LOCKS` without checking whether entries are locked; `lexicon_service.py:604–610` performs synchronous cold load under `_LEXICON_LOCK`.
- **Why It Matters:** First-user latency spikes feel like hangs, and the lock-clearing bug undermines the exact double-render protection `_PAGE_RENDER_LOCKS` was designed to provide on large (>512 page) books.
- **Actual or Potential Impact:** 5+ second cold-start stall on Raspberry Pi; potential duplicate PyMuPDF renders and concurrent DB row updates (`BookPage`) when viewing/processing books exceeding 512 pages.
- **Recommended Solution:** Replace `_PAGE_RENDER_LOCKS` with a fixed-size striped lock table (e.g., 64 or 128 pre-allocated `threading.Lock`s indexed by `hash((book_id, page_number)) % 64`) or `weakref.WeakValueDictionary`—eliminating unbounded growth and unsafe `.clear()`. Optionally warm the lexicon in a background daemon thread during FastAPI `lifespan` startup (or pre-serialize an indexed cache / SQLite index) so the first user request never stalls.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

### PERF-06 — Redundant PNG Decoding, 3-Channel Grayscale Bloat, Unsynchronized Provider Cache, and Duplicate OCR Submission
- **Category:** Performance & Concurrency (PDF/OCR Pipeline)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/ocr_service.py`, `src/pdf/rasterizer.py`
- **Relevant Function / Component:** `OCRJobExecutor.get_provider`, `_apply_preprocessing_profile`, `execute_run`, `create_or_reuse_ocr_runs`, `resume_ocr_run`, `render_pdf_pages`
- **Line Numbers:** `src/services/ocr_service.py:238–255, 361–364, 532–536, 737–760, 813–834`; `src/pdf/rasterizer.py:180–186`
- **Description:**
  1. `execute_run` (`ocr_service.py:532–536`) opens every page PNG with Pillow (`Image.open(img_path)`) solely to log `(img_w, img_h)`, even when `_ensure_page_image_path` / `BookPage` already knows the dimensions.
  2. `_apply_preprocessing_profile` (`ocr_service.py:361–364`) converts `contrast_clahe` grayscale output back to 3-channel BGR (`cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)`) before saving as PNG, inflating preprocessed image disk size and PNG encoding time.
  3. `render_pdf_pages` (`rasterizer.py:180–186`) when `skip_existing=True` reads the entire PNG into RAM (`image_path.read_bytes()`) and decodes it via `pymupdf.open(stream=png_bytes, filetype="png")` solely to read `width_px`/`height_px`, whereas Pillow `Image.open(image_path).size` reads only the 24-byte PNG header.
  4. `OCRJobExecutor._providers` (`ocr_service.py:238–255`) is read/mutated without a lock from both HTTP request threads (`create_or_reuse_ocr_runs:761`) and the background worker thread (`execute_run:456`).
  5. `create_or_reuse_ocr_runs` (`ocr_service.py:737–758`) checks `existing.status == "completed"` and `existing.status in ("partial", "failed")`, but **omits** `existing.status in ("queued", "running")`—allowing double-clicks to create duplicate runs for the same `idempotency_key`. Similarly, `resume_ocr_run` (`823–832`) only guards against `status == "completed"`, allowing an already `running`/`queued` run to be re-queued concurrently.
- **Evidence from Implementation:** Confirmed directly across all cited lines.
- **Why It Matters:** Duplicate OCR submissions waste minutes/hours of CPU on Raspberry Pi and can trigger unique-constraint races on `ocr_blocks`; redundant image decodes and bloated PNGs waste I/O and SD-card/NVMe space.
- **Actual or Potential Impact:** Duplicate wasted OCR jobs on impatient clicks/retries; slower CLI `skip_existing` re-runs; ~2–3× larger `contrast_clahe` PNG cache files.
- **Recommended Solution:**
  - Guard `existing.status in ("queued", "running")` in both `create_or_reuse_ocr_runs` (reuse the active run!) and `resume_ocr_run` (no-op return!).
  - Protect `self._providers` with `self._lock`.
  - Pass `(width_px, height_px)` directly from `_ensure_page_image_path` / `_apply_preprocessing_profile` instead of re-opening with Pillow, and use Pillow header-only `Image.open(path).size` in `rasterizer.py`.
  - Verify whether PaddleOCR/Tesseract accept single-channel grayscale PNGs (PaddleOCR decodes via OpenCV `IMREAD_COLOR` automatically) to save preprocessed grayscale as 1-channel PNG.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

### PERF-07 — High-Frequency Frontend Full-Page-List Polling and Sequential Per-Block HTTP Loop
- **Category:** Performance (Frontend)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `frontend/src/App.tsx`, `frontend/src/components/SourcePageViewer.tsx`
- **Relevant Function / Component:** OCR polling `useEffect`, `handleBatchApproveUnflagged`, `SourcePageViewer`
- **Line Numbers:** `frontend/src/App.tsx:226–298, 720–756`; `frontend/src/components/SourcePageViewer.tsx:176`
- **Description:**
  1. During active OCR, `App.tsx:226–298` polls `getOcrRunStatus` every 1.5s, and every time `progress_current` advances by a single page, it re-fetches `listBookPages(bookId)` (returning all 400+ page metadata records), `listBookOcrRuns(bookId)`, and `getPageReview(...)`.
  2. `handleBatchApproveUnflagged` (`App.tsx:720–756`) executes a sequential `for (const blk of targets) { await submitBlockEdit(...); }` loop—sending 30–50 separate HTTP `POST` requests and database commits sequentially—even though the backend already provides an atomic `POST .../batch-save` endpoint (`batchSavePage` in `client.ts:210`).
  3. `SourcePageViewer.tsx:176` calls `pdfjsLib.getDocument(url)` with default options; unless `disableAutoFetch: true` and `disableStream: false` are explicitly configured, PDF.js may eagerly prefetch large portions of multi-hundred-MB PDFs over the network even when viewing a single page.
- **Evidence from Implementation:** `App.tsx:735–741` contains the sequential `for` loop of `await submitBlockEdit(...)`; `SourcePageViewer.tsx:176` passes a bare URL string to `pdfjsLib.getDocument(...)`.
- **Why It Matters:** Sequential HTTP requests over WAN (`https://lahari.org/telugu/`) multiply RTT latency by 30–50× and risk partial failure mid-page; excessive polling and eager PDF prefetching waste Raspberry Pi upload bandwidth and CPU.
- **Actual or Potential Impact:** Slow "Approve Unflagged" UX (5–15 seconds over WAN vs <200 ms with `batch-save`), partial approval state on network hiccups, and unnecessary bandwidth usage on large PDFs.
- **Recommended Solution:** Refactor `handleBatchApproveUnflagged` to submit one atomic `batchSavePage` call (`markPageApproved: false`, `approveRemainingBlocks: false`); throttle `listBookPages` refreshes during OCR polling (only refresh when the active page finishes or run transitions to terminal state); pass `{ url, disableAutoFetch: true, rangeChunkSize: 65536 }` to `pdfjsLib.getDocument` and ensure `Accept-Ranges: bytes` works through Apache/Caddy.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** Confirm Apache/Caddy reverse proxy preserves HTTP `Range` headers for `/api/v1/books/{id}/pdf`.

---

### PERF-08 — Hardware Acceleration Evaluation: CPU vs GPU/NPU Suitability for This Workload
- **Category:** Performance (Resource & Hardware Architecture)
- **Severity:** Informational
- **Confidence:** Observation
- **Exact File Path:** `src/ocr/paddle_provider.py`, `src/core/config.py`, `src/ocr/tesseract_provider.py`
- **Relevant Function / Component:** `PaddleOCRProvider.__init__`, `AppSettings.paddle_device`
- **Line Numbers:** `src/ocr/paddle_provider.py:51–113`; `src/core/config.py:36, 66`
- **Description:** This repository targets two real deployment environments: macOS Apple Silicon (`arm64` Mac Mini) and Linux ARM64 (`aarch64` Raspberry Pi), plus optional x86_64 Docker hosts. `PaddleOCRProvider` defaults to `device="cpu"` (`PADDLE_DEVICE=cpu`) with single-page sequential inference (`predict(str(img))`).
- **Evidence from Implementation:** `paddle_provider.py:90–94` caps `text_det_limit_side_len=1280` on Linux ARM64 and `1920` elsewhere; `ocr_service.py:551` calls `provider.recognize(img_path)` one page at a time; Tesseract 5 LSTM (`--oem 1`) is CPU-only.
- **Why It Matters:** Recommending GPU acceleration indiscriminately would be counterproductive for this project's actual hardware and model architecture.
- **Actual or Potential Impact:**
  - **Tesseract 5 (`tel`):** Pure CPU LSTM; GPUs provide zero speedup.
  - **Raspberry Pi (`aarch64`):** No supported CUDA/ROCm GPU for PaddlePaddle; CPU optimization (`ONNX Runtime` INT8/FP32 export or tuned `PP-OCRv5_mobile_det` vs `server_det` + `PADDLE_CPU_THREADS=4`) yields far larger practical speedups than GPU flags. Notably, the current config pairs `PP-OCRv5_server_det` (a heavy server detector) with `te_PP-OCRv5_mobile_rec` (a mobile recognizer) on a Raspberry Pi CPU!
  - **macOS Apple Silicon:** Official `paddlepaddle==3.3.1` CPU wheel does not leverage Apple Metal/MPS GPU acceleration; GPU acceleration is only meaningful if migrating to an NVIDIA CUDA x86_64 server *and* batching recognition crops across pages.
- **Recommended Solution:** Keep CPU execution for local/Pi targets rather than adding GPU complexity. Instead, benchmark `PP-OCRv5_mobile_det` vs `PP-OCRv5_server_det` (and ONNX Runtime CPU inference if supported for `te_PP-OCRv5_mobile_rec`) on real printed Telugu pages to measure the accuracy-vs-speed tradeoff objectively before switching models.
- **Estimated Implementation Complexity:** Medium (benchmarking & evaluation only)
- **Dependencies / Prerequisites:** Real printed Telugu benchmark dataset (`TEST-01`).

---

## 7. Detailed Security Findings

### SEC-01 — Public/Network Deployment Defaults to Zero Authentication on Destructive & Compute-Heavy Endpoints
- **Category:** Security (Authentication & Authorization)
- **Severity:** Critical *(for internet-exposed deployments such as `lahari.org/telugu/`; Low/Acceptable only when strictly bound to `127.0.0.1` on a single-user machine)*
- **Confidence:** Confirmed
- **Exact File Path:** `deploy/raspberry-pi/install.sh`, `deploy/.env.lahari.example`, `src/api/app.py`, `README.md`
- **Relevant Function / Component:** `install.sh` env generator, `require_basic_auth` middleware
- **Line Numbers:** `deploy/raspberry-pi/install.sh:77–97`; `deploy/.env.lahari.example:10–13`; `src/api/app.py:144–184`; `README.md:216`
- **Description:** The Raspberry Pi production installer (`install.sh`) generates `/etc/telugu-digitizer/env` with **no** `APP_AUTH_USERNAME` or `APP_AUTH_PASSWORD` ("Public open access (no login)"), and `README.md:216` documents `https://lahari.org/telugu/` as publicly open by default. Without authentication, any anonymous internet client can:
  - Permanently delete any digitized book, PDF, OCR output, and human corrections (`DELETE /api/v1/books/{id}`).
  - Upload up to 200 MB PDFs repeatedly (`POST /api/v1/books`), exhausting disk space and CPU.
  - Trigger expensive PaddleOCR/Tesseract runs (`POST /api/v1/books/{id}/ocr-runs`).
  - Overwrite/corrupt human-verified transcripts (`POST /edits`, `POST /batch-save`), poison `correction_memory`, and delete custom Telugu dictionary entries (`DELETE /api/v1/dictionary/custom/{id}`).
  - Furthermore, even when Basic Auth *is* enabled (`src/api/app.py:144–184`), there is no brute-force rate limiting or login lockout, and browsers automatically attach cached Basic Auth credentials to same-site requests without CSRF token validation.
- **Evidence from Implementation:** `src/api/app.py:144` only registers `require_basic_auth` when both `cfg.auth_username` and `cfg.auth_password` are non-empty; `deploy/raspberry-pi/install.sh:77–97` omits both variables entirely.
- **Why It Matters:** A single automated crawler, scanner, or malicious visitor hitting `https://lahari.org/telugu/api/v1/books` can wipe months of painstaking human Telugu proofreading work or brick the Raspberry Pi via disk/CPU exhaustion.
- **Actual or Potential Impact:** Complete unauthorized data loss (book & transcript deletion), unauthorized data corruption/poisoning, disk exhaustion, and sustained CPU DoS on any network-exposed deployment.
- **Recommended Solution:**
  - If the public site is intended for public **read-only dictionary lookup** while keeping book digitization private, separate authorization tiers: allow unauthenticated read-only `GET /api/v1/dictionary/stats|search|word` + `POST /api/v1/dictionary/check-text` (rate-limited), and **require authentication** for all book/OCR/review/correction/export/custom-word write & delete routes (or enforce authentication across the entire `/telugu/` studio via Cloudflare Access / Apache Basic Auth / session-cookie auth with CSRF protection).
  - Add startup warning logs (or fail-closed flag `REQUIRE_AUTH_FOR_NON_LOCALHOST=true`) whenever `PROXY_HEADERS=true` or `API_HOST != 127.0.0.1` without auth enabled.
  - Add reverse-proxy rate limiting (Caddy/Apache/Cloudflare WAF) on auth and upload/compute routes.
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** Decision on whether `https://lahari.org/telugu/` should keep the Dictionary tab public while locking Book Studio behind authentication.

---

### SEC-02 — Unbounded In-Memory PDF Upload Buffering Before `MAX_UPLOAD_MB` Enforcement
- **Category:** Security (File Handling / Denial of Service)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/api/routes.py`, `src/services/book_service.py`
- **Relevant Function / Component:** `upload_book`, `import_pdf_book`
- **Line Numbers:** `src/api/routes.py:153–179`; `src/services/book_service.py:120–126`
- **Description:** `upload_book` calls `pdf_bytes = await file.read()` (`routes.py:165`), reading the *entire* uploaded HTTP multipart payload into a Python `bytes` object in RAM before passing it to `import_pdf_book`, which only then checks `len(pdf_bytes) > settings.max_upload_mb * 1024 * 1024` (`book_service.py:120–126`). Even for a legitimate 200 MB PDF, Starlette spools the upload, `file.read()` copies 200 MB into RAM, and `pymupdf.open(stream=pdf_bytes)` holds another in-memory view simultaneously.
- **Evidence from Implementation:** `src/api/routes.py:165` has no `size` cap or chunked streaming loop; `deploy/Caddyfile.direct` and `deploy/Caddyfile.tunnel` do not configure `request_body { max_size ... }` either.
- **Why It Matters:** Any client can stream a 2–5 GB body to `POST /api/v1/books` and trigger an immediate OOM kill of the FastAPI server before `MAX_UPLOAD_MB` ever executes.
- **Actual or Potential Impact:** Trivial remote or local memory exhaustion / crash of the API server (especially severe on a Raspberry Pi with `MemoryMax=4500M`).
- **Recommended Solution:** Stream `file.read(1024 * 1024)` in 1 MiB chunks directly to a temporary file inside `workspace/tmp/`, updating an incremental `hashlib.sha256()` digest and aborting immediately with HTTP `413` (`FILE_TOO_LARGE`) as soon as cumulative bytes exceed `settings.max_upload_mb * 1024 * 1024` (unlinking the temp file in `finally`). Open the validated PDF from disk path in PyMuPDF (`pymupdf.open(tmp_path)`) rather than holding `pdf_bytes` in RAM. Also set `request_body { max_size 210MB }` in Caddy / `LimitRequestBody` in Apache.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

### SEC-03 — Docker Container Runs as `root` and Trusts Arbitrary `X-Forwarded-*` Headers
- **Category:** Security (Container & Network Hardening)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `deploy/Dockerfile`, `deploy/compose.lahari.yml`, `scripts/run_api.py`
- **Relevant Function / Component:** Docker build/runtime image, Uvicorn proxy header config
- **Line Numbers:** `deploy/Dockerfile:10–67`; `deploy/compose.lahari.yml:31–35`; `scripts/run_api.py:59–60`
- **Description:**
  1. `deploy/Dockerfile` defines no non-root `USER` directive. FastAPI, PyMuPDF (native C/MuPDF PDF parser), OpenCV, Tesseract, and PaddleOCR all execute as UID `0` (`root`) inside the container.
  2. Both `deploy/Dockerfile:23` and `deploy/compose.lahari.yml:35` hardcode `FORWARDED_ALLOW_IPS=*` alongside `PROXY_HEADERS=true`. Combined with `scripts/run_api.py:59–60`, Uvicorn unconditionally trusts `X-Forwarded-For`, `X-Forwarded-Proto`, and `X-Forwarded-Host` from *any* IP address.
- **Evidence from Implementation:** No `USER` instruction exists anywhere in `deploy/Dockerfile`; `ENV FORWARDED_ALLOW_IPS=*` is set at line `23` and repeated in `compose.lahari.yml:35`.
- **Why It Matters:** Running native C/C++ document parsers (MuPDF, OpenCV, Leptonica/Tesseract) as `root` enlarges the blast radius of any memory-corruption vulnerability in untrusted PDF/image parsing. Trusting wildcard `FORWARDED_ALLOW_IPS=*` enables IP/scheme spoofing (bypassing IP-based rate limits or forging audit logs) if the app port is reachable inside a shared host or container network.
- **Actual or Potential Impact:** Elevated privilege inside container on native parser compromise; spoofable client IP/protocol metadata behind misconfigured networks.
- **Recommended Solution:** Create a dedicated unprivileged user (`appuser`, UID 1000) in `deploy/Dockerfile`, chown `/app`, `/workspace`, and model caches, and drop privileges via `USER appuser` (aligning with `deploy/docker-entrypoint.sh`). Restrict `FORWARDED_ALLOW_IPS` to the reverse proxy's specific loopback/Docker subnet IP (e.g., `127.0.0.1` or Caddy's internal network CIDR) rather than `*`.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** Verify volume ownership on existing Docker deployments when switching from `root` to UID 1000.

---

### SEC-04 — Malformed/Adversarial PDF & Decompression Pixel-Bomb Exposure
- **Category:** Security (File Handling / Resource Exhaustion)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/book_service.py`, `src/services/ocr_service.py`, `src/pdf/rasterizer.py`
- **Relevant Function / Component:** `import_pdf_book`, `ensure_page_image_rendered`, `OCRJobExecutor._ensure_page_image_path`, `render_pdf_pages`
- **Line Numbers:** `src/services/book_service.py:73–77, 144–174`; `src/services/ocr_service.py:296–328`; `src/pdf/rasterizer.py:151–215`
- **Description:** Untrusted PDFs are opened in-process with PyMuPDF without checking individual page dimensions (`page.rect.width`, `page.rect.height`) before rendering at 300 DPI (or user-requested `render_dpi` up to `450` in `OCRRunCreateRequest`), and without any render timeout or explicit Pillow `Image.MAX_IMAGE_PIXELS` bound. A tiny (<50 KB) crafted PDF declaring a single page of `7200 × 7200 pt` (100 × 100 inches) renders at 300 DPI to a `30,000 × 30,000 px` RGB pixmap—allocating **~2.7 GB of uncompressed RAM** from a single `page.get_pixmap(dpi=300)` call. Additionally, `import_pdf_book` does not verify magic bytes (`%PDF-`) or reject encrypted/password-protected PDFs cleanly before walking all pages (encrypted PDFs fail only later or produce empty text).
- **Evidence from Implementation:** `book_service.py:76` (`page.get_pixmap(dpi=target_dpi, alpha=False)`) and `ocr_service.py:310` pass `dpi` directly without bounding output pixel area; `book_service.py:144–155` checks only `doc.page_count`, not `doc.is_encrypted` or page dimensions.
- **Why It Matters:** Crafted or scanned-poster PDFs can crash the server via single-page memory spikes even when file size (<200 MB) and page count (<1000) limits are respected.
- **Actual or Potential Impact:** OOM crash on a single adversarial or oversized-page PDF; confusing empty-page imports for encrypted PDFs.
- **Recommended Solution:** Reject `doc.is_encrypted` (with explicit 400 `ENCRYPTED_PDF_UNSUPPORTED` error) and check `%PDF-` header on upload. Before calling `get_pixmap`, compute `target_w = rect.width * dpi / 72` and `target_h = rect.height * dpi / 72`; clamp effective rendering scale if `target_w * target_h` exceeds a safe ceiling (e.g., `25_000_000` pixels ≈ 5000×5000 px) or reject absurdly oversized pages. Explicitly configure `Image.MAX_IMAGE_PIXELS` in Pillow usage.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

### SEC-05 — Hardcoded Default Weak DB Credentials, `--auth=trust` Local Postgres, and Cleartext HTTP LAN Preset
- **Category:** Security (Configuration & Transport)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/core/config.py`, `docker-compose.yml`, `scripts/manage_local_pg.py`, `mobile/lib/ui/features/studio/views/server_settings_sheet.dart`
- **Relevant Function / Component:** `AppSettings.from_env`, `docker-compose.yml` postgres service, `init_cluster`, `ServerSettingsSheet`
- **Line Numbers:** `src/core/config.py:49–50`; `docker-compose.yml:6–8`; `scripts/manage_local_pg.py:30, 55`; `mobile/lib/ui/features/studio/views/server_settings_sheet.dart:99–101`
- **Description:**
  1. `src/core/config.py:49–50` (`default_db` fallback for `DATABASE_URL`) and `docker-compose.yml:6–8` (`POSTGRES_USER` / `POSTGRES_PASSWORD`) embed a weak predictable default credential pair.
  2. `scripts/manage_local_pg.py:55` initializes the local PostgreSQL cluster with `--auth=trust` (allowing any local process/user to connect as superuser without a password).
  3. `mobile/lib/ui/features/studio/views/server_settings_sheet.dart:99–101` hardcodes a private LAN preset (`http://<lan-ip>:8085`) over unencrypted HTTP; if Basic Auth is configured, entering credentials against an `http://` URL transmits the Base64 password in cleartext over Wi-Fi without warning.
- **Evidence from Implementation:** Verified in `config.py:49–50`, `docker-compose.yml:6–8`, `manage_local_pg.py:55`, and `server_settings_sheet.dart:99–101`. (Note: `deploy/raspberry-pi/install.sh:46` properly generates a random 24-byte hex password via `openssl rand -hex 24` for Pi installs.)
- **Why It Matters:** Weak default credentials frequently survive into shared LAN or dev-turned-prod setups; cleartext HTTP transmission exposes Basic Auth credentials on shared Wi-Fi networks.
- **Actual or Potential Impact:** Unauthorized local DB access on multi-user workstations; credential interception if mobile users authenticate over cleartext `http://` LAN links.
- **Recommended Solution:** Switch `manage_local_pg.py` to `scram-sha-256` with an auto-generated local `.pgpass`/env password; require `POSTGRES_PASSWORD` via `.env` in `docker-compose.yml` (with `${POSTGRES_PASSWORD:?}` or dev override); remove hardcoded personal LAN IPs from mobile UI chips and warn/block sending Basic Auth credentials over non-loopback `http://` URLs.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

### SEC-06 — Unpinned External Model & Dictionary Downloads Without Checksum Verification + Conflicting OpenCV Packages
- **Category:** Security (Supply Chain & Dependencies)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `deploy/Dockerfile`, `deploy/raspberry-pi/install.sh`, `scripts/build_telugu_lexicon.py`, `scripts/build_telugu_dictionary_db.py`, `requirements-phase5.lock.txt`
- **Relevant Function / Component:** Asset download steps, `SOURCES`, `DICTIONARY_SOURCES`, Python lockfile
- **Line Numbers:** `deploy/Dockerfile:47–49`; `deploy/raspberry-pi/install.sh:57–60`; `scripts/build_telugu_lexicon.py:31–68`; `scripts/build_telugu_dictionary_db.py:29–48`; `requirements-phase5.lock.txt:46–47`
- **Description:**
  1. `Dockerfile` and `install.sh` fetch `tel.traineddata` from `tesseract-ocr/tessdata_best` `main` branch via `curl` without verifying its SHA-256 checksum (even though `artifacts/benchmark/demo-run/benchmark_report.md:12` records the exact expected SHA-256!).
  2. `scripts/build_telugu_lexicon.py` and `scripts/build_telugu_dictionary_db.py` download 6 external files from mutable `master`/`main` GitHub branches without commit-SHA pinning or checksum verification.
  3. `requirements-phase5.lock.txt:46–47` lists **both** `opencv-contrib-python==4.10.0.84` and `opencv-python-headless==5.1.0.95` simultaneously in the same environment—a known OpenCV packaging conflict where both packages overwrite the same `cv2` namespace in `site-packages`, leading to non-deterministic binaries and unnecessary GUI/contrib attack surface. PaddleX also pulls cloud-adjacent SDKs (`aistudio_sdk`, `bce-python-sdk`, `modelscope`, `huggingface_hub`) into the environment.
- **Evidence from Implementation:** Verified verbatim in `Dockerfile:47–49`, `install.sh:57–60`, `build_telugu_lexicon.py:31–68`, `build_telugu_dictionary_db.py:29–48`, and `requirements-phase5.lock.txt:46–47`.
- **Why It Matters:** Upstream branch changes or repository compromises could silently alter OCR models or inject malformed dictionary content during rebuilds; conflicting OpenCV wheels cause subtle ABI/runtime crashes.
- **Actual or Potential Impact:** Non-reproducible builds, potential supply-chain tampering of downloaded models/lexicons, and unpredictable `cv2` binary behavior.
- **Recommended Solution:** Pin GitHub asset URLs to immutable commit SHAs and verify expected SHA-256 checksums before placing files into `models/`. Resolve the dual OpenCV installation so only `opencv-python-headless` (matching PaddleOCR's constraint) is installed cleanly in a regenerated lockfile, and run `pip-audit` / `npm audit` in CI.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** Verify exact OpenCV version compatibility with `paddleocr==3.7.0` / `paddlex==3.7.2`.

---

### SEC-07 — Missing FastAPI Security Headers, Over-Permissive CORS Methods/Headers, Exposed OpenAPI Docs, and Path Leak in `/health`
- **Category:** Security (Application & HTTP Hardening)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/api/app.py`, `src/api/routes.py`
- **Relevant Function / Component:** `create_app`, `health_check`, `require_basic_auth`
- **Line Numbers:** `src/api/app.py:80–84, 150, 186–192, 196–210`; `src/api/routes.py:133–143`
- **Description:**
  1. HTTP security headers (`Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`) are defined only in `deploy/Caddyfile.*`, not in FastAPI middleware. Bare-metal Apache (`install.sh`) or local deployments lack these headers unless configured manually in Apache.
  2. `CORSMiddleware` (`app.py:186–192`) uses `allow_methods=["*"]` and `allow_headers=["*"]` rather than an explicit minimal allowlist.
  3. FastAPI exposes interactive Swagger UI (`/docs`), ReDoc (`/redoc`), and `/openapi.json` by default (`app.py:80–84`), advertising the full API schema on public deployments.
  4. `GET /api/v1/health` (`routes.py:133–143`), which explicitly bypasses `require_basic_auth` (`app.py:150`), returns `workspace_dir=str(settings.workspace_dir)`—leaking the absolute server filesystem path (and OS username on local/Pi installs) to unauthenticated callers.
- **Evidence from Implementation:** Verified directly in `app.py:80–84, 150, 186–192` and `routes.py:133–143`.
- **Why It Matters:** Defense-in-depth headers protect against XSS/clickjacking/MIME-sniffing regardless of reverse proxy; leaking absolute filesystem paths and full OpenAPI specs aids reconnaissance on public hosts.
- **Actual or Potential Impact:** Reduced browser-side hardening on Apache/local setups; unauthenticated filesystem path disclosure via `/api/v1/health`.
- **Recommended Solution:** Add lightweight FastAPI security-header middleware (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: no-referrer`, pragmatic CSP compatible with PDF.js worker); narrow `CORSMiddleware` to explicit methods (`GET, POST, PATCH, DELETE, OPTIONS`) and headers (`Authorization, Content-Type`); gate `/docs`, `/redoc`, `/openapi.json` behind `ENABLE_API_DOCS` (default `False` when `PROXY_HEADERS=true`); remove `workspace_dir` from public `/api/v1/health` (return `"workspace": "ready"` instead).
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** Verify mobile/frontend tests that assert `workspace_dir` on `/api/v1/health` (`mobile/test/widget_test.dart:62`, `tests/test_phase2_api_and_db.py`) are updated together.

---

### SEC-08 — Missing Input Size Bounds on API Schemas, Raw XML Interpolation Helper, and TOFU SSH Check in Backup Script
- **Category:** Security (Input Validation & Ops Hardening)
- **Severity:** Low
- **Confidence:** Confirmed
- **Exact File Path:** `src/api/schemas.py`, `src/services/export_service.py`, `scripts/backup_pi_to_mac.sh`
- **Relevant Function / Component:** `BlockEditRequest`, `PageAutocorrectRequest`, `PageBatchSaveRequest`, `ManualBlockCreateRequest`, `DigitalTextUpdateRequest`, `_append_field`, `backup_pi_to_mac.sh`
- **Line Numbers:** `src/api/schemas.py:254–363`; `src/services/export_service.py:94–103`; `scripts/backup_pi_to_mac.sh:21, 56`
- **Description:**
  1. Several write endpoints accept unbounded strings or lists: `BlockEditRequest.edited_text`, `ManualBlockCreateRequest.text`, `DigitalTextUpdateRequest.text`, `PageAutocorrectRequest.current_texts`, and `PageBatchSaveRequest.edits` have no `max_length` or `max_items` bounds (unlike `DictionaryTextCheckRequest.text`, which properly sets `max_length=25_000`, and `CustomDictionaryWordCreateRequest`, which bounds fields).
  2. `_append_field` (`export_service.py:94–103`) interpolates `instruction` directly into an XML string passed to `parse_xml(rf'<w:instrText ...> {instruction} </w:instrText>')`. Currently only invoked with hardcoded constants (`"PAGE"` and `'TOC \o "1-3" \h \z \u'`), so it is **not currently exploitable**, but fragile if reused with dynamic input.
  3. `scripts/backup_pi_to_mac.sh:21` sets `StrictHostKeyChecking=accept-new` (Trust-On-First-Use SSH) and curls unauthenticated `http://127.0.0.1:8085/api/v1/health` over SSH.
- **Evidence from Implementation:** Verified directly in `schemas.py:254–363`, `export_service.py:94–103`, and `backup_pi_to_mac.sh:21`.
- **Why It Matters:** Unbounded request bodies can cause huge DB writes or slow autocorrect runs; building XML elements via `OxmlElement` + `.text` prevents future XML injection bugs by construction.
- **Actual or Potential Impact:** Minor DoS amplification on write endpoints; negligible risk on `_append_field` today; minor LAN MITM window on first backup run with `accept-new`.
- **Recommended Solution:** Add pragmatic Pydantic `Field(max_length=...)` bounds (e.g., 50,000 chars for block/digital text, max 500 edits per batch page save); replace `parse_xml(rf'...')` in `_append_field` with `OxmlElement("w:instrText")` and `instr.text = f" {instruction} "`; pin the Raspberry Pi SSH host key in `~/.ssh/known_hosts` and use `StrictHostKeyChecking=yes` in `backup_pi_to_mac.sh`.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

## 8. Telugu OCR Quality Findings

### OCR-01 — Missing Geometric Reading-Order Sorting, Multi-Column Segmentation, Paragraph Reconstruction, and Header/Footer Filtering
- **Category:** Telugu OCR Quality (Layout & Document Structure)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/ocr/paddle_provider.py`, `src/ocr/tesseract_provider.py`, `src/services/export_service.py`
- **Relevant Function / Component:** `PaddleOCRProvider.recognize`, `parse_tesseract_tsv_lines`, `_build_docx_bytes`
- **Line Numbers:** `src/ocr/paddle_provider.py:225–242`; `src/ocr/tesseract_provider.py:71–90`; `src/services/export_service.py:397–417`
- **Description:**
  1. Both OCR providers assign `reading_order = block_index` directly from raw detector output (`paddle_provider.py:240`, `tesseract_provider.py:88`) with zero geometric Y/X sorting or two-column detection. On classical Telugu books with two-column layouts, verse + footnote commentary, or slightly tilted lines, PaddleOCR's DBNet box ordering can interleave columns or invert adjacent lines.
  2. There is no automatic detection or tagging of repeating running headers, footers, or page numbers (e.g., top/bottom margin bands with short digits or book title), forcing human reviewers to manually click "Ignore Box" on every single page of a 400-page book.
  3. Even in `editable_flow` DOCX mode (`export_service.py:397–417`), every single OCR `text_line` is emitted as a separate Word `<w:p>` paragraph with `space_after = Pt(6)` (`344`), rather than reconstructing logical paragraphs (detecting indentation, vertical line-spacing gaps, and Telugu end-of-line hyphenation `-`/`–`).
- **Evidence from Implementation:** `paddle_provider.py:240` sets `"reading_order": block_index`; `export_service.py:397–417` loops `for item in page.block_items:` and calls `doc.add_paragraph(...)` unconditionally for every single OCR line.
- **Why It Matters:** Telugu printed books frequently combine prose paragraphs, indented *padyam* (poetry stanzas), two-column commentaries, and running book-title headers/page numbers. Line-per-paragraph output makes the resulting DOCX hard to reflow or typeset without extensive manual joining in Word.
- **Actual or Potential Impact:** Scrambled reading order on two-column pages; tedious manual header/footer dismissal across hundreds of pages; fragmented line-by-line DOCX output in `editable_flow` mode.
- **Recommended Solution:**
  1. Add a deterministic layout post-processor (keeping raw engine output untouched!) that sorts polygons into reading order using vertical clustering + optional X-projection two-column split detection.
  2. Flag likely running headers/footers/page numbers (top/bottom ~8% margin band + repeating text across pages or numeric patterns including Telugu digits `౦-౯`) as suggested `ignore` candidates for one-click approval.
  3. In `editable_flow` DOCX export, add an opt-in paragraph-reflow pass (joining consecutive `paragraph` lines based on line-gap / right-margin heuristics while preserving explicit `verse`, `heading_1`, and `heading_2` breaks, and carefully handling Telugu word breaks without corrupting conjuncts).
- **Estimated Implementation Complexity:** Large
- **Dependencies / Prerequisites:** Benchmark evaluation across single-column, two-column, and verse Telugu pages (`TEST-01`).

---

### OCR-02 — Whitespace/Newline Destruction in Auto-Correct & Suggestions, ZWNJ/ZWJ Mismatch Bypassing Tesseract Fixes, and Substring Replacement Bug
- **Category:** Telugu OCR Quality (Unicode & Post-Processing)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/lexicon_service.py`, `src/services/correction_service.py`, `scripts/build_telugu_lexicon.py`, `scripts/build_telugu_dictionary_db.py`, `frontend/src/components/DictionaryPanel.tsx`
- **Relevant Function / Component:** `_TELUGU_WORD_RE`, `is_telugu_word`, `_autocorrect_single_block`, `find_block_suggestions_from_index`, `normalize_telugu_token`, `_clean_headword`, `handleApplySpellFix`
- **Line Numbers:** `src/services/lexicon_service.py:47, 194–195, 731–754`; `src/services/correction_service.py:403, 438`; `scripts/build_telugu_lexicon.py:81`; `scripts/build_telugu_dictionary_db.py:75`; `frontend/src/components/DictionaryPanel.tsx:203–205`
- **Description:** Three confirmed Telugu text-handling defects exist in the NLP and proofreading pipeline:
  1. **ZWNJ (`\u200c`) / ZWJ (`\u200d`) Blind Spot:** In `artifacts/benchmark/demo-run/benchmark_report.md:74–77`, Tesseract 5 (`tel`) frequently injects spurious `\u200c` inside Telugu consonant conjuncts (e.g., `పన్‌తక`, `వీద్‌యార్‌థులు`, `డీజిటకైజేషన్‌`). However, `_TELUGU_WORD_RE` (`lexicon_service.py:47`) is `^[\u0C01-\u0C63\u0C78-\u0C7F]+$`, which **excludes** `\u200c`, `\u200d`, and `\u0C00` (Combining Candrabindu Above). As a result, `is_telugu_word(core)` returns `False` for *every* Tesseract token containing a spurious `\u200c`, causing both Auto-Correct and Dictionary Spell-Check to completely skip those corrupted words! Conversely, `build_telugu_lexicon.py:81` and `build_telugu_dictionary_db.py:75` unconditionally strip `\u200c`/`\u200d` from dictionary headwords, erasing legitimate classical Telugu *nakāra-pollu* (`న్‍`) distinctions.
  2. **Whitespace & Newline Collapse:** `_autocorrect_single_block` (`lexicon_service.py:731, 754`) and `find_block_suggestions_from_index` (`correction_service.py:403, 438`) tokenize using `.split()` and reconstruct with `" ".join(...)`. Any multi-line block (such as a verse stanza or manually edited block containing `\n` or indentation) silently loses all internal line breaks when an auto-correct proposal or correction-memory suggestion is applied.
  3. **Substring Replacement Bug in Dictionary Spell-Check:** `DictionaryPanel.tsx:203–205` implements `handleApplySpellFix(token, replacement)` as `prev.replace(token, replacement)`. Because JavaScript `.replace()` replaces the *first substring occurrence* anywhere in the textarea, clicking a fix for a short misspelled word (e.g. `పన`) can corrupt an earlier valid longer word containing those characters (`పనిచేయడం` or `తపన`) instead of replacing the exact token at `issue.token_index`.
- **Evidence from Implementation:** Verified directly in all five files and corroborated by the real Tesseract output in `artifacts/benchmark/demo-run/benchmark_report.md:74–77`.
- **Why It Matters:** Directly undermines Telugu Unicode fidelity: valid line structure and classical *nakāra-pollu* can be silently altered, while Tesseract's #1 Telugu conjunct error evades auto-correction completely.
- **Actual or Potential Impact:** Missed fixes on Tesseract OCR runs; corrupted verse formatting upon accepting suggestions; accidental corruption of unrelated valid Telugu words in Dictionary Spell-Check.
- **Recommended Solution:**
  1. Tokenize using a regex splitter (`re.split(r"(\s+)", working_text)`) so whitespace, tabs, and newlines are preserved verbatim when rebuilding proposed block text.
  2. Explicitly handle `\u200c`/`\u200d` and `\u0C00` in `_TELUGU_WORD_RE` / `_autocorrect_single_block`: detect spurious mid-conjunct ZWNJ (`్\u200c` followed by a Telugu consonant) as a targeted high-confidence OCR repair candidate when removing it yields a known dictionary word, while preserving valid word-final *nakāra-pollu* (`న్\u200d`/`న్\u200c`) in classical profiles.
  3. Return character `(start_offset, end_offset)` spans in `DictionaryTextIssueItem` (or replace by token index via regex match offsets) in `DictionaryPanel.tsx` instead of `prev.replace(token, replacement)`.
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** Add unit tests covering `\u200c`/`\u200d`, `\u0C00`, multi-line blocks, and substring-prefix collisions (`TEST-04`).

---

### OCR-03 — DOCX Export Drops `verse` Role, Omits Run-Level Complex Script (`w:cs`) Font, Skips NFC Normalization, and Fails to Sanitize XML Control Characters
- **Category:** Telugu OCR Quality (Export Encoding & Typography)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/export_service.py`
- **Relevant Function / Component:** `_configure_telugu_font`, `_build_docx_bytes`, `_build_txt_bytes`
- **Line Numbers:** `74–92`, `397–422`, `478–510`
- **Description:**
  1. **`verse` Role Ignored:** Reviewers can tag blocks as `verse` (`ALLOWED_BLOCK_ROLES = {"paragraph", "heading_1", "heading_2", "verse", "ignore"}` in `review_service.py:42`), and `document_text_blocks.block_role` persists `"verse"`. However, `_build_docx_bytes` (`export_service.py:398–417`) only branches on `heading_1` and `heading_2`; `verse` falls through to ordinary `paragraph` formatting, losing stanza indentation/spacing and line-break semantics.
  2. **Missing Run-Level Complex Script (`w:cs`) Font:** While `_configure_telugu_font` (`74–92`) properly sets `w:ascii`, `w:hAnsi`, `w:cs`, and `w:eastAsia` on paragraph *styles*, `_build_docx_bytes` (`403, 409, 415`) explicitly executes `run.font.name = font_family` on every run. In `python-docx`, setting `run.font.name` writes only `w:ascii` and `w:hAnsi` to `<w:rPr><w:rFonts/>` and leaves `w:cs` unset—which in Microsoft Word and LibreOffice can cause Telugu (a Complex Script) to ignore the run font or fall back inconsistently.
  3. **No NFC Normalization or XML Control-Char Sanitization:** Exported text is passed directly into `p.add_run(item.text)` without `unicodedata.normalize("NFC", ...)` and without stripping XML 1.0 illegal control characters (`\x00–\x08`, `\x0b`, `\x0c`, `\x0e–\x1f`, which frequently appear in raw PyMuPDF `digital_text` layers from older PDFs). `lxml` raises `ValueError: All strings must be XML compatible` when encountering control characters, crashing the entire book export!
- **Evidence from Implementation:** Verified at `export_service.py:398–417` (only `heading_1` and `heading_2` branches; `run.font.name = font_family` without `w:cs`; no `normalize_nfc` or XML control-char filter in `_build_docx_bytes`).
- **Why It Matters:** Books with Telugu poetry (*padyalu*) lose their semantic markup in DOCX; dirty PDF digital text layers can make an entire book un-exportable; inconsistent Complex Script font tagging breaks Telugu glyph shaping across Word/macOS/Windows.
- **Actual or Potential Impact:** Crashed DOCX exports on PDFs containing control bytes; broken typography or fallback fonts for Telugu runs in Word/LibreOffice; lost `verse` formatting.
- **Recommended Solution:** Add a dedicated `TeluguVerse` Word style (indented, preserved line breaks, tighter intra-stanza spacing) and branch on `item.role == "verse"`; set `<w:rFonts w:cs=...>` and `<w:lang w:bidi="te-IN"/>` on both styles and runs (or inherit from style instead of setting incomplete `run.font.name`); apply NFC normalization (for `human_approved` or optionally configurable while keeping `raw_ocr` faithful) and strip XML-illegal control characters before `add_run()`.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

### OCR-04 — 7-Bit ASCII Legacy Telugu Font PDFs Bypass `has_legacy_font_encoding`
- **Category:** Telugu OCR Quality (PDF Classification)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/pdf/rasterizer.py`
- **Relevant Function / Component:** `has_legacy_font_encoding`, `classify_and_extract_pdf_page`
- **Line Numbers:** `18–68`
- **Description:** `has_legacy_font_encoding` detects legacy non-Unicode Telugu font encodings (such as Anu, Shreelipi, Priyankaa, Hemalatha) only if either `>= 10%` of characters fall in the Private Use Area (`U+E000–U+F8FF`) or `>= 25%` fall in Latin-1 Supplement (`U+00A1–U+00FF`) with zero Telugu Unicode characters. Many older Telugu DTP PDFs use custom-encoded fonts mapped heavily onto standard 7-bit ASCII (`A–Z`, `a–z`, punctuation like `~`, `@`, `#`, `^`, `{`, `}`, `\`) with `< 25%` Latin-1 high bytes. Those pages pass `has_legacy_font_encoding` as `False`, are classified as `digital_text`, skip OCR by default, and export garbled ASCII gibberish.
- **Evidence from Implementation:** `rasterizer.py:29–38` checks only `pua_count` and `latin_ext_count`, ignoring PDF embedded font names (`page.get_fonts()`) and abnormal ASCII symbol/punctuation ratios on Telugu-language books (`language_code="te"`).
- **Why It Matters:** Many historical Telugu books digitized in the 1990s–2010s were typeset in Anu/Shreelipi/Vemana/Priyankaa legacy fonts. Misclassifying them as `digital_text` silently bypasses OCR unless the user discovers and toggles "Include Digital Text Pages" manually.
- **Actual or Potential Impact:** Unreadable garbled Latin characters exported in DOCX/TXT for legacy-font Telugu PDFs.
- **Recommended Solution:** Inspect `page.get_fonts()` for known legacy Telugu font-name patterns (e.g., `Anu`, `Priyankaa`, `Hemalatha`, `Shree-Tel`, `Tikkana`, `TL-TT`, `Vani-Legacy`, custom `Identity-H` without valid `/ToUnicode` CMap) and check whether a `language_code="te"` book page has zero Unicode Telugu characters alongside high non-English symbol density (`~`, `|`, `^`, `\` inside words) or low English dictionary hit rate; flag such pages as `scanned_image` (or `legacy_encoded` routed to OCR).
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** Collect 2–3 sample legacy-font Telugu PDFs to validate detection thresholds without false-positiving on genuine English preface/copyright pages.

---

### OCR-05 — Fragile Full-Page `deskew`, Naive Comparator Index Fallback, and ARM64 Detection Downscaling Tradeoff
- **Category:** Telugu OCR Quality (Preprocessing, Alignment & Inference)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/ocr_service.py`, `src/services/review_service.py`, `src/ocr/paddle_provider.py`
- **Relevant Function / Component:** `OCRJobExecutor._apply_preprocessing_profile`, `_match_comparator_block`, `PaddleOCRProvider.__init__`
- **Line Numbers:** `src/services/ocr_service.py:366–383`; `src/services/review_service.py:79–108`; `src/ocr/paddle_provider.py:90–94`
- **Description:**
  1. **Fragile `deskew` (`ocr_service.py:366–383`):** Computes `cv2.minAreaRect` across *all* Otsu-thresholded foreground pixels of the entire page. Book-spine shadows, black scanner margins, decorative Telugu chapter borders, or punch holes heavily bias `minAreaRect`, rotating an already-straight page by up to ±15° and degrading OCR accuracy.
  2. **Naive Comparator Index Fallback (`review_service.py:106–107`):** When PaddleOCR and Tesseract produce different line counts (very common—PaddleOCR splits wide lines or misses page numbers differently than Tesseract), `_match_comparator_block` falls back to `comparator_blocks_with_bbox[fallback_idx]` whenever no box exceeds `0.25` vertical overlap. This compares two completely unrelated lines on the page and raises a false **"Engine Disagreement"** flag, polluting review triage.
  3. **ARM64 `text_det_limit_side_len=1280` Tradeoff (`paddle_provider.py:90–94`):** On Linux ARM64 (Raspberry Pi), PaddleOCR automatically caps the detector's max side length to `1280 px` (vs `1920 px` on macOS/x86_64) to avoid RAM spikes. On a dense 300-DPI Telugu book scan (`2500 × 3500 px`), downscaling by ~2.7× shrinks sub-baseline Telugu *vattu* (subscript conjuncts like `క్క`, `త్త`, `ష్ట`) and thin vowel signs (`ి`, `ు`, `ృ`) during text detection, risking cropped bottom diacritics in detected bounding boxes before recognition even runs.
- **Evidence from Implementation:** Verified verbatim in `ocr_service.py:366–383`, `review_service.py:79–108`, and `paddle_provider.py:90–94`.
- **Why It Matters:** Cropped bottom *vattu* boxes cannot be recovered by the recognizer; noisy disagreement flags waste reviewer attention; bad deskew actively damages clean pages.
- **Actual or Potential Impact:** Higher false-positive review flags, potential missed/clipped Telugu subscript conjuncts on Raspberry Pi ARM64 scans, and corrupted geometry when users enable `deskew` on bordered scans.
- **Recommended Solution:**
  - Replace full-page `minAreaRect` with text-line projection-profile variance maximization or Hough line angle median over filtered inner-margin connected components, clamping small angles (`< 0.3°` = no-op).
  - Remove the blind `fallback_idx` match in `_match_comparator_block` (return `None` when vertical IoU/overlap is below threshold, and join multiple horizontally split comparator boxes sharing the same line band!).
  - Benchmark `text_det_limit_side_len` (`1280` vs `1536` vs `1920`) and `text_det_unclip_ratio` (slightly wider vertical box padding for Telugu *vattu* descenders!) on real 300-DPI Telugu scans on Raspberry Pi to verify whether `1280` causes measurable CER degradation.
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** Real printed Telugu benchmark pages (`TEST-01`) to quantify impact before changing defaults.

---

### OCR-06 — Lexicon Candidate Truncation and Uncalibrated Hardcoded Confidence Thresholds
- **Category:** Telugu OCR Quality (Lexicon & Triage)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/lexicon_service.py`, `src/services/review_service.py`
- **Relevant Function / Component:** `TeluguLexicon._populate`, `_is_low_confidence`
- **Line Numbers:** `src/services/lexicon_service.py:324–340`; `src/services/review_service.py:71–76`
- **Description:**
  1. `TeluguLexicon._populate` (`lexicon_service.py:324–340`) caps each `skeleton_index` bucket at `10` words (`if len(bucket) < 10`) and only indexes the top `60,000` words (out of 186,086) in `delete1_index` (capped at `8` per key). Because `_SKELETON_MAP` aggressively merges many consonants (`స/న/త/ష/శ → న`, `క/ర/గ/ఖ/ఱ → ర`, `ధ/భ/ణ → ణ`), common skeleton buckets saturate quickly with high-frequency modern words, causing rare classical/literary (*granthika*) Telugu words from C.P. Brown / Janapada to be dropped from candidate generation.
  2. `_is_low_confidence` (`review_service.py:71–76`) hardcodes `< 75.0` for Tesseract and `< 0.85` for PaddleOCR with no calibration against real Telugu CER and no configurability via `AppSettings` or book quality profile.
- **Evidence from Implementation:** Verified at `lexicon_service.py:329–338` and `review_service.py:71–76`.
- **Why It Matters:** Classical Telugu books (the primary digitization use case) rely heavily on rarer vocabulary beyond the top 60k frequency-ranked words; poorly calibrated confidence thresholds either miss real OCR errors or over-flag clean lines.
- **Actual or Potential Impact:** Lower auto-correct recall on classical/literary vocabulary; sub-optimal review triage precision/recall.
- **Recommended Solution:** Raise or remove the aggressive `skeleton_index` bucket cap (or use a slightly less lossy secondary skeleton alongside the coarse one, and include book-local verified words with priority); allow calibrating confidence thresholds empirically from the real Telugu benchmark (`TEST-01`) and exposing them via `AppSettings`.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** Benchmark dataset (`TEST-01`) for empirical confidence threshold calibration.

---

## 9. Architecture and Maintainability Findings

### ARCH-01 — Broken `Save Digital Text` API Contract (Guaranteed HTTP 422) & Dropped Manual Block `bbox`
- **Category:** Architecture / Correctness (API Contract Drift)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `frontend/src/api/client.ts`, `frontend/src/types/api.ts`, `src/api/schemas.py`, `src/api/routes.py`
- **Relevant Function / Component:** `updatePageDigitalText`, `createManualPageBlock`, `DigitalTextUpdateRequest`, `patch_page_digital_text`, `ManualBlockCreateRequest`, `ManualBlockCreateResponse`
- **Line Numbers:** `frontend/src/api/client.ts:282–309`; `frontend/src/types/api.ts:206–213`; `src/api/schemas.py:345–363`; `src/api/routes.py:616–650`
- **Description:** Two verified frontend-to-backend contract mismatches exist:
  1. **Guaranteed Failure on `PATCH .../digital-text`:** `frontend/src/api/client.ts:307` sends `JSON.stringify({ digital_text_content: digitalTextContent })`, whereas backend `DigitalTextUpdateRequest` (`src/api/schemas.py:361–362`) requires `{ "text": str }`. Every attempt to save edited digital text from the web studio fails with HTTP `422 VALIDATION_ERROR`. Additionally, the frontend return type (`client.ts:303`) expects `review_status`, which `DigitalTextPageResponse` (`routes.py:635, 649`) does not include.
  2. **Silent Field Drop on `POST .../blocks`:** `frontend/src/api/client.ts:289` accepts and sends `bbox?: number[] | null`, and `ManualBlockCreateResult` (`types/api.ts:206–213`) expects `ocr_run_id`. Backend `ManualBlockCreateRequest` (`schemas.py:345–348`) has no `bbox` field (silently discarded by Pydantic) and `ManualBlockCreateResponse` (`schemas.py:351–358`) omits `ocr_run_id`.
- **Evidence from Implementation:** Direct side-by-side verification of `client.ts:282–309` against `schemas.py:345–363` and `routes.py:616–650`.
- **Why It Matters:** Born-digital PDF text editing is completely non-functional in the shipped web UI, and manually inserted blocks cannot preserve user-supplied bounding boxes.
- **Actual or Potential Impact:** Confirmed runtime failure (HTTP 422) whenever a user clicks "Save Digital Text"; silent data loss of `bbox` if passed to manual block creation.
- **Recommended Solution:** Fix `updatePageDigitalText` in `client.ts` to send `{ text: digitalTextContent }` (or accept an alias on `DigitalTextUpdateRequest` for backwards compatibility), align the return schema, add optional validated `bbox` support to `ManualBlockCreateRequest` (converting to 4-point polygon in `insert_manual_review_block`), and generate TypeScript types from OpenAPI (`openapi-typescript`) in CI to prevent future drift.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** Add an integration test exercising `PATCH .../digital-text` (`TEST-02`).

---

### ARCH-02 — Incomplete Book Deletion Leaks `training_crops/` and Fails to Cancel Active OCR Jobs
- **Category:** Architecture / Reliability (Lifecycle & Data Hygiene)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/book_service.py`, `src/api/routes.py`
- **Relevant Function / Component:** `delete_book_and_artifacts`, `delete_book`
- **Line Numbers:** `src/services/book_service.py:307–325`; `src/api/routes.py:202–209`
- **Description:** When a user deletes a book (`DELETE /api/v1/books/{book_id}`):
  1. `delete_book_and_artifacts` (`book_service.py:321–324`) deletes `originals/{book_id}`, `pages/{book_id}`, `ocr/{book_id}`, and `exports/{book_id}`, but **forgets** `training_crops/{book_id}` (created by `_maybe_record_training_sample` in `review_service.py:445`).
  2. Neither `routes.py:202–209` nor `book_service.py:307–325` notifies `OCRJobExecutor` to cancel queued/running OCR runs for `book_id` before executing `db.delete(book)`. If an OCR worker is mid-page when the book is deleted, it continues processing and then hits foreign-key/missing-row errors or recreates orphaned PNG/JSON files under `workspace/pages/{book_id}` and `workspace/ocr/{book_id}` *after* deletion.
- **Evidence from Implementation:** `delete_book` (`routes.py:202–209`) does not even inject `executor: OCRJobExecutor`; `book_service.py:321–324` omits `storage.delete_prefix(f"training_crops/{book_id}")`.
- **Why It Matters:** Violates user expectations on deletion (both storage cleanup and privacy when removing a copyrighted/sensitive book with training crops) and creates race conditions with the background worker.
- **Actual or Potential Impact:** Orphaned cropped page images persisting indefinitely on disk; worker exceptions and ghost directories recreated after book deletion.
- **Recommended Solution:** Inject `executor` into `delete_book`, look up all `queued`/`running` `OCRRun` IDs for `book_id`, signal cancellation (and wait briefly or reject with `409 BOOK_OCR_IN_PROGRESS` unless `force=true`), delete `training_crops/{book_id}` alongside the other 4 prefixes, and verify in `execute_run` that the `Book` still exists before writing page artifacts.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

### ARCH-03 — Fresh Docker and Raspberry Pi Install Pipelines Omit Telugu Lexicon and Dictionary Artifacts
- **Category:** Architecture / Deployment Completeness
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `deploy/Dockerfile`, `deploy/raspberry-pi/install.sh`, `.gitignore`
- **Relevant Function / Component:** Docker build stages, bare-metal Pi installer
- **Line Numbers:** `deploy/Dockerfile:46–61`; `deploy/raspberry-pi/install.sh:55–76`
- **Description:** Both `models/lexicon/telugu_lexicon.tsv.gz` (903 KB) and `models/lexicon/telugu_dictionary.sqlite` (167 MB) are git-ignored build artifacts (created locally by `scripts/build_telugu_lexicon.py` and `scripts/build_telugu_dictionary_db.py`), and `deploy/raspberry-pi/remote-deploy.sh` explicitly syncs `models/lexicon/` only from a developer laptop that happens to have built them. Neither `deploy/Dockerfile` nor `deploy/raspberry-pi/install.sh` builds or bundles these files (they only download `tel.traineddata`).
- **Evidence from Implementation:** `Dockerfile:46–49` only downloads `tel.traineddata`; `install.sh:57–60` only downloads `tel.traineddata`; neither invokes `build_telugu_lexicon.py` or `build_telugu_dictionary_db.py`.
- **Why It Matters:** Anyone provisioning a new Raspberry Pi or Docker container from the repository starts with an empty Telugu lexicon (`0` words) and `dictionary_db_available: false`, silently breaking both Auto-Correct dictionary suggestions and the standalone Telugu Dictionary tab.
- **Actual or Potential Impact:** Broken out-of-the-box experience on Docker and fresh Raspberry Pi deployments; brittle manual dependency on one developer machine's local `models/lexicon/` directory.
- **Recommended Solution:** Add an explicit build step (or optional build-arg/volume bootstrap script) in `deploy/Dockerfile` and `deploy/raspberry-pi/install.sh` to run `scripts/build_telugu_lexicon.py` and `scripts/build_telugu_dictionary_db.py` (with checksum-verified sources per `SEC-06`), or publish versioned release artifacts with SHA-256 verification.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** Pinned/verified asset URLs (`SEC-06`).

---

### ARCH-04 — Monolithic Frontend Components and Flutter Mobile Client Feature Drift
- **Category:** Architecture & Maintainability
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `frontend/src/App.tsx`, `frontend/src/components/ReviewEditorPanel.tsx`, `mobile/lib/data/services/digitizer_api_service.dart`
- **Relevant Function / Component:** `App`, `ReviewEditorPanel`, `DigitizerApiService`
- **Line Numbers:** `frontend/src/App.tsx:1–1489`; `frontend/src/components/ReviewEditorPanel.tsx:1–1254`; `mobile/lib/data/services/digitizer_api_service.dart`
- **Description:**
  1. `App.tsx` (1,489 lines) combines library management, OCR polling, review state orchestration, keyboard focus routing, block sync, upload/delete modal workflows, quick dictionary lookup, and 4 studio views into a single React component with dozens of interdependent `useState`/`useEffect` hooks. `ReviewEditorPanel.tsx` (1,254 lines) similarly bundles per-block editing, autocorrect diff previews, batch save, digital-text editing, manual block insertion, and suggestion cards.
  2. The Flutter mobile companion (`mobile/lib/data/services/digitizer_api_service.dart`) lacks support for newer backend workflows: `/autocorrect`, `/batch-save`, `/dictionary/*`, `/blocks` manual insert, and `/digital-text` editing.
- **Evidence from Implementation:** Verified via `wc -l` (`App.tsx`: 1,489; `ReviewEditorPanel.tsx`: 1,254) and inspection of `digitizer_api_service.dart` / `studio_view_model.dart`.
- **Why It Matters:** High state coupling in `App.tsx` makes adding features or fixing subtle re-render/polling bugs error-prone; mobile client drift risks breaking mobile users if API schemas evolve.
- **Actual or Potential Impact:** Slower development velocity, higher regression risk on UI changes, and incomplete mobile workflows.
- **Recommended Solution:** Incrementally extract focused custom hooks from `App.tsx` (`useBookLibrary`, `useOcrPolling`, `usePageReview`, `useTeluguKeyboardTarget`) and split `ReviewEditorPanel.tsx` into `BlockReviewCard`, `AutocorrectToolbar`, and `DigitalTextEditor` without a full rewrite. Clearly document the mobile client's supported scope (or incrementally add `batch-save` and `dictionary` endpoints).
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** Keep existing Vitest suites green across refactoring steps.

---

### ARCH-05 — Silent Exception Swallowing, Lazy `os.environ` Mutation, and Fragmented Dependency Manifests
- **Category:** Architecture & Maintainability
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `src/services/review_service.py`, `src/ocr/paddle_provider.py`, `pyproject.toml`, `deploy/requirements.runtime.txt`
- **Relevant Function / Component:** `_maybe_record_training_sample`, `PaddleOCRProvider.ensure_loaded`, dependency manifests
- **Line Numbers:** `src/services/review_service.py:470–472`; `src/ocr/paddle_provider.py:120–124`; `pyproject.toml:1–15`; `deploy/requirements.runtime.txt:1–25`
- **Description:**
  1. `_maybe_record_training_sample` (`review_service.py:470–472`) catches `except Exception: pass` with zero logging—silently hiding Pillow decoding errors, missing page images, permission problems, or DB constraint failures when capturing consented training crops.
  2. `PaddleOCRProvider.ensure_loaded` (`paddle_provider.py:120–124`) mutates process-global `os.environ` lazily inside a worker thread (`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK`, `PADDLE_PDX_CPU_NUM_THREADS`), which is not thread-safe and depends on import/call timing before PaddleX initializes.
  3. `pyproject.toml` declares zero `dependencies`, while runtime requirements are scattered across 4 separate files (`requirements-phase1.lock.txt`, `requirements-phase2.lock.txt`, `requirements-phase5.lock.txt`, `deploy/requirements.runtime.txt`). Furthermore, `src/evaluation/metrics.py` directly imports `rapidfuzz`, which is not explicitly declared in `deploy/requirements.runtime.txt` (relying solely on a transitive dependency of `jiwer==4.0.0`).
- **Evidence from Implementation:** Verified directly in all four files (`except Exception:` + `pass` at `review_service.py:470–472`; `os.environ[...]` at `paddle_provider.py:121, 123`; `pyproject.toml` has no `dependencies` table; `grep` of `src/` imports vs `deploy/requirements.runtime.txt`).
- **Why It Matters:** Silent failures make training-data collection bugs invisible; transitive dependency reliance breaks unexpectedly when upgrading `jiwer`; lazy `os.environ` mutation can fail silently if PaddleX reads env vars at module import time.
- **Actual or Potential Impact:** Missing training samples with no error trace; brittle environment builds across macOS and Linux ARM64.
- **Recommended Solution:** Log exceptions at `WARNING` level with structured context (`book_id`, `block_id`, `error_type`) in `_maybe_record_training_sample`; set Paddle env defaults once during app/CLI bootstrap before importing `paddleocr`; declare direct runtime dependencies cleanly in `pyproject.toml` (including `rapidfuzz`) and generate platform lockfiles from it.
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

### ARCH-06 — Stale `README.md` Scope Notice, Private LAN Host Disclosure, and Missing Request Correlation / Metrics
- **Category:** Maintainability & Observability
- **Severity:** Low
- **Confidence:** Confirmed
- **Exact File Path:** `README.md`, `src/common/logging_utils.py`, `src/api/app.py`
- **Relevant Function / Component:** `README.md`, `configure_logging`, FastAPI middleware
- **Line Numbers:** `README.md:5, 214`; `src/common/logging_utils.py`; `src/api/app.py:35`
- **Description:**
  1. `README.md:5` still displays a prominent banner stating *"This repository currently implements Phase 1 only... No web UI, FastAPI backend, database, LLM post-correction, or DOCX exporter is included"*, contradicting sections 4–8 immediately below it.
  2. `README.md:214` (and `scripts/backup_pi_to_mac.sh`, `deploy/raspberry-pi/remote-deploy.sh`, `server_settings_sheet.dart`) embeds a personal local LAN IP and SSH username directly in version-controlled documentation/code.
  3. While `src/common/logging_utils.py` outputs structured JSON logs (good), there is no HTTP request-ID middleware, request-latency logging, or operational metrics endpoint/counters (e.g., pages/min, OCR failure rate, cache hit rate).
- **Evidence from Implementation:** Verified at `README.md:5, 214` and `src/api/app.py:35`.
- **Why It Matters:** Confuses new contributors/operators; lacks basic per-request tracing when diagnosing 502/timeout issues behind Apache/Caddy.
- **Actual or Potential Impact:** Minor operational friction during debugging and onboarding.
- **Recommended Solution:** Update `README.md` to reflect the actual Phase 5 + Dictionary architecture and replace personal host/user literals with generic placeholders (`<pi-user>@<pi-lan-ip>`); add lightweight FastAPI request-ID + duration logging middleware (excluding auth headers/bodies).
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

## 10. Testing and Reliability Gaps

### TEST-01 — No Real Multi-Book Printed Telugu Ground-Truth Benchmark; Missing p95 Latency & Peak RAM Metrics
- **Category:** Testing & Reliability (OCR Benchmarking)
- **Severity:** High
- **Confidence:** Confirmed
- **Exact File Path:** `artifacts/benchmark/demo-run/benchmark_report.md`, `tests/fixtures/`, `src/evaluation/metrics.py`, `scripts/benchmark.py`
- **Relevant Function / Component:** `aggregate_metrics`, `benchmark.py`, fixture corpus
- **Line Numbers:** `artifacts/benchmark/demo-run/benchmark_report.md:23–26, 86`; `src/evaluation/metrics.py`; `scripts/benchmark.py`
- **Description:** Although `scripts/benchmark.py` and `src/evaluation/` implement a strong benchmarking harness (Raw CER, NFC CER, WER, Grapheme ER, exact-line accuracy, provenance tracking), the repository contains **zero real printed Telugu book ground-truth pages**. The only scored benchmark artifacts (`artifacts/benchmark/demo-run/` and `slice_test/`) evaluate a single synthetic 3-line Pillow-rendered page (`tests/fixtures/sample_scanned_telugu.pdf`). Even the generated report (`benchmark_report.md:86`) explicitly warns: *"1 gold-annotated page(s) scored in this run. Do not finalize production engine selection or Phase 2 acceptance thresholds until 20–30 real printed pages across at least three Telugu books... are evaluated."* Additionally, `aggregate_metrics` computes only mean/median latency—omitting **p95 latency**, **peak RSS RAM**, and **cold model-load time** in the summary table.
- **Evidence from Implementation:** `find tests/fixtures data/gold` shows only `sample_scanned_telugu_p1.gold.txt` (1 synthetic page); `benchmark_report.md:23–26` confirms `1 / 1` scored page.
- **Why It Matters:** Engine configuration choices (PaddleOCR `server_det` vs `mobile_det`, ARM64 `text_det_limit_side_len=1280`, preprocessing profiles, auto-correct confidence threshold `0.78`, and low-confidence thresholds) are currently unvalidated against real printed Telugu book typography, aging paper, bleed-through, and classical conjuncts.
- **Actual or Potential Impact:** Unmeasured OCR regressions when changing preprocessing, model versions, or Telugu post-processing rules.
- **Recommended Solution:** Execute the Performance Benchmarking Plan in Section 12 using 25–30 verified real printed Telugu book pages across ≥3 books and extend `src/evaluation/metrics.py` + `scripts/benchmark.py` to record `avg_sec_per_page`, `p95_sec_per_page`, `peak_rss_mb`, and `model_load_ms` per engine.
- **Estimated Implementation Complexity:** Medium (code changes Small; gold annotation effort Medium)
- **Dependencies / Prerequisites:** Rights-cleared / user-owned representative Telugu book scans and human-verified UTF-8 NFC gold transcripts.

---

### TEST-02 — Missing API Contract Verification & Digital-Text Endpoint Tests
- **Category:** Testing & Reliability (Integration)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `tests/test_phase3_review_api.py`, `frontend/src/`
- **Relevant Function / Component:** Review API tests, frontend API client tests
- **Line Numbers:** `tests/test_phase3_review_api.py` (entire file); `frontend/src/api/client.ts:282–309`
- **Description:** Frontend unit tests mock `api/client.ts` functions rather than testing `client.ts` request payloads against FastAPI's OpenAPI schema, and `tests/test_phase3_review_api.py` does not test `PATCH /api/v1/books/{id}/pages/{n}/digital-text` or manual block creation with `bbox`. That exact coverage gap allowed `ARCH-01` (guaranteed HTTP 422 on Save Digital Text) to go undetected.
- **Evidence from Implementation:** Confirmed by absence of `digital-text` `PATCH` assertions in `tests/test_phase3_review_api.py` and mocked client calls in `frontend/src/components/*.test.tsx`.
- **Why It Matters:** Backend Pydantic schema renames or frontend payload typos break live workflows silently despite green unit tests on both sides.
- **Actual or Potential Impact:** Broken production features (`ARCH-01`) slipping past both `pytest` and `vitest`.
- **Recommended Solution:** Add backend integration tests for `PATCH .../digital-text` and `POST .../blocks` (including `bbox`), and add a contract test exporting FastAPI's `/openapi.json` to validate `frontend/src/api/client.ts` request/response shapes (via `openapi-typescript` + `tsc --noEmit`).
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** Fix `ARCH-01`.

---

### TEST-03 — Missing Security, Streaming-Limit, Adversarial-PDF, and Concurrency Regression Tests
- **Category:** Testing & Reliability (Security & Resilience)
- **Severity:** Medium
- **Confidence:** Confirmed
- **Exact File Path:** `tests/test_deployment_and_security.py`, `tests/test_phase2_api_and_db.py`
- **Relevant Function / Component:** Deployment/security and OCR job lifecycle tests
- **Line Numbers:** `tests/test_deployment_and_security.py` (entire file); `tests/test_phase2_api_and_db.py` (entire file)
- **Description:** Existing security tests verify basic CORS, Basic Auth happy/fail paths, and relative subpath assets, but lack tests for:
  - Streaming upload rejection (`413`) without full buffering,
  - Encrypted PDFs, corrupted/truncated PDFs, and oversized-dimension pixel-bomb PDFs,
  - Duplicate concurrent `POST /ocr-runs` and `/resume` calls on an already-running job,
  - Deleting a book while an OCR job is active and confirming `training_crops/{book_id}` is removed,
  - OCR subprocess timeout enforcement.
- **Evidence from Implementation:** Inspected `tests/test_deployment_and_security.py` and `tests/test_phase2_api_and_db.py`.
- **Why It Matters:** Concurrency and malformed-input bugs are the primary causes of production crashes and data leaks in background document-processing apps.
- **Actual or Potential Impact:** Regressions in upload safety, job idempotency, and deletion cleanup go undetected.
- **Recommended Solution:** Implement the regression suites detailed in Section 14 alongside the corresponding P0/P1 fixes.
- **Estimated Implementation Complexity:** Medium
- **Dependencies / Prerequisites:** Corresponding fixes in `SEC-02`, `SEC-04`, `ARCH-02`, `PERF-04`, `PERF-06`.

---

### TEST-04 — Duplicated PostgreSQL Test Fixtures & Missing Telugu Unicode / DOCX Edge-Case Tests
- **Category:** Testing & Reliability (Maintainability & Script Coverage)
- **Severity:** Low
- **Confidence:** Confirmed
- **Exact File Path:** `tests/test_phase2_api_and_db.py`, `tests/test_phase3_review_api.py`, `tests/test_phase4_correction_memory.py`, `tests/test_phase5_export.py`, `tests/test_deployment_and_security.py`, `tests/test_dictionary_api.py`
- **Relevant Function / Component:** Per-file `reset_schema` / client setup fixtures; export & NLP tests
- **Line Numbers:** Repeated across all 6 PostgreSQL test modules
- **Description:** Six test files independently copy-paste PostgreSQL engine creation, `Base.metadata.drop_all/create_all`, and FastAPI `TestClient` bootstrap code instead of sharing a central `tests/conftest.py`. Furthermore, existing export and lexicon tests do not cover key Telugu edge cases: multi-line blocks with `\n`, ZWNJ (`\u200c`) / ZWJ (`\u200d`) handling, Combining Candrabindu (`\u0C00`), `verse` role DOCX export, XML control characters in `digital_text_content`, or `<w:rFonts w:cs=...>` verification in exported DOCX XML.
- **Evidence from Implementation:** Verified across all 6 test files and `tests/test_phase5_export.py` / `tests/test_lexicon_and_autocorrect.py`.
- **Why It Matters:** Schema or app-factory changes require editing 6 test files in lockstep; subtle Telugu Unicode/DOCX regressions remain unguarded.
- **Actual or Potential Impact:** Higher test maintenance cost and unguarded Telugu edge cases.
- **Recommended Solution:** Consolidate shared PostgreSQL/TestClient fixtures into `tests/conftest.py` and add targeted Telugu Unicode + DOCX XML assertions (`Section 14`).
- **Estimated Implementation Complexity:** Small
- **Dependencies / Prerequisites:** None.

---

## 11. Recommended Remediation Roadmap

Every finding from Section 5 is mapped below. Efforts use relative engineering complexity (`Small`, `Medium`, `Large`) rather than fabricated calendar dates.

### P0 — Immediate (Critical Security, Data Integrity & Reliability)

#### P0-1: Enforce Authentication & Access Tiering for Network-Exposed Deployments
- **Finding IDs Addressed:** `SEC-01`
- **Recommended Implementation:** Partition routes into optional public read-only Dictionary endpoints (rate-limited) vs authenticated Book Studio/write/delete endpoints, or enforce authentication globally on non-localhost deployments. Update `deploy/raspberry-pi/install.sh` and `deploy/.env.lahari.example` to require credentials (or Cloudflare Access / Apache auth) by default, and add a fail-closed startup check when `PROXY_HEADERS=true` without auth.
- **Files / Components Likely to Change:** `src/api/app.py`, `src/core/config.py`, `deploy/raspberry-pi/install.sh`, `deploy/.env.lahari.example`, `deploy/Caddyfile.direct`, `deploy/Caddyfile.tunnel`.
- **Required Tests:** Verify unauthenticated `DELETE /books/{id}`, `POST /books`, `POST /edits`, `DELETE /dictionary/custom/{id}` return `401`; verify fail-closed config validation; verify dictionary read access policy matches chosen tier.
- **Expected Benefit:** Eliminates anonymous data destruction, transcript vandalism, and compute/disk DoS on `https://lahari.org/telugu/`.
- **Risks of the Fix:** Existing bookmarked clients/mobile apps must supply credentials or log in once enabled; communicate rollout clearly.
- **Dependencies:** Product decision on whether standalone Dictionary tab remains public while Book Studio requires login.
- **Estimated Effort:** Medium

#### P0-2: Stream PDF Uploads to Disk with Incremental Size Limit & SHA-256 Hashing
- **Finding IDs Addressed:** `SEC-02`
- **Recommended Implementation:** Replace `await file.read()` in `upload_book` with a 1 MiB chunked async reader streaming into a temp file under `workspace/tmp/`, computing SHA-256 incrementally and raising HTTP `413` (`FILE_TOO_LARGE`) immediately when bytes exceed `MAX_UPLOAD_MB`. Pass the temp path into `import_pdf_book` instead of raw `bytes`. Add reverse-proxy `max_size` limits in Caddy/Apache configs.
- **Files / Components Likely to Change:** `src/api/routes.py`, `src/services/book_service.py`, `deploy/Caddyfile.direct`, `deploy/Caddyfile.tunnel`.
- **Required Tests:** Streaming upload test exceeding `MAX_UPLOAD_MB` verifying immediate `413` and zero orphaned temp files; regression test for valid upload & SHA-256 deduplication.
- **Expected Benefit:** Prevents trivial OOM DoS on upload and cuts legitimate 200 MB upload peak RAM by ~400 MB.
- **Risks of the Fix:** Temp-file cleanup on aborted client connections must be guaranteed via `try/finally`.
- **Dependencies:** None.
- **Estimated Effort:** Small

#### P0-3: Fix `Save Digital Text` HTTP 422 Contract Bug & Manual Block `bbox` Support
- **Finding IDs Addressed:** `ARCH-01`
- **Recommended Implementation:** Change `updatePageDigitalText` payload in `frontend/src/api/client.ts` to `{ text: digitalTextContent }` (and optionally accept `digital_text_content` alias in `DigitalTextUpdateRequest` during transition); align response schema (`review_status`); add optional validated `bbox` (`[x1, y1, x2, y2]`) to `ManualBlockCreateRequest` and return `ocr_run_id` in `ManualBlockCreateResponse`.
- **Files / Components Likely to Change:** `frontend/src/api/client.ts`, `frontend/src/types/api.ts`, `src/api/schemas.py`, `src/api/routes.py`, `src/services/review_service.py`.
- **Required Tests:** End-to-end API tests for `PATCH .../digital-text` and `POST .../blocks` with `bbox`; frontend unit test asserting exact JSON body keys.
- **Expected Benefit:** Restores completely broken digital-text editing in the web studio and fixes manual block coordinate loss.
- **Risks of the Fix:** Minimal; keep backwards compatibility if older clients exist.
- **Dependencies:** None.
- **Estimated Effort:** Small

#### P0-4: Safe Book Deletion (Cancel Active OCR Jobs + Clean `training_crops/`)
- **Finding IDs Addressed:** `ARCH-02`
- **Recommended Implementation:** Inject `OCRJobExecutor` into `DELETE /api/v1/books/{id}`, cancel any `queued`/`running` OCR runs for that book (and wait briefly for worker exit or return `409` if actively locked), add `storage.delete_prefix(f"training_crops/{book_id}")`, and guard worker writes against deleted books.
- **Files / Components Likely to Change:** `src/api/routes.py`, `src/services/book_service.py`, `src/services/ocr_service.py`.
- **Required Tests:** Delete book with training crops → verify `workspace/training_crops/{book_id}` is removed; delete book during mocked active OCR run → verify worker stops cleanly with zero orphaned files.
- **Expected Benefit:** Prevents storage leaks, privacy violations on deleted consented books, and post-delete worker crashes.
- **Risks of the Fix:** Slight delay (<1s) on delete if waiting for an active page cancellation check.
- **Dependencies:** None.
- **Estimated Effort:** Small

#### P0-5: Add Per-Page OCR Inference Timeouts & Process Isolation Strategy
- **Finding IDs Addressed:** `PERF-04`
- **Recommended Implementation:** Immediately add `OCR_PAGE_TIMEOUT_SEC` (default `180s`) to `TesseractOCRProvider` (`subprocess.run(..., timeout=...)`). Next, extract `OCRJobExecutor` execution into an isolated worker process (either a managed `multiprocessing` worker with hard kill on timeout or a standalone `telugu-digitizer-worker` systemd/compose process polling PostgreSQL) so hung or crashing PaddleOCR C++ calls cannot wedge or crash the FastAPI studio.
- **Files / Components Likely to Change:** `src/ocr/tesseract_provider.py`, `src/services/ocr_service.py`, `src/core/config.py`, `scripts/run_worker.py` (new), `deploy/raspberry-pi/telugu-digitizer.service`, `deploy/compose.lahari.yml`.
- **Required Tests:** Simulated hung Tesseract subprocess verifying timeout marks page failed and continues next page; simulated worker crash verifying API stays responsive and run recovers as `partial`.
- **Expected Benefit:** Eliminates single-page permanent queue freezes and protects web UI / dictionary uptime from native ML crashes.
- **Risks of the Fix:** Slightly higher baseline memory for a second Python process (~60–80 MB) — offset by removing PaddleOCR from the web API process entirely!
- **Dependencies:** Deploy config updates for systemd & Docker Compose.
- **Estimated Effort:** Small (Tesseract timeout); Large (full separate worker process)

---

### P1 — High Priority (Major Performance, OCR Correctness, Container Security & Benchmarking)

#### P1-1: Harden Docker Container (Non-Root User) & Proxy Header Trust + PDF Pixel-Bomb Guards
- **Finding IDs Addressed:** `SEC-03`, `SEC-04`
- **Recommended Implementation:** Add non-root `USER` in `deploy/Dockerfile`, narrow `FORWARDED_ALLOW_IPS` away from `*`, reject encrypted PDFs (`doc.is_encrypted`), check `%PDF-` header, and enforce a maximum rendered pixel area cap (`MAX_RENDER_PIXELS`, e.g., 25M px) in `book_service.py`, `ocr_service.py`, and `rasterizer.py` before `page.get_pixmap(...)`.
- **Files / Components Likely to Change:** `deploy/Dockerfile`, `deploy/compose.lahari.yml`, `deploy/docker-entrypoint.sh`, `src/services/book_service.py`, `src/services/ocr_service.py`, `src/pdf/rasterizer.py`, `src/core/config.py`.
- **Required Tests:** Adversarial oversized-rect PDF test (verifying clamped/rejected render without OOM); encrypted PDF test (`400`); Docker container `id -u != 0` verification.
- **Expected Benefit:** Contains native parser blast radius and prevents single-page PDF memory bombs.
- **Risks of the Fix:** Existing Docker volumes owned by `root` need a one-time `chown` during upgrade.
- **Dependencies:** None.
- **Estimated Effort:** Small

#### P1-2: Cache `SentenceContextModel` & Eliminate Hot-Path Full-Table / N+1 Queries
- **Finding IDs Addressed:** `PERF-01`, `PERF-02`
- **Recommended Implementation:** Cache the cross-book `SentenceContextModel` in memory with write-driven invalidation (or version counter) plus lightweight per-book overlay. Push `scope`/`book_id` filtering into SQL in `get_page_review_payload`; bulk-load blocks/edits in `batch_save_and_approve_page` and remove its redundant `get_page_review_payload()` call; paginate `GET /api/v1/corrections`; move `CustomDictionaryWord` search filtering into SQL (or cached index); preload completed page IDs in 1 query at the start of `OCRJobExecutor.execute_run`.
- **Files / Components Likely to Change:** `src/services/lexicon_service.py`, `src/services/review_service.py`, `src/services/dictionary_service.py`, `src/services/correction_service.py`, `src/services/ocr_service.py`, `src/api/routes.py`, `frontend/src/components/CorrectionMemoryPanel.tsx`.
- **Required Tests:** SQL query-count regression tests (using SQLAlchemy `before_cursor_execute` listener) verifying O(1) queries on `batch-save` and `execute_run` resume; cache invalidation test verifying new corrections/custom words appear immediately in `/autocorrect`.
- **Expected Benefit:** 5–20× faster `/autocorrect`, page review turns, batch saves, and OCR resume on multi-book databases.
- **Risks of the Fix:** Stale cache if any write path forgets to bump the invalidation epoch — centralize invalidation helper.
- **Dependencies:** Coordinate pagination UI update on Correction Memory panel.
- **Estimated Effort:** Medium

#### P1-3: Optimize Export Queries & Eliminate Double-RAM DOCX Validation
- **Finding IDs Addressed:** `PERF-03`
- **Recommended Implementation:** Project only needed scalar columns from `OCRBlock` (excluding `raw_engine_payload` and `polygon`), fetch only the latest `ReviewEdit` per block via `DISTINCT ON`, write DOCX directly to a temp file, release the builder `Document` before validation, and perform lightweight ZIP/XML round-trip validation.
- **Files / Components Likely to Change:** `src/services/export_service.py`.
- **Required Tests:** Export parity tests for 200+ page synthetic book comparing memory/output identity with existing `test_phase5_export.py`.
- **Expected Benefit:** >50% reduction in peak export RAM and faster exports for large 400+ page books.
- **Risks of the Fix:** Ensure PostgreSQL `DISTINCT ON` tie-breaking matches `(created_at DESC, id DESC)` exactly.
- **Dependencies:** None.
- **Estimated Effort:** Medium

#### P1-4: Fix Telugu Auto-Correct Whitespace Preservation, ZWNJ/ZWJ Conjunct Handling & Dictionary Spell-Fix Offset Bug
- **Finding IDs Addressed:** `OCR-02`
- **Recommended Implementation:** Switch `_autocorrect_single_block` and `find_block_suggestions_from_index` to regex whitespace-preserving tokenization (`re.split(r"(\s+)", text)`). Update `_TELUGU_WORD_RE` to support `\u0C00`, `\u200c`, `\u200d`; add a targeted repair rule proposing removal of spurious mid-conjunct `\u200c` (common Tesseract Telugu artifact) when it produces a valid dictionary word while preserving classical *nakāra-pollu* where valid. Return exact character offsets in `/dictionary/check-text` and replace by offset in `DictionaryPanel.tsx`.
- **Files / Components Likely to Change:** `src/services/lexicon_service.py`, `src/services/correction_service.py`, `src/services/dictionary_service.py`, `src/api/schemas.py`, `frontend/src/components/DictionaryPanel.tsx`, `frontend/src/types/api.ts`.
- **Required Tests:** Unit tests with multi-line Telugu verse blocks, Tesseract-style `వీద్‌యార్‌థులు` ZWNJ repairs, classical *nakāra-pollu* preservation, and substring-prefix spell-fix collisions in Vitest.
- **Expected Benefit:** Fixes silent newline destruction, unlocks dictionary auto-correction for Tesseract's #1 Telugu conjunct error, and eliminates wrong-word replacements in Dictionary Spell-Check.
- **Risks of the Fix:** Care required not to strip intentional classical ZWNJ/ZWJ in *granthika* books; expose behavior per `orthography_profile`.
- **Dependencies:** None.
- **Estimated Effort:** Medium

#### P1-5: Fix DOCX `verse` Role, Run-Level Complex Script (`w:cs`) Font, NFC Normalization & Control-Char Sanitization
- **Finding IDs Addressed:** `OCR-03`
- **Recommended Implementation:** Add a `TeluguVerse` style and handle `item.role == "verse"` in `_build_docx_bytes`; apply full `<w:rFonts w:cs=...>` + `<w:lang w:bidi="te-IN"/>` on styles/runs; apply NFC normalization and strip XML 1.0 illegal control characters (`[\x00-\x08\x0b\x0c\x0e-\x1f]`) before writing runs.
- **Files / Components Likely to Change:** `src/services/export_service.py`.
- **Required Tests:** Export DOCX with `verse`, `heading_1`, `heading_2`, `paragraph`, decomposed Telugu (`క\u0c46\u0c56`), and embedded `\x00`/`\x0b` control bytes; parse `word/document.xml` to verify valid XML, `TeluguVerse` style, NFC output, and `w:cs` attribute.
- **Expected Benefit:** Prevents export crashes on dirty PDF digital layers and produces faithful Telugu typography in Word/LibreOffice.
- **Risks of the Fix:** None.
- **Dependencies:** None.
- **Estimated Effort:** Small

#### P1-6: Add Deterministic Reading-Order Sorting, Column Detection, Header/Footer Flagging & Paragraph Reflow
- **Finding IDs Addressed:** `OCR-01`
- **Recommended Implementation:** Add a non-destructive post-OCR layout module (`src/ocr/layout.py`) that computes geometric `reading_order` (supporting single- and two-column Telugu pages), flags repeating header/footer/page-number blocks as review hints, and provides an opt-in paragraph-joining option for `editable_flow` DOCX export while preserving `verse` and heading breaks.
- **Files / Components Likely to Change:** `src/ocr/layout.py` (new), `src/ocr/paddle_provider.py`, `src/ocr/tesseract_provider.py`, `src/services/ocr_service.py`, `src/services/export_service.py`.
- **Required Tests:** Layout unit tests with shuffled single-column and two-column bounding boxes, running headers/page numbers (ASCII + Telugu numerals `౦-౯`), and prose vs verse reflow tests.
- **Expected Benefit:** Dramatically improves readability of two-column classical books and cuts manual header-ignoring and post-export Word cleanup time.
- **Risks of the Fix:** Incorrect column splits on sparse pages (e.g., title/TOC pages) — use conservative gutter-width thresholds and keep raw polygons untouched.
- **Dependencies:** Real printed Telugu benchmark (`TEST-01`) to validate across diverse book layouts.
- **Estimated Effort:** Large

#### P1-7: Bundle/Bootstrap Lexicon & Dictionary Artifacts in Fresh Docker & Pi Installs
- **Finding IDs Addressed:** `ARCH-03`
- **Recommended Implementation:** Update `deploy/Dockerfile` (multi-stage builder) and `deploy/raspberry-pi/install.sh` to invoke `scripts/build_telugu_lexicon.py` and `scripts/build_telugu_dictionary_db.py` (or download checksum-verified release artifacts) into `models/lexicon/`, and log a clear startup warning if either file is missing.
- **Files / Components Likely to Change:** `deploy/Dockerfile`, `deploy/raspberry-pi/install.sh`, `src/api/app.py`.
- **Required Tests:** Build verification check confirming `GET /api/v1/dictionary/stats` returns `dictionary_db_available: true` and `lexicon_words > 0` on a fresh container.
- **Expected Benefit:** Makes fresh Docker and Raspberry Pi deployments work out of the box with full Telugu dictionary and auto-correct capabilities.
- **Risks of the Fix:** Increases Docker image size by ~168 MB unless `telugu_dictionary.sqlite` is mounted as an initialized volume or compressed during build.
- **Dependencies:** Pinned asset checksums (`SEC-06`).
- **Estimated Effort:** Small

#### P1-8: Build Real Multi-Book Printed Telugu Ground-Truth Benchmark & Extend Metrics
- **Finding IDs Addressed:** `TEST-01`
- **Recommended Implementation:** Extend `src/evaluation/metrics.py` and `scripts/benchmark.py` to report `avg_sec_per_page`, `p95_sec_per_page`, `peak_rss_mb`, and `model_load_ms`, and execute the benchmark plan in Section 12 on 25–30 real printed Telugu book pages across ≥3 books.
- **Files / Components Likely to Change:** `src/evaluation/metrics.py`, `src/evaluation/report.py`, `scripts/benchmark.py`, `tests/test_metrics_and_report.py`.
- **Required Tests:** Unit tests asserting p95 calculation, peak RSS field propagation, and Markdown/CSV output formatting.
- **Expected Benefit:** Gives objective quantitative ground truth for every OCR model, preprocessing, and auto-correct decision.
- **Risks of the Fix:** Copyrighted book pages should remain in local git-ignored `data/gold/` while only anonymized aggregate benchmark reports are committed.
- **Dependencies:** Availability of ≥3 representative printed Telugu PDFs and human-verified gold transcriptions.
- **Estimated Effort:** Medium

---

### P2 — Medium Priority (Concurrency, Security Hygiene, OCR Tuning, Maintainability & Tests)

#### P2-1: Concurrency, Idempotency & Image I/O Fixes in Book/OCR/Lexicon Services
- **Finding IDs Addressed:** `PERF-05`, `PERF-06`
- **Recommended Implementation:** Replace `_PAGE_RENDER_LOCKS` with striped locks or `WeakValueDictionary`; warm lexicon asynchronously on startup (or via lightweight SQLite lookup); guard `queued`/`running` runs in `create_or_reuse_ocr_runs` and `resume_ocr_run`; lock `OCRJobExecutor._providers`; eliminate redundant `Image.open` and full-byte `skip_existing` reads; store `contrast_clahe` as 1-channel grayscale PNG.
- **Files / Components Likely to Change:** `src/services/book_service.py`, `src/services/ocr_service.py`, `src/services/lexicon_service.py`, `src/pdf/rasterizer.py`, `src/api/app.py`.
- **Required Tests:** Concurrency test firing parallel `POST /ocr-runs` and `/resume` on an active run verifying zero duplicate runs; unit test for >512 page render lock safety.
- **Expected Benefit:** Prevents duplicate wasted OCR runs, eliminates lock race conditions, speeds up cold starts and CLI re-runs, and shrinks preprocessed disk cache.
- **Risks of the Fix:** Verify PaddleOCR handles 1-channel grayscale PNG cleanly on both macOS and ARM64.
- **Dependencies:** None.
- **Estimated Effort:** Medium

#### P2-2: Frontend Polling Optimization & Atomic `handleBatchApproveUnflagged`
- **Finding IDs Addressed:** `PERF-07`
- **Recommended Implementation:** Replace the sequential `for` loop in `handleBatchApproveUnflagged` with a single `batchSavePage` call; debounce/reduce `listBookPages` refreshes during active OCR polling; configure `pdfjsLib.getDocument({ url, disableAutoFetch: true, rangeChunkSize: 65536 })`.
- **Files / Components Likely to Change:** `frontend/src/App.tsx`, `frontend/src/components/SourcePageViewer.tsx`.
- **Required Tests:** Vitest test verifying `handleBatchApproveUnflagged` issues 1 `batchSavePage` call instead of N `submitBlockEdit` calls.
- **Expected Benefit:** Much faster bulk approval over WAN and significantly reduced Raspberry Pi load during long OCR runs.
- **Risks of the Fix:** Ensure reverse proxy supports HTTP `Range` requests before enabling `disableAutoFetch`.
- **Dependencies:** None.
- **Estimated Effort:** Small

#### P2-3: Security Hygiene — DB Defaults, Supply-Chain Checksums, HTTP Headers & `/health` Cleanup
- **Finding IDs Addressed:** `SEC-05`, `SEC-06`, `SEC-07`
- **Recommended Implementation:** Pin GitHub asset URLs to commit SHAs with SHA-256 verification; remove duplicate `opencv-contrib-python` conflict from lockfile; add FastAPI security-header middleware, restrict CORS methods/headers, gate `/docs` behind env flag, remove `workspace_dir` from `/api/v1/health`; switch `manage_local_pg.py` from `--auth=trust` to `scram-sha-256`; remove hardcoded personal LAN IP from mobile settings and warn on cleartext HTTP Basic Auth.
- **Files / Components Likely to Change:** `src/api/app.py`, `src/api/routes.py`, `src/api/schemas.py`, `scripts/manage_local_pg.py`, `scripts/build_telugu_lexicon.py`, `scripts/build_telugu_dictionary_db.py`, `deploy/Dockerfile`, `deploy/raspberry-pi/install.sh`, `docker-compose.yml`, `mobile/lib/ui/features/studio/views/server_settings_sheet.dart`.
- **Required Tests:** Security header assertions on API & SPA responses; `/health` payload assertion confirming no filesystem path; SHA-256 mismatch rejection test in asset builders.
- **Expected Benefit:** Closes supply-chain, transport, and HTTP defense-in-depth gaps across local, Docker, and Pi deployments.
- **Risks of the Fix:** Removing `workspace_dir` from `/health` requires updating `mobile/test/widget_test.dart` and `tests/test_phase2_api_and_db.py`.
- **Dependencies:** None.
- **Estimated Effort:** Medium

#### P2-4: Improve Legacy-Font Detection, `deskew`, Comparator Alignment, Lexicon Recall & Confidence Calibration
- **Finding IDs Addressed:** `OCR-04`, `OCR-05`, `OCR-06`
- **Recommended Implementation:** Augment `has_legacy_font_encoding` with `page.get_fonts()` font-name/CMap checks; replace `minAreaRect` deskew with projection-profile or inner-margin Hough deskew; remove blind `fallback_idx` in `_match_comparator_block`; raise/tune `skeleton_index` & `delete1_index` bounds for classical Telugu recall; make low-confidence thresholds configurable in `AppSettings` and calibrate them via `TEST-01`.
- **Files / Components Likely to Change:** `src/pdf/rasterizer.py`, `src/services/ocr_service.py`, `src/services/review_service.py`, `src/services/lexicon_service.py`, `src/core/config.py`.
- **Required Tests:** Unit tests for legacy ASCII Telugu PDF classification, bordered-page deskew angle accuracy, mismatched line-count comparator matching (zero false disagreements), and classical Telugu word recall.
- **Expected Benefit:** Higher OCR recall on older DTP PDFs and classical books, fewer false review flags, and safer deskew.
- **Risks of the Fix:** Raising `delete1_index` cap increases lexicon RAM slightly (~10–25 MB) — profile on Raspberry Pi.
- **Dependencies:** `TEST-01` benchmark for calibrating confidence thresholds and ARM64 `text_det_limit_side_len`.
- **Estimated Effort:** Medium

#### P2-5: Modularize Frontend Studio, Fix Silent Logging & Unify Dependency Management
- **Finding IDs Addressed:** `ARCH-04`, `ARCH-05`
- **Recommended Implementation:** Extract focused React hooks (`useBookLibrary`, `useOcrPolling`, `usePageReview`) from `App.tsx` and sub-components from `ReviewEditorPanel.tsx`; log exceptions in `_maybe_record_training_sample`; move Paddle `os.environ` setup to startup bootstrap; consolidate direct dependencies (including `rapidfuzz`) into `pyproject.toml`.
- **Files / Components Likely to Change:** `frontend/src/App.tsx`, `frontend/src/components/ReviewEditorPanel.tsx`, `src/services/review_service.py`, `src/ocr/paddle_provider.py`, `pyproject.toml`, `deploy/requirements.runtime.txt`.
- **Required Tests:** Existing Vitest & pytest suites; unit test asserting warning log emitted when `_maybe_record_training_sample` fails.
- **Expected Benefit:** Improves readability, isolates UI re-renders, makes training-crop bugs observable, and prevents broken installs.
- **Risks of the Fix:** Refactoring large React components requires careful preservation of keyboard focus and block-sync state.
- **Dependencies:** None.
- **Estimated Effort:** Medium

#### P2-6: Close Contract, Security & Concurrency Test Gaps
- **Finding IDs Addressed:** `TEST-02`, `TEST-03`
- **Recommended Implementation:** Add OpenAPI-driven TypeScript contract checks (`openapi-typescript`), `PATCH .../digital-text` tests, adversarial PDF / streaming 413 tests, and concurrent job cancel/resume tests.
- **Files / Components Likely to Change:** `tests/test_phase3_review_api.py`, `tests/test_deployment_and_security.py`, `tests/test_phase2_api_and_db.py`, `frontend/package.json`.
- **Required Tests:** Self-validating CI test suite.
- **Expected Benefit:** Prevents regressions like `ARCH-01` and `SEC-02` from re-entering the codebase.
- **Risks of the Fix:** Minimal.
- **Dependencies:** `P0-2`, `P0-3`, `P0-4`, `P1-1`.
- **Estimated Effort:** Medium

---

### P3 — Future Improvements (Hardening, Polish & Optional Optimizations)

#### P3-1: Input Length Bounds, Safe OOXML Element Construction & Backup SSH Pinning
- **Finding IDs Addressed:** `SEC-08`
- **Recommended Implementation:** Add Pydantic `max_length`/`max_items` bounds on review/batch schemas; replace `parse_xml(rf'...')` in `_append_field` with `OxmlElement`; switch `backup_pi_to_mac.sh` to pinned SSH host keys (`StrictHostKeyChecking=yes`).
- **Files / Components Likely to Change:** `src/api/schemas.py`, `src/services/export_service.py`, `scripts/backup_pi_to_mac.sh`.
- **Required Tests:** Schema validation boundary tests (`422` on oversized payloads); existing DOCX TOC/page-number tests.
- **Expected Benefit:** Tightens defense-in-depth across API schemas, XML generation, and LAN backups.
- **Risks of the Fix:** Ensure `max_length` bounds comfortably accommodate legitimate long born-digital pages (e.g., 50,000+ chars).
- **Dependencies:** None.
- **Estimated Effort:** Small

#### P3-2: Documentation Hygiene, Observability Middleware & Shared Test Fixtures
- **Finding IDs Addressed:** `ARCH-06`, `TEST-04`
- **Recommended Implementation:** Update stale Phase-1 notice and remove personal LAN IP/username in `README.md`; add FastAPI request-ID + latency logging middleware; extract shared PostgreSQL `conftest.py` across the 6 DB test files and add Telugu Unicode/DOCX edge-case tests.
- **Files / Components Likely to Change:** `README.md`, `src/api/app.py`, `tests/conftest.py` (new), `tests/test_phase*.py`, `tests/test_deployment_and_security.py`, `tests/test_dictionary_api.py`.
- **Required Tests:** Full `pytest` suite passing with unified `conftest.py`.
- **Expected Benefit:** Cleaner onboarding, faster production debugging, and lower test maintenance overhead.
- **Risks of the Fix:** None.
- **Dependencies:** None.
- **Estimated Effort:** Small

#### P3-3: Controlled Evaluation of Lightweight Detector / ONNX Runtime on ARM64
- **Finding IDs Addressed:** `PERF-08`
- **Recommended Implementation:** Once the real Telugu benchmark (`P1-8`) is established, benchmark `PP-OCRv5_mobile_det` + `te_PP-OCRv5_mobile_rec` (and ONNX Runtime CPU execution if compatible) vs current `PP-OCRv5_server_det` on Raspberry Pi ARM64 and Apple Silicon CPU to evaluate throughput vs CER/Grapheme ER tradeoffs.
- **Files / Components Likely to Change:** `src/ocr/paddle_provider.py`, `scripts/benchmark.py` (experiment branch first).
- **Required Tests:** Reproducible benchmark run comparing CER, NFC CER, Grapheme ER, p95 sec/page, and peak RSS.
- **Expected Benefit:** Potential 2–4× speedup on Raspberry Pi if mobile detection achieves acceptable Telugu *vattu* CER.
- **Risks of the Fix:** Mobile detector may drop small Telugu diacritics/footnotes—do not adopt unless benchmark proves non-regression.
- **Dependencies:** `P1-8` (`TEST-01`).
- **Estimated Effort:** Medium

---

## 12. Performance Benchmarking Plan

Because only **1 synthetic 3-line page** has been benchmarked to date (`artifacts/benchmark/demo-run/benchmark_report.md`), no production throughput or accuracy claims should be treated as validated. Below is a reproducible benchmark specification tailored to `telugu-digitizer`.

### 1. Representative Ground-Truth Dataset (25–30 Pages Minimum)
Curate a locked manifest (`data/manifests/benchmark_v1.json`) spanning **at least 3 distinct real printed Telugu books** (with ≥1 held-out book never used for tuning):
- **Clean modern prose (8–10 pages):** Single-column 300-DPI modern print, crisp conjuncts, mixed Telugu + ASCII numerals/punctuation.
- **Classical / literary / poetry (*padyalu*) (6–8 pages):** Archaic spellings (*granthika*, *nakāra-pollu*, *śakaṭarēpha* `ఱ`), verse indentation, heavy Sanskrit conjuncts (*ottulu*).
- **Degraded / aged scans (6–8 pages):** Paper yellowing, ink bleed-through, broken strokes, slight skew (1–4°), spine curvature shadows.
- **Complex layout (4–5 pages):** Two-column commentary or glossary pages, running headers, footnotes, and mixed Telugu/English citations.
- **Born-digital & legacy-font PDF control set (2–3 pages):** 1 valid Unicode Telugu born-digital page + 1–2 legacy Anu/Shreelipi-encoded pages to verify PDF classification accuracy.

Store verified human gold transcripts as UTF-8 NFC text (`data/gold/<book_id>/page-NNNN.gold.txt`) following `docs/phase-1-annotation-guide.md`.

### 2. Required Metrics (Per Engine, Per Preprocessing Profile, Per Hardware Target)
Extend `src/evaluation/metrics.py` and `scripts/benchmark.py` to capture and report:

| Metric | Definition / Purpose |
|---|---|
| **Raw CER & NFC CER** | Levenshtein character edit rate before and after Unicode NFC normalization (exposes combining-mark decomposition noise). |
| **Grapheme Error Rate (Akshara proxy)** | Edit rate over Unicode extended grapheme clusters (`\X`) — essential for Telugu syllabic units. |
| **WER** | Whitespace-tokenized Word Error Rate (before and after opt-in Auto-Correct proposal pass). |
| **Exact-Line Accuracy** | Fraction of lines requiring zero human edits (direct proxy for proofreader time saved). |
| **Model Load Time (Cold Start, ms)** | Time to initialize `PaddleOCRProvider` (det + rec weights) before page 1. |
| **Warm Avg & p95 Sec / Page** | Mean and 95th-percentile inference latency after 1 warmup page (excludes cold init). |
| **Throughput (Pages / Min)** | Sustained warm pages/minute across full 30-page batch (and 100-page endurance subset). |
| **Peak RSS Memory (MB)** | Process + child peak RSS via `resource.getrusage` / `/proc/self/status` `VmHWM` during OCR and during 400-page DOCX export. |
| **API Latency (p50 / p95 ms)** | `/review`, `/autocorrect`, `/batch-save`, `/dictionary/search`, and `/exports` latency on a seeded 5-book (~2,000-page, ~60,000-block) PostgreSQL database. |

### 3. Controlled Experiment Matrix
Run identically on **(A) macOS Apple Silicon host** and **(B) Raspberry Pi ARM64 host** with fixed thread/env provenance recorded in `provenance.json`:
1. `paddle` (`PP-OCRv5_server_det + te_PP-OCRv5_mobile_rec`, `limit_side_len=1280` vs `1920`, preprocessing `none` / `contrast_clahe` / `deskew`).
2. `tesseract` (`tel` `tessdata_best`, `--oem 1`, `--psm 6` vs `--psm 3`).
3. Post-OCR Auto-Correct delta: measure WER & NFC CER **before** vs **after** applying proposals at `min_confidence` = `0.70`, `0.78`, `0.85`, `0.90` — explicitly tracking **false-positive corruption rate** (valid Telugu words mistakenly altered).

---

## 13. Security Validation Plan

No automated security scanners or live penetration tests were executed during this read-only audit. Execute the following validation suite after P0/P1 remediations:

1. **Authentication & Authorization Matrix (DAST / Integration):**
   - Against a staging deployment configured like `lahari.org/telugu/`, run an automated script verifying every mutating/sensitive endpoint (`POST/DELETE /books`, `POST /ocr-runs`, `POST /edits`, `POST /batch-save`, `POST /exports`, `POST/DELETE /dictionary/custom`) rejects unauthenticated requests with `401`, and verify `GET /api/v1/health` exposes no absolute server paths.
2. **Upload & Malformed PDF Fuzzing:**
   - Test `POST /api/v1/books` with: (a) stream exceeding `MAX_UPLOAD_MB` (verify early `413` and flat RSS), (b) non-PDF polyglot / spoofed `.pdf` extension, (c) encrypted PDF, (d) truncated/corrupt PDF, (e) 1-page PDF with `rect = 7200 × 7200 pt` (verify pixel-area clamp prevents OOM), (f) filename with path traversal (`../../etc/passwd.pdf`) and null bytes.
3. **Path Traversal & Storage Isolation:**
   - Fuzz `storage_key` resolution, SPA fallback (`GET /../.env`, `/%2e%2e/pyproject.toml`), and export download filenames for traversal or header-injection (`\r\n` in `Content-Disposition`).
4. **Dependency & Container Scanning (SCA):**
   - Run `pip-audit -r deploy/requirements.runtime.txt` and `pip-audit -r requirements-phase5.lock.txt` (after resolving dual OpenCV).
   - Run `cd frontend && npm audit` and `cd mobile && dart pub outdated`.
   - Scan built Docker image with `trivy image` and verify `docker run --rm --entrypoint id <image>` reports a non-root UID.
5. **HTTP Header & Proxy Verification:**
   - Inspect live headers behind Caddy/Apache (`curl -I`) for `Strict-Transport-Security`, `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options`, and confirm spoofed `X-Forwarded-For` from untrusted IPs is ignored.

---

## 14. Recommended Regression Tests

Add the following deterministic tests (without requiring external network calls):

1. **API Contract & Schema Tests (`tests/test_phase3_review_api.py` + CI OpenAPI check):**
   - `PATCH /api/v1/books/{id}/pages/{n}/digital-text` matching exact frontend `updatePageDigitalText` payload and asserting persisted `digital_text_content`.
   - `POST /api/v1/books/{id}/pages/{n}/blocks` with explicit `bbox` verifying persisted polygon and returned `ocr_run_id`.
   - Automated check generating TS definitions from FastAPI OpenAPI schema and running `tsc --noEmit` in `frontend/`.
2. **Upload Streaming, Adversarial PDF & Lifecycle Tests (`tests/test_deployment_and_security.py`):**
   - Oversized upload rejected with `413` while asserting no temp file remains in `workspace/tmp/`.
   - Encrypted PDF rejected cleanly (`400`); oversized page rect (`7200×7200 pt`) clamped safely below `MAX_RENDER_PIXELS`.
   - `DELETE /api/v1/books/{id}` removes `originals/`, `pages/`, `ocr/`, `exports/`, **and** `training_crops/` and cancels/blocks active OCR runs.
   - Concurrent `POST /ocr-runs` (same `idempotency_key`) and `POST /ocr-runs/{id}/resume` on a `running` job never enqueue duplicate executions.
   - `TesseractOCRProvider.recognize` timeout triggers clean failure handling without hanging the executor.
3. **Telugu Unicode, NLP & Export Correctness Tests (`tests/test_lexicon_and_autocorrect.py`, `tests/test_phase5_export.py`):**
   - Multi-line block (`"పద్యం మొదటి పాదం\nరెండవ పాదం"`) passed through `_autocorrect_single_block` and `find_block_suggestions_from_index` preserves `\n` verbatim.
   - Tesseract-style spurious ZWNJ word (`"వీద్\u200cయార్\u200cథులు"`) is detected and proposed as `"విద్యార్థులు"` (or `"వీద్యార్థులు"` per lexicon), while valid classical *nakāra-pollu* is not blindly corrupted.
   - Combining Candrabindu (`\u0C00`) and decomposed vowel signs (`క\u0c46\u0c56`) survive review → export in valid NFC.
   - DOCX export with `verse` role emits distinct verse formatting; `word/document.xml` contains `w:cs` Complex Script font attribute on Telugu runs; `digital_text_content` containing `\x00`/`\x0b`/`\x1f` exports cleanly without `lxml` errors.
   - Frontend Vitest test in `DictionaryPanel.test.tsx` verifying `handleApplySpellFix` replaces only the targeted token occurrence when the misspelled token is a prefix/substring of an earlier valid word.
4. **Performance / Query-Count Guardrails (`tests/test_query_performance.py`):**
   - SQLAlchemy query counter asserting `batch_save_and_approve_page` for 40 blocks executes a bounded O(1) number of SQL queries (not 3N+ queries), and `propose_page_autocorrections` hits the cached `SentenceContextModel` on repeat calls.

---

## 15. Areas That Were Reviewed and Found Acceptable

The following design choices and implementations were directly verified in source code and found sound:

1. **Immutable Raw OCR & Append-Only Audit Trail (`src/db/models.py`, `src/services/review_service.py`):** `OCRBlock.raw_text` is never mutated by human edits; every correction, approval, revert, or ignore appends an immutable `ReviewEdit` row, and `Revert to Raw OCR` cleanly restores original text.
2. **Read-Only Source PDF Storage & SHA-256 Deduplication (`src/core/storage.py:44–52`, `src/services/book_service.py:130–142`):** Original PDFs are written atomically (`atomic_write_bytes` via temp file + `os.replace`), `chmod 0o444`, and deduplicated by SHA-256.
3. **Workspace Path Containment (`src/common/io.py`, `src/core/storage.py:38–42`, `src/api/app.py:206–209`):** Both `LocalFilesystemStorage.resolve_key` and FastAPI's SPA static file handler resolve paths and enforce `is_relative_to(...)` containment, preventing directory traversal.
4. **SQL Injection Hygiene (`src/services/*.py`, `src/services/dictionary_service.py:52`):** PostgreSQL access uses SQLAlchemy 2.x parameterized ORM expressions throughout; the standalone SQLite dictionary is opened read-only via `file:<path>?mode=ro` URI (`dictionary_service.py:52`) with bound `?` parameters and sanitized FTS5 query strings.
5. **Constant-Time Basic Auth Comparison (`src/api/app.py:161–163`):** When Basic Auth is enabled, credentials are verified with `hmac.compare_digest` against UTF-8 bytes, avoiding timing side channels.
6. **Frontend XSS Hygiene (`frontend/src/components/*.tsx`):** Zero occurrences of `dangerouslySetInnerHTML`, `innerHTML`, or `eval` were found; Telugu OCR text and dictionary definitions render through React text nodes (with HTML tags already stripped at SQLite build time in `scripts/build_telugu_dictionary_db.py`).
7. **Mobile Credential Handling (`mobile/lib/data/repositories/digitizer_repository.dart:26–51`):** The Flutter app persists only `baseUrl` and `username` in `SharedPreferences` and keeps the Basic Auth `password` in memory only (not written to plaintext local storage).
8. **Crash-Recovery Startup Lifespan & Atomic Page Commits (`src/api/app.py:48–73`, `src/services/ocr_service.py`):** Interrupted OCR runs automatically recover to `partial` on startup, and completed pages are persisted per-page so multi-hour jobs can resume without losing finished work.
9. **Database Indexing Foundation (`alembic/versions/0001_initial_schema.py`, `0003_performance_indexes.py`, `0004_custom_dictionary_words.py`):** Core hot lookup paths (`ocr_blocks(ocr_run_id, book_page_id)`, `document_text_blocks(version_id, ocr_block_id)`, `correction_memory(language_code, status, scope, book_id)`, `custom_dictionary_words(language_code, word)`) have appropriate composite/unique indexes and cascading foreign keys.
10. **Telugu Evaluation Metrics Design (`src/evaluation/metrics.py`):** Explicitly measuring both Raw CER and NFC CER alongside Unicode extended grapheme clusters (`\X`) and WER demonstrates strong awareness of Indic script evaluation subtleties.

---

## 16. Limitations of This Audit

In strict accordance with the read-only audit constraints, the following boundaries apply to this report:

1. **No Tests Executed Against Live Databases or Runtimes:** `pytest` (which drops/recreates PostgreSQL schemas in test fixtures), `vitest`, `flutter test`, and `scripts/benchmark.py` were **not executed** during this audit so that zero databases, processes, or workspace states were modified. All findings are substantiated through static source inspection and inspection of existing committed artifacts.
2. **No Live Production Host Inspection:** The live Raspberry Pi (`systemd` runtime, `/etc/telugu-digitizer/env`, Apache reverse-proxy vhost config, TLS certificates, firewall rules, and live PostgreSQL tuning) and `https://lahari.org/telugu/` were not accessed or probed. `SEC-01` reflects the repository's shipped installation scripts (`deploy/raspberry-pi/install.sh`) and documented defaults (`README.md:216`).
3. **No Automated External Vulnerability Scanners Run:** `pip-audit`, `npm audit`, `bandit`, and `trivy` were not executed against online CVE databases; dependency risk analysis (`SEC-06`) is limited to manifest/lockfile inspection and known packaging conflicts.
4. **No Live Memory / CPU Profiling:** Peak RAM estimates (e.g., for DOCX export and PDF pixel-bombs) are derived analytically from code paths and pixel/DOM sizing rather than measured via live `tracemalloc` or `VmHWM` telemetry.
5. **Binary Assets Inspected at Metadata/Schema Level Only:** Local binary files (`models/tesseract/tessdata/tel.traineddata`, `models/lexicon/telugu_dictionary.sqlite`, `tests/fixtures/sample_scanned_telugu.pdf`) were inspected via file metadata, build scripts, and `models/lexicon/manifest.json`, not via exhaustive binary content inspection.
6. **Flutter Mobile UI Views:** Mobile data/repository/service/viewmodel/settings layers and widget tests were inspected in full; secondary Flutter presentation views (`library_tab_view.dart`, `page_review_tab_view.dart`, `correction_memory_tab_view.dart`, `export_tab_view.dart`, `studio_home_view.dart`) were not exhaustively audited line-by-line for minor Flutter UI layout issues.
