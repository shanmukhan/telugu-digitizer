# 12 — Acceptance Criteria and Definition of Done

## Phase 1 — OCR proof of concept

### Environment

- [ ] Isolated Python virtual environment created.
- [ ] Python, PaddlePaddle, PaddleOCR and Tesseract versions recorded.
- [ ] PaddleOCR Telugu PP-OCRv5 model selection explicitly verified.
- [ ] Tesseract `tel.traineddata` source and SHA-256 recorded.
- [ ] Cold start/model download separated from warm inference timings.

### Dataset and rendering

- [ ] 20–30 pages selected from at least three printed Telugu books, subject to available permissions.
- [ ] Source PDF file hashes recorded.
- [ ] Page manifest contains every selected page.
- [ ] Selected scanned pages rendered at configured 300 DPI.
- [ ] Rendered image dimensions and hashes recorded.
- [ ] No page silently omitted.
- [ ] Gold transcription subset manually checked.
- [ ] Annotation policy documented.

### OCR

- [ ] PaddleOCR run uses `lang="te"` and `ocr_version="PP-OCRv5"`.
- [ ] Tesseract run uses `-l tel --oem 1` with the selected traineddata file.
- [ ] Both engines receive identical page images.
- [ ] Raw text and native engine payloads saved.
- [ ] Confidence and bounding boxes saved when available; null otherwise.
- [ ] Engine/model/config metadata saved.
- [ ] Per-page failures are captured and do not terminate the full run.

### Evaluation

- [ ] CER calculated.
- [ ] NFC-normalized CER calculated.
- [ ] WER calculated.
- [ ] Grapheme/akshara proxy error rate calculated.
- [ ] Exact-line accuracy calculated.
- [ ] Seconds/page and pages/minute reported.
- [ ] Results grouped by book and page/layout quality.
- [ ] Error taxonomy applied to representative failures.
- [ ] No test book was used to tune the final configuration.
- [ ] No unsupported accuracy claims are made.

### Phase 1 deliverable

- [ ] Reproducible CLI scripts.
- [ ] Setup/run instructions.
- [ ] Machine-readable raw outputs.
- [ ] Benchmark CSV/JSON.
- [ ] Human-readable Markdown benchmark report.
- [ ] Known limitations and recommendation for Phase 2.

## Phase 2 — PDF processing backend

- [ ] Upload and page classification work locally.
- [ ] Digital-text and scanned-page paths are distinct.
- [ ] OCR output retains page/block provenance and coordinates.
- [ ] Processing is restartable and idempotent.

## Phase 3 — Human review UI

- [ ] Source page and OCR text are displayed together.
- [ ] Low-confidence/disagreement regions are visibly flagged.
- [ ] Telugu Unicode edits save reliably.
- [ ] Original OCR output is not overwritten.
- [ ] Undo/redo and page review status work.

## Phase 4 — Correction memory

- [ ] User chooses book-only or global-suggestion scope.
- [ ] Context and provenance stored.
- [ ] Accepted and rejected suggestions are recorded.
- [ ] Conflicts can coexist and be reviewed.
- [ ] Global correction does not silently change text.

## Phase 5 — Export

- [ ] Editable-flow DOCX generated.
- [ ] Page-preserving DOCX generated with source page boundaries.
- [ ] TXT generated as UTF-8.
- [ ] Telugu font rendering checked in Word/LibreOffice.
- [ ] Export text is traceable to a selected transcript version.

## Release-blocking defects

- Telugu combining marks dropped or corrupted.
- Pages or text blocks silently omitted.
- Output cannot be traced to original pages.
- Human corrections overwrite raw OCR output.
- Model selection silently falls back to a non-Telugu model.
- Private documents are included in training data without consent.
