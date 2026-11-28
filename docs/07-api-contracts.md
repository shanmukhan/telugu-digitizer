# 07 — API Contracts (Later Application Phase)

## 1. API conventions

- Base URL: `http://127.0.0.1:8000/api/v1`
- JSON request/response unless file upload/download is explicit.
- UUIDs for persistent identifiers.
- One-based `page_number` in public APIs; preserve zero-based PDF index only internally if useful.
- Use RFC 3339 timestamps.
- Return structured errors with stable `code` and human-readable `message`.
- Bind to localhost by default.

## 2. Initial endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/books` | Upload PDF and create book record |
| `GET` | `/books` | List books |
| `GET` | `/books/{book_id}` | Book metadata and processing status |
| `GET` | `/books/{book_id}/pages` | List page metadata/status |
| `GET` | `/books/{book_id}/pages/{page_number}/image` | Serve original rendered page image |
| `POST` | `/books/{book_id}/ocr-runs` | Start OCR run with selected engine(s) |
| `GET` | `/ocr-runs/{run_id}` | Run status and progress |
| `GET` | `/ocr-runs/{run_id}/pages/{page_number}` | Page OCR output and blocks |
| `POST` | `/ocr-blocks/{block_id}/edits` | Submit human correction |
| `POST` | `/corrections/{correction_id}/approve` | Approve correction-memory entry |
| `POST` | `/corrections/{correction_id}/reject` | Reject/disable suggestion |
| `GET` | `/corrections/search` | Find correction candidates |
| `POST` | `/books/{book_id}/exports` | Create DOCX/TXT export |
| `GET` | `/exports/{export_id}` | Export status and download metadata |

## 3. Book upload

`POST /books` uses multipart form data:

- `file`: PDF bytes;
- `title`: required;
- `author`: optional;
- `publication_year`: optional;
- `orthography_profile`: optional, default `unspecified`;
- `training_consent`: boolean, default `false`.

Response:

```json
{
  "book_id": "uuid",
  "title": "Book title",
  "page_count": 120,
  "source_sha256": "hex-sha256",
  "status": "uploaded"
}
```

## 4. OCR run request

`POST /books/{book_id}/ocr-runs`:

```json
{
  "engines": ["paddle_ppocrv5_te", "tesseract_tel_best"],
  "page_range": {"start": 1, "end": 30},
  "render_dpi": 300,
  "preprocessing_profile": "none",
  "force_rerun": false
}
```

Response:

```json
{
  "ocr_run_id": "uuid",
  "status": "queued",
  "pages_total": 30
}
```

## 5. OCR block response

```json
{
  "ocr_run_id": "uuid",
  "page_number": 10,
  "engine": "paddleocr",
  "model_id": "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
  "blocks": [
    {
      "block_id": "uuid",
      "block_index": 0,
      "reading_order": 0,
      "text": "తెలుగు గుర్తించిన పాఠ్యం",
      "confidence": 0.91,
      "polygon": [[100, 120], [850, 120], [850, 175], [100, 175]]
    }
  ]
}
```

The confidence and polygon fields are nullable. Do not synthesize confidence or bounding boxes if the engine does not provide them.

## 6. Human edit request

`POST /ocr-blocks/{block_id}/edits`:

```json
{
  "edited_text": "మానవుడు ధృవీకరించిన తెలుగు పాఠ్యం",
  "action": "corrected",
  "review_note": "OCR confused a printed vowel sign",
  "add_to_correction_memory": true,
  "memory_scope": "global_suggestion"
}
```

Server responsibilities:

1. Preserve the original OCR block.
2. Insert an append-only edit event.
3. Create/update a human-approved transcript version.
4. If requested, create a correction-memory candidate with source page/context.
5. Do not silently change other occurrences in the same book or other books.

## 7. Correction search

`GET /corrections/search?incorrect_text=...&left_context=...&right_context=...&book_id=...`

Return candidates and provenance:

```json
{
  "items": [
    {
      "correction_id": "uuid",
      "incorrect_text": "OCR రూపం",
      "corrected_text": "ధృవీకరించిన రూపం",
      "scope": "global_suggestion",
      "approved_count": 3,
      "rejected_count": 0,
      "context_match": "strong",
      "source_book_count": 2
    }
  ]
}
```

`context_match` is an application assessment, not an LLM-calibrated probability.

## 8. Export request

`POST /books/{book_id}/exports`:

```json
{
  "format": "docx",
  "layout_mode": "page_preserving",
  "text_version": "human_approved",
  "font_family": "Noto Serif Telugu",
  "include_page_numbers": true,
  "include_table_of_contents": true
}
```

Allowed `layout_mode` values:

- `editable_flow`
- `page_preserving`

Allowed formats: `docx`, `txt`, and optional later `searchable_pdf`.

## 9. Error response

```json
{
  "error": {
    "code": "OCR_MODEL_NOT_AVAILABLE",
    "message": "The configured Telugu OCR model is not available locally.",
    "details": {"engine": "paddleocr", "model_id": "..."}
  }
}
```

## 10. API phase implementation constraints

- Phase 1 does not need to implement this API.
- Do not start a background job without a durable status record once the UI supports long-running OCR.
- Enforce PDF size/page limits and validate MIME type and file signature.
- Keep file paths internal; expose download endpoints rather than raw absolute paths.

## 11. OCR Calibration, Book State, and Word-Level Correction Memory Endpoints

- `GET /api/v1/books/{book_id}/calibration`: Returns book `processing_state`, calibration range (`calibration_start_page`, `calibration_page_count`, `calibration_range_end`, `book_end_page`, `skipped_front_pages_count`), remaining range, learned word rule count, recurring character confusion patterns, and auto-applied block counts.
- `POST /api/v1/books/{book_id}/calibration/start`: Validates `start_page` (1-based PDF index), `calibration_page_count`, and optional `end_page`; persists calibration config on the book and queues OCR strictly on `[start_page, start_page + calibration_page_count - 1]`.
- `POST /api/v1/books/{book_id}/calibration/complete`: Harvests approved word-level edits from the calibration batch into `book_only` correction memory and marks calibration completed.
- `POST /api/v1/books/{book_id}/calibration/process-remaining`: Harvests any pending calibration edits and starts OCR on `[calibration_range_end + 1, book_end_page]` with safe auto-application of learned corrections (`apply_calibration_corrections=true`).
- `PATCH /api/v1/books/{book_id}/state`: Updates book `processing_state` (e.g., `paused` when switching books safely).
- `GET /api/v1/corrections`: Supports `book_id`, `status_filter`, `scope_filter` (`global_suggestion` | `book_only`), `unit_type` (`word` | `char_pattern` | `phrase`), `conflict_only`, `q`, `limit`, `offset`, returning enriched items (`reliability_score`, `has_conflict`, `conflict_count`, `source_book_title`, `source_page_number`, `last_used_at`) plus `total_count`, `global_count`, `book_specific_count`, and `conflicts_count`.
- `PATCH /api/v1/corrections/{correction_id}`: Edits `corrected_text`, `left_context`, `right_context`, `correction_type`, `unit_type`, `scope`, or `status`.
- `DELETE /api/v1/corrections/{correction_id}`: Removes a correction memory record.
- `POST /api/v1/ocr-blocks/{block_id}/edits`: Accepts `reject_auto_applied_rules: true` when reverting an `auto_applied` block to restore raw OCR and increment negative evidence (`rejected_count`) on the triggering memory rule(s).
