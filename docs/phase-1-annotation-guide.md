# Phase 1 Dataset Manifest & Gold Annotation Guide

Follow these rules when collecting the 20–30 printed Telugu pages across at least three books (`docs/04-phase-1-implementation-plan.md`, `docs/05-benchmark-methodology.md`):

## 1. Book-level splits (avoid data leakage)

Split by whole **book**, never by random lines or pages from the same book:

- `dev`: Book A (tuning / inspecting OCR behavior and `--psm` modes)
- `val`: Book B (validation)
- `test`: Book C (held-out evaluation — do not tune configs on this book)

## 2. Page metadata fields in manifest JSON

After running `scripts/render_pdf.py`, each page entry supports:

- `split`: `"dev"`, `"val"`, or `"test"`
- `page_quality`: `"clean"`, `"degraded"`, `"skewed"`, etc.
- `layout_type`: `"single_column"`, `"two_column"`, `"headings_body"`, `"footnotes"`, `"mixed_latin_digits"`
- `gold_path`: relative path to UTF-8 gold transcription text file (e.g. `data/gold/v1/book_a/page-0001.txt`), or `null` for unscored throughput pages.

See `data/manifests/manifest.example.json` for a complete sanitized template.

## 3. Gold transcription rules

1. Transcribe strictly from the **original page image** (`data/pages/<book_id>/page-NNNN.png`), never by copying and editing OCR output.
2. Preserve exact printed wording, older spellings, Sanskrit loanwords, punctuation, numerals, and paragraph/line breaks.
3. Mark genuinely illegible spans consistently as `[UNREADABLE]`.
4. Document consistently whether running headers/footers and page numbers are included (default: include all visibly printed text on the page in reading order).
5. Save files as UTF-8 plain text (`.txt`). Do not worry if keyboard input produces canonically decomposed forms—evaluation reports **both** raw code-point CER and NFC-normalized CER while keeping raw text untouched.
6. Have a second reviewer verify at least a subset of annotated pages before treating results as gold.
7. Keep copyrighted source PDFs, page images, and book gold transcriptions out of Git (`data/` is gitignored).
