# 00 — Product Brief

## 1. Product statement

Build a local Telugu book digitization application that turns scanned or image-based printed Telugu PDFs into editable Unicode Telugu documents. It must preserve the original author's words, allow users to inspect and correct OCR output, and retain approved corrections for future suggestions.

The product is an OCR and proofreading tool, not a grammar-rewriting or translation system.

## 2. Target user and main workflow

A user has a printed Telugu book scanned into a PDF.

1. Import the PDF and enter book metadata.
2. Identify text-based versus scanned pages.
3. Render scanned pages to images.
4. Run Telugu OCR.
5. Review text against the source page.
6. Correct recognition mistakes and approve the final text.
7. Export an editable-flow DOCX, page-preserving DOCX and/or TXT.
8. Optionally contribute approved, permissioned examples to the correction memory and future training dataset.

## 3. Initial scope

### In scope

- Printed Telugu books, including modern print and modestly degraded scans.
- Single-language Telugu content in v1; preserve digits and common Latin text if present.
- Scanned PDFs and digitally generated PDFs.
- Page-level processing and traceability.
- OCR engine comparison.
- Telugu Unicode output.
- Human proofreading and audit trail.
- Reusable correction memory with contextual matching.
- Two DOCX modes and TXT export.
- Local storage and local inference.

### Out of scope for v1

- Handwritten Telugu recognition.
- Other Indian languages.
- Automatic literary editing, grammar modernization or translation.
- Guaranteed pixel-perfect editable Word layout.
- Multi-user cloud SaaS, authentication federation or external integrations.
- Fine-tuning OCR on every user correction.
- Automatic global replacement of words from one unverified correction.

## 4. Product principles

1. **Source fidelity:** Preserve the author's wording, spelling conventions and punctuation unless a human reviewer explicitly corrects an OCR error.
2. **Traceability:** Every output block must be traceable to a source page and, where possible, source coordinates.
3. **Non-destructive processing:** Raw OCR, machine proposals and human-approved text are separate records.
4. **Human authority:** A human correction is authoritative for that reviewed instance. Reuse in another book is a suggestion subject to context.
5. **Offline-first:** OCR, review, correction memory and exports must work without remote AI services.
6. **Measurable quality:** Engine/model decisions are made using a fixed gold dataset and repeatable metrics.
7. **Reversible learning:** Corrections can be disabled, superseded or rolled back.

## 5. Success measures

### Phase 1

- Process the agreed sample set without losing pages.
- Run both selected OCR engines against identical page rasters.
- Save machine-readable results and engine metadata.
- Produce a reproducible benchmark report.
- Quantify accuracy by book and page quality category.

### Product release

- Reviewers can correct each OCR block and see the exact source region.
- Corrected text survives application restart.
- Both DOCX modes and TXT output contain Telugu Unicode correctly.
- Every suggested correction has provenance and can be accepted/rejected.
- No cloud dependency is required for core workflows.

## 6. Assumptions to validate

- Most input PDFs are scans of printed pages rather than born-digital PDFs.
- Page images are sufficiently legible for machine OCR.
- The user can obtain rights or permission to digitize and retain book contents.
- Telugu print fonts and orthographic conventions vary; the app must retain book-specific profiles.
- OCR confidence scores are not calibrated probabilities and cannot alone determine correctness.
