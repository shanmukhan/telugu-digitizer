# Telugu Book Digitizer — Project Specification Pack

**Project type:** Local-first Telugu printed-book digitization and OCR correction platform  
**Specification date:** 23 November 2026  
**Primary language:** Telugu (`te`)  
**Deployment:** Local/offline after dependencies and model weights are downloaded  
**Exports:** Editable-flow DOCX, page-preserving DOCX, Unicode TXT

## What this repository contains

| File | Purpose |
|---|---|
| `00-product-brief.md` | Product scope, goals, users and non-goals |
| `01-technical-architecture.md` | System design, components, data flow and deployment |
| `02-ocr-model-selection.md` | Exact OCR model choices and model constraints |
| `03-local-installation.md` | Local environment setup and verification commands |
| `04-phase-1-implementation-plan.md` | Detailed OCR proof-of-concept execution plan |
| `05-benchmark-methodology.md` | Ground-truth dataset, metrics and comparison rules |
| `06-database-design.md` | PostgreSQL schema and data-retention model |
| `07-api-contracts.md` | Proposed API surface for later application phases |
| `08-correction-memory-and-learning.md` | Human feedback, correction memory and future model training |
| `09-document-export-specification.md` | DOCX/TXT formatting and pagination rules |
| `10-ai-coding-agent-instructions.md` | Master instructions for Codex/Claude/Gemini coding agents |
| `11-architecture-decisions.md` | Explicit architectural decisions and trade-offs |
| `12-acceptance-criteria.md` | Definition of done and release gates |
| `19-ocr-calibration-and-word-learning.md` | OCR Calibration with PDF starting page, word-level learning, and safe Book Switching |

## Locked decisions

1. Printed Telugu books are the initial target. Handwriting is out of scope.
2. Telugu-only product scope in v1. Keep interfaces language-configurable, but do not build other languages now.
3. Run locally. No cloud OCR or cloud LLM is required for the product to function.
4. Deliver two DOCX modes: normal editable-flow and page-preserving. Also produce TXT.
5. Primary OCR candidate: PaddleOCR 3.x with **PP-OCRv5**, `lang="te"`, which selects `PP-OCRv5_server_det` and `te_PP-OCRv5_mobile_rec` in the current model mapping. Pin the version family explicitly: do not allow a default model selection.
6. Secondary baseline: Tesseract 5 with Telugu `tel.traineddata` from `tessdata_best`, using the LSTM engine (`--oem 1`).
7. Benchmark on manually transcribed pages before making accuracy claims or deciding the final production engine.
8. Never overwrite raw OCR output. Keep raw, AI-proposed and human-approved text as separate versions.
9. A correction is a learning record, not permission for blind global replacement.

## First working milestone

Given 20–30 representative printed-book pages (from at least three books), the Phase 1 tool must:

- render all pages at a consistent configured DPI;
- run PaddleOCR Telugu PP-OCRv5 and Tesseract Telugu on identical page images;
- save raw text, confidence values where available, text-region coordinates where available, model/engine metadata and processing time;
- compare both engines against a manually verified gold transcription for the annotated subset;
- produce a benchmark report containing CER, WER, Telugu grapheme/akshara error rate, exact-line accuracy and seconds/page;
- never alter the source PDF or raw OCR result.

Phase 1 is a command-line proof of concept. It is **not** the full web application.

## How to use these files with an AI coding agent

1. Copy this folder into the root of a new Git repository.
2. Give the agent `10-ai-coding-agent-instructions.md` and ask it to read the other specification files before coding.
3. Tell it to implement **Phase 1 only** from `04-phase-1-implementation-plan.md`.
4. Supply a small set of legally usable Telugu book pages and verified transcriptions.
5. Review benchmark output before authorizing the web UI, LLM correction or model training phases.

## Scope discipline

Do not start with microservices, Kubernetes, LLM fine-tuning, Redis, pgvector, cloud APIs or a complex React editor. The first risk to retire is Telugu OCR accuracy on the actual print material. Add application infrastructure only after the OCR benchmark works.

## Current model documentation

- [PaddleOCR installation](https://www.paddleocr.ai/latest/en/version3.x/installation.html)
- [PaddleOCR quick start and Python API](https://www.paddleocr.ai/latest/en/quick_start.html)
- [PaddleOCR multilingual PP-OCRv5 models](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html)
- [PaddleOCR model/language mapping](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html)
- [PaddlePaddle framework installation](https://www.paddleocr.ai/latest/en/version3.x/paddlepaddle_installation.html)
- [Tesseract traineddata sets](https://tesseract-ocr.github.io/tessdoc/Data-Files.html)
- [Tesseract installation](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md)
- [PyMuPDF installation](https://pymupdf.readthedocs.io/en/latest/installation.html)

Model and package support changes. Recheck the linked documentation and record exact installed package versions and model identifiers in every benchmark run.
