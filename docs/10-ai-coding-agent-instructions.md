# 10 — Instructions for AI Coding Agents

## Mission

Act as a senior Python, computer-vision and full-stack engineer. Implement the Telugu Book Digitizer according to the specification files in this folder. The product converts printed Telugu PDFs into editable Unicode DOCX/TXT and improves future recognition suggestions using reviewed corrections.

## Mandatory reading order

Read these files before coding:

1. `README.md`
2. `00-product-brief.md`
3. `01-technical-architecture.md`
4. `02-ocr-model-selection.md`
5. `03-local-installation.md`
6. `04-phase-1-implementation-plan.md`
7. `05-benchmark-methodology.md`
8. `06-database-design.md`
9. `07-api-contracts.md`
10. `08-correction-memory-and-learning.md`
11. `09-document-export-specification.md`
12. `11-architecture-decisions.md`
13. `12-acceptance-criteria.md`

## Non-negotiable requirements

- The initial target is printed Telugu only.
- Keep the product local-first and usable without cloud services.
- Primary OCR candidate is PaddleOCR 3.x with `lang="te"` and `ocr_version="PP-OCRv5"`; do not silently use the PP-OCRv6 default.
- Secondary OCR baseline is Tesseract Telugu `tel.traineddata` from `tessdata_best`, using LSTM mode.
- Do not overwrite raw OCR output.
- Preserve source PDF, page images, engine outputs and reviewer-approved text separately.
- Do not paraphrase, modernize, translate or grammar-correct the author's Telugu.
- A user correction can be saved as a suggestion; never globally replace matching words without context/approval.
- No LLM, React UI, fine-tuning, Redis, MinIO or Kubernetes in Phase 1.
- Do not invent benchmark numbers. Run the benchmark against real manually transcribed pages.

## Execution mode

Implement **Phase 1 only** from `04-phase-1-implementation-plan.md`.

Before writing code:

1. Inspect the current repository and installed Python/runtime versions.
2. Produce a concise implementation checklist.
3. Confirm the exact PaddleOCR/Tesseract APIs against the installed package versions.
4. Create a minimal working vertical slice: one PDF page -> PNG -> OCR -> JSON/text output.
5. Expand to batch pages and the benchmark runner only after the vertical slice succeeds.

## Phase 1 code quality

- Use type hints and docstrings for public interfaces.
- Use `pathlib.Path` for filesystem operations.
- Use structured logging; do not print book text into logs by default.
- Validate input paths and PDF page range.
- Catch errors per page and continue with remaining pages.
- Make render DPI and OCR engine configuration explicit command-line options/config values.
- Save raw engine payloads.
- Write outputs atomically (temporary file then rename).
- Add unit tests for PDF page indexing, path naming, Unicode NFC normalization and metric calculations.
- Add integration tests using a tiny legally usable fixture page.
- Keep original files and gold transcription out of Git unless redistribution is explicitly allowed.
- Generate a pinned dependency lock/manifest after the environment actually works; do not guess versions.

## Definition of Phase 1 completion

Meet every criterion in `12-acceptance-criteria.md` under the Phase 1 heading and deliver a benchmark report. If a chosen package/model cannot install or run on the target hardware, report the exact failure and propose the supported environment documented by the official vendor; do not work around it with untrusted wheels.

## What not to do

- Do not build the entire application in one giant code-generation step.
- Do not create a microservice per module.
- Do not install packages globally.
- Do not download arbitrary model weights from unofficial mirrors.
- Do not claim a model is accurate because a sample paragraph looks plausible.
- Do not synthesize gold text from OCR output.
- Do not turn the correction memory into blind find-and-replace.
- Do not use an LLM to invent or fill text that OCR could not read.

## After Phase 1

Stop and present:

1. files created/changed;
2. exact setup and run commands;
3. package and model versions;
4. sample raw results (with book content appropriately protected);
5. benchmark report;
6. known OCR failure cases;
7. a recommendation for Phase 2 based on measured evidence.

Do not begin Phase 2 until the user reviews the Phase 1 results.
