# 04 — Phase 1 Implementation Plan: Telugu OCR Proof of Concept

## 1. Objective

Prove that the selected local OCR engines can process real printed Telugu book pages, produce inspectable structured output and be compared against manually transcribed ground truth.

Phase 1 is deliberately a CLI tool. No React interface, LLM correction, model training, account system or background queue is required.

## 2. Input dataset

Collect 20–30 pages from at least three printed Telugu books. Only use material that can legally be processed for this project.

Choose representative pages:

- clean modern print;
- smaller font / dense paragraph text;
- headings and chapter openings;
- page numbers and headers/footers;
- pages with common punctuation and digits;
- if available, slightly skewed or lower-quality scans.

Do not include handwriting in the first dataset. Avoid using 30 nearly identical pages from one book; that would hide generalization issues.

## 3. Dataset split

Split by **book**, not by randomly shuffling lines from the same book, to reduce leakage from font, print and scan characteristics.

Suggested split for three books:

- Book A: development/tuning pages.
- Book B: validation pages.
- Book C: held-out test pages.

If only three books are available, keep the test book untouched until OCR configs are frozen. Add more books before making broad quality claims.

## 4. Gold transcription process

For the benchmark subset, manually transcribe each selected page from the original image.

Rules:

1. Transcribe what is visibly printed, not what the sentence should say.
2. Preserve original spelling, punctuation, paragraph boundaries and page numbers according to the annotation policy.
3. Mark genuinely unreadable regions explicitly (for example `[UNREADABLE]`) rather than guessing.
4. Use a consistent policy for hyphenation and line breaks.
5. Normalize gold and OCR strings to Unicode NFC for normalized scoring, but retain exact raw strings.
6. Have a second reviewer independently check a subset and adjudicate disagreements.

For Phase 1, annotate 10–20 pages in full if time is constrained; keep the remaining pages as unscored smoke/throughput pages. Increase gold coverage before any release accuracy claims.

## 5. Implementation tasks

### Task 1 — Repository and environment

- Create the project layout described in `01-technical-architecture.md`.
- Create an isolated Python environment.
- Install PaddlePaddle CPU, PaddleOCR, Tesseract Telugu data and required libraries.
- Capture package versions and model checksums.

### Task 2 — PDF ingestion and rasterization

- Open PDF with PyMuPDF.
- Record page count and page dimensions.
- Render every selected page at 300 DPI to PNG.
- Name outputs deterministically by book ID and one-based page number.
- Preserve PDF source page numbering and original file hash.
- Detect whether pages are digital text, scanned image or mixed, but do not include direct text extraction in OCR benchmark scores.

### Task 3 — OCR adapters

Implement a small common interface:

```python
class OCRProvider:
    def recognize(self, image_path: str) -> dict:
        """Return structured text blocks and raw engine metadata."""
        raise NotImplementedError
```

Build:

- `PaddleOCRProvider`: PP-OCRv5 Telugu (`lang="te"`).
- `TesseractOCRProvider`: Telugu `tel.traineddata`, LSTM engine.

Both must receive the same PNG file. Do not preprocess differently by engine in the first comparison.

### Task 4 — Structured outputs

Save one JSON result per page per engine, plus plain text for convenience. Required fields:

- `book_id`, `page_number`, `source_pdf_sha256`;
- `engine`, `engine_version`, `model_id`, `config`;
- `render_dpi`, `image_path`, `image_sha256`;
- `elapsed_ms`;
- `blocks[]`: text, confidence (nullable), polygon/bounding box (nullable), reading order index;
- `raw_result_path`.

Tesseract TSV/hOCR can be used to retain boxes and confidence; PaddleOCR's JSON output should retain its recognition text, scores and polygons where available.

### Task 5 — Benchmark runner

- Load the page manifest and gold transcriptions.
- Run both engines sequentially on the exact same page images.
- Save raw output before normalization.
- Normalize separate copies to NFC for metric calculation.
- Calculate metrics described in `05-benchmark-methodology.md`.
- Generate CSV/JSON and Markdown summary by engine, book, page and image-quality group.

### Task 6 — Failure handling

- One failed page must not terminate the entire book run.
- Save exception type/message and retry status.
- Never silently skip pages.
- Create a final manifest showing expected versus completed pages for each engine.

## 6. Proposed repository structure

```text
telugu-book-digitizer/
  README.md
  docs/
  data/
    originals/
    pages/
    gold/
    manifests/
  models/
    tesseract/tessdata/
  artifacts/
    paddle/
    tesseract/
    benchmark/
  scripts/
    render_pdf.py
    run_ocr.py
    benchmark.py
  src/
    pdf/
    ocr/
    evaluation/
    common/
  tests/
  requirements-phase1.lock.txt
```

Keep raw source data out of Git. Commit manifests, scripts, small sanitized examples and documentation only. Add `data/`, `models/`, `artifacts/` and sensitive book content to `.gitignore`.

## 7. Phase 1 sequence and exit gates

| Step | Deliverable | Exit gate |
|---|---|---|
| 1 | Environment smoke tests | Both OCR engines import/run on one page |
| 2 | PDF rasterizer | Page count matches; output images open and are deterministic |
| 3 | OCR adapters | Both engines return structured output on the same sample page |
| 4 | Dataset/gold set | Gold text checked and annotation policy recorded |
| 5 | Benchmark runner | Metrics computed reproducibly from saved output |
| 6 | Benchmark report | Accuracy, speed and failure analysis documented |

## 8. First working milestone — strict definition

The milestone is complete when:

- 20–30 printed Telugu pages from at least three books have a page manifest;
- all pages selected for the run are rendered at 300 DPI and accounted for;
- both OCR engines have been run on identical page rasters;
- raw JSON/text and engine/model metadata are saved;
- a manually verified gold subset exists;
- report includes CER, WER, grapheme/akshara error rate, exact-line accuracy and seconds/page;
- the report identifies the winning configuration separately for clean pages and degraded pages, if performance differs;
- no model-selection decision is based on one visually impressive page.

Do not set a fixed minimum CER target before observing the baseline. First establish a trustworthy baseline; then set a product acceptance threshold with a known trade-off between error rate and manual review effort.

## 9. Deliverables

1. Runnable CLI source code.
2. Installation instructions.
3. Dataset manifest and annotation guide.
4. Raw output from both engines.
5. Reproducible benchmark script.
6. Benchmark report and error examples.
7. Model/package provenance manifest.
8. Decision note recommending next step.
