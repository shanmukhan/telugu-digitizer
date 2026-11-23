# 11 — Architecture Decision Records

## ADR-001: Printed Telugu only in v1

**Decision:** Initial product supports printed Telugu, not handwriting or other scripts.  
**Reason:** Keeps OCR model selection, evaluation data and correction logic focused.  
**Consequence:** Interfaces may carry a language code, but language expansion is not part of v1 acceptance.

## ADR-002: PaddleOCR PP-OCRv5 Telugu as primary candidate

**Decision:** Instantiate PaddleOCR with `lang="te"` and `ocr_version="PP-OCRv5"`.  
**Reason:** Current PaddleOCR docs map Telugu to `te_PP-OCRv5_mobile_rec`; PP-OCRv6's listed supported languages do not include Telugu.  
**Consequence:** The code and model configuration must explicitly select PP-OCRv5. Package/model versions must be recorded.

## ADR-003: Tesseract `tessdata_best` Telugu as independent baseline

**Decision:** Run Tesseract 5 using the Telugu model from `tessdata_best`, `--oem 1`, and tested page segmentation modes.  
**Reason:** It provides a local offline comparison engine with an independent architecture.  
**Consequence:** Tesseract results are benchmarked separately; confidence values are not comparable to Paddle's.

## ADR-004: Local-first, CPU-first development

**Decision:** First benchmark on a reproducible Ubuntu x86_64 CPU environment.  
**Reason:** Avoids GPU driver/CUDA setup as an initial blocker and makes results easier to reproduce.  
**Consequence:** GPU can be enabled later. Native Apple Silicon PaddlePaddle wheel support must be checked rather than assumed; Tesseract remains a local Mac baseline.

## ADR-005: Modular monolith

**Decision:** Use one Python backend with internal modules and a replaceable OCRProvider interface.  
**Reason:** A personal/local product does not justify microservices initially.  
**Consequence:** Module boundaries remain explicit so processing, correction and export can be separated later if scale requires it.

## ADR-006: PostgreSQL plus local filesystem

**Decision:** Store relational metadata and text in PostgreSQL; store PDFs, page images and exports in local filesystem storage.  
**Reason:** Simpler local deployment and easier backup than operating object storage in the first release.  
**Consequence:** Use storage keys and an abstraction rather than embedding absolute paths throughout the database.

## ADR-007: Human correction memory before model fine-tuning

**Decision:** Store approved corrections and use them as contextual suggestions before training any OCR model.  
**Reason:** Corrections become immediately reusable without expensive retraining and without destabilizing the recognizer.  
**Consequence:** Preserve image-text pairs for future training, but require consent and a separate holdout test set.

## ADR-008: No automatic global replacement in early releases

**Decision:** Correction memory proposes changes; humans approve.  
**Reason:** The same string may represent different words in different contexts, particularly with names and old spellings.  
**Consequence:** False corrections are measured as a first-class quality risk.

## ADR-009: Two DOCX layout modes

**Decision:** Deliver editable-flow and page-preserving DOCX.  
**Reason:** Users have different needs: convenient editing versus original source-page boundaries.  
**Consequence:** Page-preserving mode does not promise exact glyph placement because Word reflows editable text. Exact facsimile mode, if required, is a separate future feature.

## ADR-010: Phase 1 is a CLI benchmark, not a web app

**Decision:** Complete the OCR proof of concept and benchmark before building React/ FastAPI review screens.  
**Reason:** OCR accuracy on the real source material is the highest technical uncertainty.  
**Consequence:** No React UI, Redis/Celery, MinIO, LLM or pgvector is required for Phase 1.
