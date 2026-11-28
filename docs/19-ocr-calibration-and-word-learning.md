# 19 — OCR Calibration, Word-Level Correction Memory, and Safe Book Switching

This guide documents the **OCR Calibration Phase**, **PDF Starting Page selection**, **Word-Level Correction Memory**, and **Non-Destructive Book Switching** workflows introduced to dramatically reduce manual proofreading effort on printed Telugu books.

---

## 1. OCR Calibration Workflow

Because a printed Telugu book shares a consistent typeface, scan quality, and spelling convention across hundreds of pages, processing all pages before learning from early corrections forces reviewers to fix the same recurring OCR mistakes repeatedly.

### End-to-End Flow

1. **Upload PDF**: Upload the book PDF; the app extracts total PDF page count and classifies scanned vs. digital pages.
2. **Configure OCR Calibration Settings**:
   - **PDF Starting Page**: Select the 1-based **PDF page index** where actual Telugu body text starts (skipping cover, title page, publisher info, dedication, illustrations, or blank pages).
     - *Important distinction*: **PDF Starting Page** refers to the physical page index in the PDF file, **not** the printed page number inside the book (e.g., PDF page 12 may carry printed page number `1`).
     - A live **PDF Page Thumbnail Preview** appears beside the selector so you can visually verify where body text starts without guessing.
   - **Calibration Pages**: Pick `5`, `6`, `7`, `8`, `9`, `10`, or any valid custom count (default `5`).
   - **Ending PDF Page (optional)**: Defaults to the final page of the PDF.
   - A visual range bar clearly shows:
     - Skipped front matter (`PDF 1–11`, untouched unless processed explicitly later)
     - Selected calibration range (`PDF 12–19`)
     - Remaining book pages (`PDF 20–250`)
3. **Run Calibration OCR** (`POST /api/v1/books/{book_id}/calibration/start`):
   - Processes **only** the calibration pages (`start_page .. start_page + calibration_page_count - 1`).
   - Jumps the review workspace directly to `start_page`.
4. **Review & Correct Calibration Pages**:
   - Proofread the calibration batch and save/approve fixes.
   - Every edit extracts clean **word-level** rules into `correction_memory`.
5. **Apply Calibration & Process Remaining Pages** (`POST /api/v1/books/{book_id}/calibration/process-remaining`):
   - Consolidates all approved calibration edits into book-specific word rules (`scope="book_only"`) and extracts recurring character/diacritic confusion patterns observed across >= 2 distinct calibrated words.
   - Runs OCR strictly on the remaining pages (`calibration_range_end + 1 .. book_end_page`) — never reprocessing calibration pages or untouched front-matter pages.
   - As each remaining page completes OCR, learned rules are safely applied as append-only `ReviewEdit(action="auto_applied")` rows while `ocr_blocks.raw_text` remains **100% immutable**.
6. **Review Auto-Applied Fixes**:
   - Auto-applied lines are flagged with `⚡ Auto-Applied (Calibration)` showing exact word diffs (`incorrect → corrected`).
   - Reviewers can **✓ Approve Fix** (reinforcing positive evidence), **↩ Revert** to raw OCR, or **✕ Revert & Reject Rule** (restoring raw OCR and recording negative evidence on the triggering rule).

---

## 2. Book Processing States

Each book tracks an explicit lifecycle (`books.processing_state`, combined with live OCR run telemetry):

| State | Meaning |
|---|---|
| `uploaded` | PDF imported; awaiting calibration or OCR configuration |
| `calibration_pending` | Calibration range configured; OCR not yet started |
| `calibration_processing` | Calibration batch OCR is actively queued/running |
| `calibration_review` | Calibration OCR finished; awaiting human review & approval |
| `calibration_completed` | Calibration corrections harvested; ready to process remaining pages |
| `remaining_processing` | Remaining pages OCR is actively running with calibration learning |
| `review_in_progress` | Remaining pages extracted; human proofreading underway |
| `completed` | All target pages approved |
| `paused` | User switched to another book mid-work; all OCR results and edits preserved |

---

## 3. Word-Level Correction Memory & Safety Guards

### Word-Level Extraction (No Sentence-to-Sentence Replacement)

`extract_word_level_corrections()` splits adjacent edited words inside a line into individual **word-to-word** rules rather than storing multi-word phrases or entire sentences:

