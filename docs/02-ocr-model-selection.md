# 02 — OCR Model Selection and Exact Configuration

## 1. Model decision for the first benchmark

### Primary: PaddleOCR 3.x — PP-OCRv5 Telugu

Use:

- Pipeline: PaddleOCR general OCR pipeline (PaddlePaddle inference engine)
- OCR version: `PP-OCRv5`
- Language code: `te`
- Detection model selected by the current PP-OCRv5 mapping: `PP-OCRv5_server_det`
- Recognition model: `te_PP-OCRv5_mobile_rec`
- Device: `cpu` for the initial reproducible benchmark

Python initialization:

```python
from paddleocr import PaddleOCR

telugu_ocr = PaddleOCR(
    lang="te",
    ocr_version="PP-OCRv5",
    device="cpu",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)

results = telugu_ocr.predict("path/to/page-0001.png")
for result in results:
    result.print()
    result.save_to_json(save_path="artifacts/paddle/page-0001")
```

The explicit `ocr_version="PP-OCRv5"` matters. Current PaddleOCR documentation lists Telugu under PP-OCRv5, while its PP-OCRv6 supported-language table does not list Telugu. Do not instantiate `PaddleOCR()` with defaults and assume Telugu has been selected.

Current model mapping source: [PaddleOCR OCR pipeline documentation](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html). PP-OCRv5 multilingual model source: [PP-OCRv5 multilingual recognition](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html).

### Secondary baseline: Tesseract 5 — Telugu `tessdata_best`

Use:

- Language: `tel` (Tesseract's code; not PaddleOCR's `te`)
- Model file: `tel.traineddata` from `tesseract-ocr/tessdata_best`
- OCR engine mode: `--oem 1` (LSTM)
- Initial page segmentation: `--psm 6` for a reasonably uniform text block; test `--psm 4` for multi-column text and `--psm 3` as a general page mode if needed.

Example:

```bash
tesseract page-0001.png stdout \
  -l tel --oem 1 --psm 6 \
  --tessdata-dir ./models/tesseract/tessdata
```

`tessdata_best` is slower than `tessdata_fast` but is a stronger accuracy-oriented baseline and is the official set intended for best recognition results and possible retraining. `tessdata_best` and `tessdata_fast` require the LSTM engine (`--oem 1`). Source: [Tesseract data files](https://tesseract-ocr.github.io/tessdoc/Data-Files.html).

## 2. Model alternatives — not Phase 1 dependencies

| Candidate | Decision | Reason |
|---|---|---|
| PaddleOCR PP-OCRv5 Telugu | **Primary benchmark model** | Explicit Telugu model mapping |
| Tesseract 5 `tel` from `tessdata_best` | **Secondary benchmark** | Independent baseline, local/offline |
| Tesseract `tessdata_fast` `tel` | Optional speed baseline | Useful only if speed becomes a priority |
| PP-OCRv3 Telugu | Optional legacy comparator | Use only if v5 fails on the selected print types; freeze package/model versions |
| Research-specific Telugu OCR projects | Research candidate | Audit code, model download, license, reproducibility and maintenance before use |
| LLM/VLM OCR | Not selected for initial OCR | Adds compute and hallucination risks; compare later against gold data |

## 3. Critical distinction: detection versus recognition

A full page pipeline uses:

1. Text detection: locate text areas on the page.
2. Text recognition: read the cropped text regions.

Paddle's Telugu recognition model is `te_PP-OCRv5_mobile_rec`; detection is handled by the selected detection model. Poor page-level results can be caused by layout/detection/reading order even when character recognition on a clean line crop is good. Benchmark both full-page OCR and a small line-crop diagnostic set if results are poor.

## 4. Page segmentation considerations for Telugu books

Test each OCR engine using identical page rasters and record page layout class:

- single-column prose;
- two-column prose;
- headings plus body text;
- footnotes or marginal notes;
- page number/header/footer;
- mixed Telugu and Arabic numerals/Latin text.

Do not flatten multi-column pages into one text string without retaining source coordinates. Reading order errors are different from character errors and should be reported separately.

## 5. Confidence policy

OCR confidence is model-specific. A Paddle score of 0.90 and a Tesseract confidence of 90 are not directly comparable and should not be treated as calibrated probabilities.

Use confidence only as a within-engine prioritization signal until calibration is measured against human labels. A review queue should also consider:

- disagreement between engines;
- unusual/unknown words;
- low image quality;
- text-block detection anomalies;
- OCR output with suspiciously short or empty content.

## 6. Model provenance required per run

Store:

- library name and package version;
- inference framework and version;
- model family/version;
- exact detection and recognition model names;
- model file checksum where available;
- CPU/GPU device;
- command/configuration;
- page render DPI and preprocessing configuration;
- timestamp and runtime.

## 7. Telugu correctness considerations

- Normalize strings to Unicode NFC for canonical comparisons, but preserve the exact raw output too.
- Never remove vowel signs, viramas, anusvara/visarga or other combining marks as a cleanup shortcut.
- Do not assume whitespace tokenization reflects Telugu word boundaries perfectly in all source texts.
- Use grapheme-cluster/akshara-aware evaluation in addition to code-point CER.
- Preserve old spelling, regional expressions, Sanskrit-derived terms and proper nouns.

## 8. Official references

- [PaddleOCR supported languages and model mapping](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html)
- [PP-OCRv5 multilingual model documentation](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html)
- [PaddleOCR Python quick start](https://www.paddleocr.ai/latest/en/quick_start.html)
- [Tesseract traineddata comparison](https://tesseract-ocr.github.io/tessdoc/Data-Files.html)
