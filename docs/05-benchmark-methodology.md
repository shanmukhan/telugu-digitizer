# 05 — OCR Benchmark Methodology

## 1. Purpose

Choose the best OCR configuration for the target printed Telugu books, not the model with the best generic benchmark score or the cleanest-looking demo.

All candidate engines must receive the same rasterized page images. The scoring text must be compared against a manually verified ground-truth transcription.

## 2. Gold dataset design

- Start with 20–30 pages across at least three books.
- Fully transcribe 10–20 representative pages for the first report.
- Keep at least one book as a held-out test group when possible.
- Record book, edition/year if known, source resolution, page quality, layout type and font-size observations.
- If multiple reviewers disagree, adjudicate before marking text as gold.
- Keep original scans immutable and record SHA-256 hashes.

### Annotation policy

Decide and document:

- whether page numbers are included;
- whether headers/footers are included;
- how printed line-break hyphenation is represented;
- whether line breaks are retained or joined within paragraphs;
- how unreadable characters are represented;
- how punctuation and numerals are treated;
- whether mixed Latin text is part of the score.

The same policy must be applied to gold and OCR output.

## 3. Metrics

### 3.1 Character Error Rate (CER)

`CER = (Substitutions + Deletions + Insertions) / Number of reference characters`

Compute a raw/code-point CER and an NFC-normalized CER. Report both. Unicode normalization is for comparison only; do not discard raw source strings.

### 3.2 Word Error Rate (WER)

`WER = (Word substitutions + Word deletions + Word insertions) / Number of reference words`

For the first version, tokenize using whitespace after the agreed normalization policy. State clearly that this is a practical token-based metric and may not represent every Telugu word-boundary convention perfectly.

### 3.3 Telugu grapheme/akshara error rate

Use Unicode extended grapheme clusters as a reproducible first approximation for Telugu orthographic units. Python's third-party `regex` module supports `\X` matching.

`Grapheme Error Rate = grapheme-level edit distance / reference grapheme count`

This is an approximation, not a linguistically perfect akshara segmenter. Keep the metric definition stable so model versions can be compared fairly. If a linguist-approved Telugu akshara tokenizer becomes available, add it as a separately versioned metric.

### 3.4 Exact-line accuracy

`Exact-line accuracy = number of exactly matching reference lines / number of reference lines`

Score after NFC normalization and the agreed whitespace policy. This is useful because a single character difference makes a line fail, which is meaningful for proofreading.

### 3.5 Throughput

Report:

- wall-clock seconds per page;
- pages per minute;
- cold-start time separately from warm inference;
- device/CPU/GPU details;
- image dimensions and DPI.

Do not include model download time in warm per-page inference throughput. Report it separately.

### 3.6 Layout/reading-order errors

Report these separately from recognition character errors:

- missing text block;
- duplicate text block;
- incorrect reading order;
- text from a neighboring column mixed into a line;
- page number/header inserted into body text;
- body text incorrectly omitted.

## 4. Normalization rules

- Use Unicode NFC on copies used for normalized scoring.
- Do not strip Telugu combining marks.
- Do not remove punctuation from the primary score.
- Do not silently change numerals or spelling.
- Use an optional secondary whitespace-normalized score, but preserve the strict score.
- Record any text exclusions (for example, unreadable regions) consistently.

## 5. Comparison protocol

1. Render selected source pages once at the configured DPI.
2. Save the rendered image and its SHA-256 hash.
3. Feed the same image file to PaddleOCR and Tesseract.
4. Freeze OCR parameters before scoring the held-out book.
5. Capture package versions, model names/checksums, page preprocessing settings and machine configuration.
6. Run each engine with a warm-up page, then process the benchmark set.
7. If measuring speed, repeat at least twice and report median seconds/page; do not hide variance.
8. Calculate metrics globally and per book/page-quality group.
9. Inspect the worst 20 pages/lines and categorize errors.
10. Save raw engine results, metric output and report.

## 6. Avoid data leakage

Do not tune preprocessing or model settings using the held-out test book. Split by whole book wherever possible. Randomly splitting adjacent lines from the same page can leak print/font and scan characteristics into both tuning and test sets.

## 7. Error taxonomy

Use labels such as:

- `glyph_confusion` — similar printed glyph read as another glyph;
- `vowel_sign` — vowel sign or dependent vowel mark wrong/missing;
- `conjunct_or_virama` — conjunct/virama sequence error;
- `punctuation`;
- `numeral`;
- `word_boundary`;
- `line_or_block_detection`;
- `reading_order`;
- `omission`;
- `insertion`;
- `scan_quality`;
- `unknown_or_rare_word`.

This error taxonomy will guide whether the next improvement belongs in image preprocessing, detection, recognition, text correction or document layout reconstruction.

## 8. Benchmark report template

```text
Project / dataset version:
Run date:
Host OS / CPU / RAM:
Python version:
PaddleOCR version:
PaddlePaddle version:
Tesseract version:
Paddle model IDs:
Tesseract traineddata SHA256:
Rendering DPI:
Preprocessing config:

Engine | CER | NFC CER | WER | Grapheme ER | Exact-line % | sec/page

Results by book:
Results by page quality:
Results by layout type:
Failed pages:
Top error categories:
Examples of worst errors:
Recommendation:
Known limitations:
```

## 9. Decision rule

Choose an OCR engine/configuration based on a combination of:

- lower held-out CER and grapheme error rate;
- lower WER and higher exact-line accuracy;
- fewer omissions and reading-order failures;
- acceptable processing time;
- stability across different books and page qualities.

Do not select an engine solely because it has higher average confidence or is faster. If one engine performs better on clean pages and another on degraded pages, retain a routing/ensemble experiment as a later phase rather than merging the output blindly.