- Example: Fixing `మలయకూట పబ్లీషన్ హ్రౌదరాబాదు` → `మలయకూట పబ్లికేషన్స్ హైదరాబాదు` extracts TWO reusable word rules:
  1. `పబ్లీషన్ → పబ్లికేషన్స్` (unit: `word`)
  2. `హ్రౌదరాబాదు → హైదరాబాదు` (unit: `word`)
- Shared leading or trailing punctuation is stripped independently so `(పగమబాగం- → ప్రథమభాగం-` stores `(పగమబాగం → ప్రథమభాగం`.
- Multi-word `phrase` units are reserved for genuine word-boundary merges/splits (e.g., `పుస్త కం → పుస్తకం`).
- Surrounding tokens are stored as `left_context` / `right_context` supporting evidence — never as the replacement target itself.

### Auto-Application Safety Rules

Before `apply_learned_corrections_to_page_blocks()` auto-applies a rule on remaining pages:

1. **Raw OCR Immutability**: `ocr_blocks.raw_text` is never modified; auto-applied text is stored via append-only `ReviewEdit(action="auto_applied")` with `applied_rules` provenance.
2. **Valid Word Guard**: Known valid Telugu dictionary words are **not** blindly replaced unless supported by a strong surrounding-context match or repeated book-specific confirmation (`approved_count >= 2`, `rejected_count == 0`).
3. **Conflict Guard**: When multiple active corrections exist for the same OCR word, auto-application is **skipped** unless one candidate has a strictly stronger `strong` surrounding-word context match.
4. **Scope Precedence & Evidence Threshold**:
   - Book-specific (`book_only`) rules take precedence over `global_suggestion` rules within the same book.
   - Cross-book `global_suggestion` rules require `approved_count >= 2` and `rejected_count == 0` before auto-applying.
5. **Full Auditability & Rejection Learning**: Reverting an auto-applied correction with **Revert & Reject Rule** increments `rejected_count` on the rule and stops it from auto-applying on future pages.

---

## 4. Non-Destructive Book Switching

A visible **⇄ Switch Book** button in the top navigation bar (and the book switcher menu) lets users pause their current book and move to another book or upload a new PDF:

- **When no unfinished work exists**: switches directly.
- **When unfinished work exists** (unsaved line drafts, running OCR, or unapproved pages):
  - Displays a native confirmation `<dialog>` listing exactly what is in progress.
  - Clearly states that **nothing will be deleted** — the current book is paused (`processing_state = "paused"`) with all OCR results, calibration settings, and saved corrections preserved.
  - Offers **Save Drafts & Switch Book** when unsaved page edits exist so zero edits are lost.
  - Safely pauses any active OCR job (saving completed pages as `partial`) so the user can return and resume anytime.

---

## 5. Legacy Phrase Cleanup, Batch Re-Apply, and Visual Fine-Tuning Export

1. **Legacy Multi-Word Cleanup (`POST /api/v1/corrections/normalize-legacy`)**:
   - Available via **✨ Split Legacy Phrases** in the Correction Memory panel.
   - Splits legacy multi-word edits into individual reusable word-level rules, strips shared edge punctuation, merges duplicates, and preserves compact word-boundary merges/splits (`unit_type="phrase"`).
2. **Batch Re-Apply on Unreviewed Pages (`POST /api/v1/books/{book_id}/calibration/reapply-unreviewed`)**:
   - Available in the OCR status bar and OCR drawer (**✨ Re-apply Rules to Unreviewed**).
   - Safely applies newly learned rules across already-OCR'd pages whose `review_status != "approved"`, skipping any block with human edits (`corrected`, `approved`, `ignored`, `reverted`) and never modifying `raw_text`.
3. **Visual OCR Fine-Tuning Dataset Bundle (`POST /api/v1/books/{book_id}/training-consent`, `GET /api/v1/training/summary`, `POST /api/v1/training/export`)**:
   - Retroactively harvests verified line image crops from human-corrected/approved blocks when training consent is enabled on a book.
   - Exports a deduplicated, page-split ZIP bundle ready for both **PaddleOCR PP-OCRv5** (`paddleocr/images/`, `train_list.txt`, `val_list.txt`, `rec_te_ppocrv5_finetune.yml`) and **Tesseract 5 `tesstrain`** (`tesseract/ground-truth/*.png` + `*.gt.txt`), plus CLI script `scripts/export_training_dataset.py`.
