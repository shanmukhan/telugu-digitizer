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
