# 01 — Technical Architecture

## 1. Architecture decision

Use a **modular monolith** for the first product version. It is simpler to develop and debug than microservices, while its internal modules remain independently replaceable.

```text
Browser (React + TypeScript)
        |
        | localhost REST API
        v
FastAPI application
        |
        +--------------------+-------------------+
        |                    |                   |
   PDF service          OCR service        Review service
        |                    |                   |
    PyMuPDF             OCRProvider          Corrections
    page raster         PaddleOCR             Audit log
                        Tesseract             Memory lookup
        |                    |                   |
        +--------------------+-------------------+
                             |
                    PostgreSQL (metadata)
                             |
                  Local filesystem storage
              PDFs / page images / OCR JSON / exports
                             |
                     Export service
                      python-docx / TXT
```

Optional local LLM integration is a separate adapter and must not be required for the core workflow.

## 2. Recommended stack

| Layer | Technology | Reason |
|---|---|---|
| UI | React + TypeScript | Review editor and page navigation |
| PDF viewer | PDF.js | Display original pages and zoom/pan |
| API | FastAPI + Pydantic | Python-native OCR integration and typed API |
| PDF handling | PyMuPDF | Render pages and inspect/extract PDF text |
| Image processing | OpenCV + Pillow | Deskew, contrast, crop and quality checks |
| Primary OCR | PaddleOCR 3.x, PP-OCRv5 Telugu | Dedicated Telugu recognition model |
| Baseline OCR | Tesseract 5, `tel.traineddata` | Independent alternative and comparison |
| Database | PostgreSQL | Books, page records, OCR runs, corrections, audit |
| Local object storage | Filesystem | Predictable and simple local storage |
| Document export | python-docx | DOCX creation |
| Unicode handling | Python `unicodedata`, `regex` | NFC normalization and grapheme-aware metrics |
| Packaging | Docker Compose (app dependencies as needed) | Reproducible local setup |

## 3. Deliberately defer these dependencies

- **Redis/Celery:** Add when OCR is run through the web app and requests need durable background queues. Phase 1 can use a sequential CLI runner.
- **MinIO:** Use local directories for one-user local deployment. Add an object-storage abstraction so MinIO can be adopted later.
- **pgvector:** Not needed for literal word/context correction lookup. Start with indexed PostgreSQL queries. Add vector search only if a real semantic retrieval need appears.
- **LLM:** Do not put it on the Phase 1 critical path. It risks fluent but false rewrites.
- **Kubernetes:** Not justified for a local desktop-style tool.
- **Spring Boot:** Not required in v1; keep OCR and AI in Python.

## 4. Core processing flow

### 4.1 Import and classify

1. Validate PDF type, page count and file size.
2. Calculate SHA-256 for source identity and duplicate detection.
3. For each page, inspect extracted text and image coverage.
4. Mark page as `digital_text`, `scanned_image`, or `mixed`.
5. For this project, scanned images are the OCR benchmark path. Digital text extraction is a separate non-OCR path and must not be compared as an OCR engine result.

### 4.2 Render

- Render scanned pages at a configured starting DPI of 300.
- Retain the original PDF and generated PNG/TIFF page images.
- Store page width, height, render DPI and source page index.
- Do not upscale low-resolution source pixels and claim the added pixels contain new detail.

### 4.3 Preprocess

Run baseline OCR on the unmodified render first. Create optional processed variants (deskew, grayscale, contrast, mild denoise) for controlled experiments. Never destructively modify the only source image.

Avoid aggressive morphology, erosion/dilation and binarization until evaluated. Telugu vowel signs and combining marks can be damaged by over-processing.

### 4.4 OCR

- Pass the exact same image bytes to both OCR engines.
- Record engine name, engine version, model identifier, config, run timestamp and elapsed time.
- Preserve each engine's text, confidence, detected polygons/boxes and raw JSON output.
- Do not merge the results automatically in Phase 1.

### 4.5 Correction and review (later phase)

1. Show the source page next to OCR text.
2. Link blocks/lines to source coordinates.
3. Allow manual correction.
4. Store a correction event rather than mutating the original OCR result.
5. Put approved corrections into correction memory with book/document scope and context.

### 4.6 Export

Generate from the human-approved text version. If no review has been completed, label the export as machine-generated/unreviewed.

## 5. Local storage layout

```text
workspace/
  originals/<book_id>/source.pdf
  pages/<book_id>/page-0001.png
  pages/<book_id>/page-0002.png
  ocr/<book_id>/<run_id>/paddle/page-0001.json
  ocr/<book_id>/<run_id>/tesseract/page-0001.json
  gold/<dataset_version>/<book_id>/page-0001.txt
  exports/<book_id>/<export_id>/book-editable.docx
  exports/<book_id>/<export_id>/book-page-preserving.docx
  exports/<book_id>/<export_id>/book.txt
  logs/
```

Never use the original filename as a path without sanitization. Generate internal UUIDs and store the original filename as metadata.

## 6. Deployment profile

### Primary supported development/inference target

Ubuntu x86_64 CPU with Python 3.11/3.12, PaddlePaddle CPU runtime and PaddleOCR. This is the most straightforward reproducible target for the PP-OCRv5 benchmark.

### macOS Apple Silicon

Tesseract can be used locally for the baseline. Do not assume the PaddlePaddle Python wheel is available for every macOS/Apple Silicon/Python combination. Verify the current official wheel matrix before promising native PaddleOCR support. If the PaddlePaddle wheel is unavailable, run the primary PaddleOCR process on the user's Ubuntu x86_64 machine locally, or use a compatible Linux container/host; keep the data local.

### GPU

Do not make GPU mandatory. Start with CPU inference. Add a GPU-specific PaddlePaddle wheel only after recording the NVIDIA driver/CUDA compatibility required by the official installation guide. Do not install CUDA packages by guessing from the system's CUDA toolkit version.

## 7. Reliability and safety

- Processing is idempotent by source SHA-256, page index, engine/model version and configuration.
- A failed page can be retried without rerunning the entire book.
- Store source documents read-only after import.
- Keep processing logs and error records per page.
- Validate every output path remains inside the configured workspace.
- Bind the API to `127.0.0.1` by default; expose on LAN only through an explicit setting.
- No telemetry or remote content upload by default.
