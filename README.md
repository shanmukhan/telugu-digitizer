# Telugu Book Digitizer — Phase 1 (CLI OCR Proof of Concept)

Local-first CLI pipeline to rasterize printed Telugu book PDFs, run **PaddleOCR PP-OCRv5 Telugu** (`lang="te"`, `ocr_version="PP-OCRv5"`) and **Tesseract 5 Telugu** (`tel.traineddata` from `tessdata_best`, `--oem 1`) on identical 300 DPI page images, preserve raw OCR outputs untouched, and compute reproducible Telugu OCR benchmark metrics.

> **Scope notice:** This repository currently implements **Phase 1 only** (`docs/04-phase-1-implementation-plan.md`). No web UI, FastAPI backend, database, LLM post-correction, or DOCX exporter is included in this phase.

---

## 1. Environment & Technical Notes

### Local macOS Apple Silicon (`osx-arm64`) Setup

On macOS ARM64 where Homebrew/system Tesseract may not be preinstalled:

1. Create an isolated Python 3.11 + Tesseract 5.5.4 runtime (`conda-forge`) and clean Python `.venv`:

```bash
conda create -y -p .tools/tesseract -c conda-forge python=3.11.14 tesseract
.tools/tesseract/bin/python -m venv .venv
ln -sf ../../.tools/tesseract/bin/tesseract .venv/bin/tesseract
```

2. Download official `tessdata_best/tel.traineddata`:

```bash
mkdir -p models/tesseract/tessdata
curl -fsSL https://github.com/tesseract-ocr/tessdata_best/raw/main/tel.traineddata \
  -o models/tesseract/tessdata/tel.traineddata
shasum -a 256 models/tesseract/tessdata/tel.traineddata
```

3. Install PaddlePaddle CPU, PaddleOCR, and Phase 1 libraries:

```bash
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install "paddlepaddle==3.3.1" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
.venv/bin/python -m pip install paddleocr pymupdf opencv-python-headless pillow numpy regex pandas jiwer pytest
.venv/bin/python -m pip install -e . --no-deps
```

> **Documented Package Version Decision (`paddlepaddle==3.3.1` vs `3.2.0`):**  
> While `docs/03-local-installation.md` noted `paddlepaddle==3.2.0` as the example from the upstream guide, testing `paddlepaddle==3.2.0` (`macosx_11_0_arm64`) on this Apple Silicon host reproduced a native `SIGBUS` (`KERN_PROTECTION_FAILURE` inside `phi::funcs::im2col_common<float>`) when running detection on 300-DPI images (`2480×1500`). Upgrading to the official `paddlepaddle==3.3.1` (`macosx_11_0_arm64`) wheel from the official PaddlePaddle CPU index resolved the crash across `2480×1500` and full A4 300-DPI (`2480×3508`) pages while keeping the exact pinned OCR models (`PP-OCRv5_server_det` and `te_PP-OCRv5_mobile_rec`) unchanged. On Ubuntu x86_64 CPU hosts, verify `3.2.0` or `3.3.1` from the official index and record exact versions in `provenance.json`.

### Locked OCR Engine Configurations

- **Primary candidate (`PaddleOCRProvider`):** `PaddleOCR(lang="te", ocr_version="PP-OCRv5", device="cpu", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)`, verified at runtime to load `PP-OCRv5_server_det` and `te_PP-OCRv5_mobile_rec`. Never silently falls back to `PP-OCRv6` or a non-Telugu recognizer.
- **Secondary baseline (`TesseractOCRProvider`):** `tesseract <img.png> <outbase> -l tel --oem 1 --psm 6 --tessdata-dir models/tesseract/tessdata -c tessedit_create_tsv=1 -c tessedit_create_txt=1`.

---

## 2. Usage

### Step 1 — Render PDF pages at 300 DPI

```bash
.venv/bin/python scripts/render_pdf.py \
  --pdf data/originals/book_a.pdf \
  --book-id book_a \
  --start-page 1 --end-page 10 \
  --dpi 300 \
  --split dev \
  --page-quality clean \
  --layout-type single_column \
  --manifest data/manifests/phase1_dataset.json
```

### Step 2 — Annotate gold transcriptions and link them in the manifest

See [docs/phase-1-annotation-guide.md](docs/phase-1-annotation-guide.md) and [data/manifests/manifest.example.json](data/manifests/manifest.example.json). Set `"gold_path"` for each annotated page in `data/manifests/phase1_dataset.json`.

### Step 3 — Run both OCR engines on identical page images

```bash
.venv/bin/python scripts/run_ocr.py \
  --manifest data/manifests/phase1_dataset.json \
  --engines paddle tesseract \
  --run-id phase1-run-01 \
  --warmup
```

Raw engine payloads (`*.raw.json`, `*.raw.tsv`, `*.raw.txt`) and structured per-page records (`*.json`, `*.txt`) are saved under `artifacts/paddle/` and `artifacts/tesseract/`.

### Step 4 — Score and generate the benchmark report

```bash
.venv/bin/python scripts/benchmark.py \
  --manifest data/manifests/phase1_dataset.json \
  --run-id phase1-run-01 \
  --run-manifest artifacts/run-phase1-run-01.manifest.json
```

Or run OCR + evaluation together in one command:

```bash
.venv/bin/python scripts/benchmark.py \
  --manifest data/manifests/phase1_dataset.json \
  --run-id phase1-run-01 \
  --engines paddle tesseract \
  --warmup
```

Outputs are written atomically to `artifacts/benchmark/<run-id>/`:
- `benchmark_report.md`
- `benchmark_results.json`
- `benchmark_pages.csv`
- `benchmark_summary.csv`
- `provenance.json`

---

## 3. Running Tests

```bash
.venv/bin/pytest -v
```

---

## 4. Phase 2 — PDF Processing Backend (FastAPI + PostgreSQL + Alembic)

### Start local PostgreSQL & run migrations

Without Docker (using project-local `.tools/postgres`):

```bash
.venv/bin/python scripts/manage_local_pg.py start
.venv/bin/alembic upgrade head
```

Or with Docker Compose:

```bash
docker compose up -d postgres
.venv/bin/alembic upgrade head
```

### Start the localhost FastAPI server

```bash
.venv/bin/python scripts/run_api.py
```

The API binds to `http://127.0.0.1:8000` by default (OpenAPI docs at `http://127.0.0.1:8000/docs`).

Key Phase 2 endpoints under `/api/v1`:
- `GET /api/v1/health`
- `POST /api/v1/books` (multipart PDF upload, SHA-256 deduplication, page classification, 300-DPI rendering)
- `GET /api/v1/books` / `GET /api/v1/books/{book_id}` / `DELETE /api/v1/books/{book_id}`
- `GET /api/v1/books/{book_id}/pages`
- `GET /api/v1/books/{book_id}/pages/{page_number}/image`
- `GET /api/v1/books/{book_id}/pages/{page_number}/digital-text`
- `POST /api/v1/books/{book_id}/ocr-runs` (idempotent & restartable background execution)
- `GET /api/v1/ocr-runs/{run_id}` / `POST /api/v1/ocr-runs/{run_id}/resume`
- `GET /api/v1/ocr-runs/{run_id}/pages/{page_number}`

---

## 5. Phase 3 — Human Review UI (React + TypeScript + PDF.js)

### Build & serve via FastAPI (`http://127.0.0.1:8000`)

```bash
cd frontend
npm install
npm run build
cd ..
.venv/bin/python scripts/run_api.py
```

When `frontend/dist/` is built, opening `http://127.0.0.1:8000` launches the React Review Studio directly from FastAPI.

### Development mode (`http://127.0.0.1:5173`)

Run FastAPI on `:8000` in one terminal and Vite dev server (proxying `/api` to `:8000`) in another:

```bash
cd frontend && npm run dev
```

### Frontend tests

```bash
cd frontend && npm test
```

---

## 6. Phase 4 — Correction Memory & Contextual Suggestions

Phase 4 endpoints under `/api/v1`:
- `POST /api/v1/ocr-blocks/{block_id}/edits` (`add_to_correction_memory`, `memory_scope`: `book_only` or `global_suggestion`, `correction_type`)
- `GET /api/v1/corrections/search` (context-aware suggestion lookup with conflict detection)
- `GET /api/v1/corrections` (browse and filter active/disabled/rejected records)
- `POST /api/v1/corrections/{correction_id}/approve` / `/reject`
- `PATCH /api/v1/corrections/{correction_id}/status` (`active`, `disabled`, `superseded`, `rejected`)

---

## 7. Phase 5 — DOCX and TXT Export

Phase 5 endpoints under `/api/v1`:
- `POST /api/v1/books/{book_id}/exports` (`format`: `docx` or `txt`, `layout_mode`: `editable_flow` or `page_preserving`, `text_version`: `human_approved` or `raw_ocr`)
- `GET /api/v1/books/{book_id}/exports`
- `GET /api/v1/exports/{export_id}` / `/download` / `/manifest`

All exports run UTF-8 and `python-docx` round-trip verification before saving and emit an `export-manifest.json` sidecar under `workspace/exports/<book_id>/<export_id>/`.

---

## 8. Raspberry Pi & Public Hosting (`https://lahari.org/telugu/`)

Full Raspberry Pi (`aarch64`) deployment configuration is provided in `deploy/` and documented in [docs/13-raspberry-pi-lahari-deployment.md](docs/13-raspberry-pi-lahari-deployment.md):

- **Bare-metal Raspberry Pi OS (`systemd` + PostgreSQL + Apache/Caddy, default):** [deploy/raspberry-pi/install.sh](deploy/raspberry-pi/install.sh), [deploy/raspberry-pi/telugu-digitizer.service](deploy/raspberry-pi/telugu-digitizer.service), and [deploy/raspberry-pi/remote-deploy.sh](deploy/raspberry-pi/remote-deploy.sh). Currently deployed natively on `lipi@192.168.1.13` (loopback `127.0.0.1:8085`, proxied under `https://lahari.org/telugu/` and linked from `https://lahari.org/` without replacing existing `lahari.org` routes).
- **Optional Docker Compose + Caddy + Cloudflare Tunnel:** [deploy/compose.lahari.yml](deploy/compose.lahari.yml), [deploy/Dockerfile](deploy/Dockerfile), [deploy/Caddyfile.tunnel](deploy/Caddyfile.tunnel), [deploy/Caddyfile.direct](deploy/Caddyfile.direct), and [deploy/.env.lahari.example](deploy/.env.lahari.example).
- **Public access & capabilities:** Open by default with no login page (`APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD` unset, optional Basic Auth if explicitly set), configurable `CORS_ALLOWED_ORIGINS`, reverse-proxy headers (`PROXY_HEADERS`), relative subpath asset/API resolution, and `GET /api/v1/capabilities`.





