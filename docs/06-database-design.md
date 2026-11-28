# 06 — Database Design

## 1. Persistence strategy

Use PostgreSQL for the integrated application. During Phase 1, JSON/JSONL manifests and files on disk are sufficient; do not block the OCR benchmark on database setup.

Store large PDFs, page images, crops and DOCX outputs on the local filesystem. Store metadata, OCR text, review events, correction memory and provenance in PostgreSQL. Keep a storage abstraction so local files can later be moved to another storage backend without changing domain logic.

## 2. Data principles

- Immutable source PDF and source page image.
- Immutable OCR run outputs.
- Separate machine proposals from user-approved corrections.
- Keep review events/audit history.
- A correction memory record has scope, context, provenance and state.
- Do not treat one reviewed correction as universally true for all books.
- Preserve original text and corrected text together.

## 3. Main entities

| Table | Purpose |
|---|---|
| `books` | Book-level metadata and source file identity |
| `book_pages` | One record per original PDF page |
| `ocr_runs` | One processing attempt with engine/model/config |
| `ocr_blocks` | Text blocks/lines detected in a page |
| `review_edits` | Append-only human edit/approval/rejection events |
| `correction_memory` | Reusable correction suggestions with context and scope |
| `training_samples` | Permissioned, reviewed image-text pairs for future OCR training |
| `model_registry` | Model/package versions and checksums |
| `processing_jobs` | Optional durable job status for the web application |

## 4. Proposed PostgreSQL schema

The following is an initial logical schema. Apply it through Alembic migrations and refine constraints/indexes during implementation.

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE books (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    author TEXT,
    publisher TEXT,
    publication_year INTEGER,
    language_code VARCHAR(8) NOT NULL DEFAULT 'te',
    orthography_profile VARCHAR(80) NOT NULL DEFAULT 'unspecified',
    original_filename TEXT NOT NULL,
    source_storage_key TEXT NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    page_count INTEGER NOT NULL CHECK (page_count > 0),
    rights_status VARCHAR(30) NOT NULL DEFAULT 'unknown',
    training_consent BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_books_source_sha256 ON books(source_sha256);

CREATE TABLE book_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    page_kind VARCHAR(20) NOT NULL DEFAULT 'scanned_image',
    image_storage_key TEXT,
    image_sha256 CHAR(64),
    width_px INTEGER,
    height_px INTEGER,
    render_dpi INTEGER,
    review_status VARCHAR(20) NOT NULL DEFAULT 'not_started',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(book_id, page_number)
);

CREATE TABLE model_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engine_name VARCHAR(80) NOT NULL,
    engine_version VARCHAR(80),
    model_family VARCHAR(80),
    model_id VARCHAR(160) NOT NULL,
    model_sha256 CHAR(64),
    runtime_name VARCHAR(80),
    runtime_version VARCHAR(80),
    device VARCHAR(40),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ocr_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    model_registry_id UUID REFERENCES model_registry(id),
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ocr_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ocr_run_id UUID NOT NULL REFERENCES ocr_runs(id) ON DELETE CASCADE,
    book_page_id UUID NOT NULL REFERENCES book_pages(id) ON DELETE CASCADE,
    block_index INTEGER NOT NULL,
    block_type VARCHAR(30) NOT NULL DEFAULT 'text_line',
    raw_text TEXT NOT NULL,
    normalized_text TEXT,
    confidence REAL,
    polygon JSONB,
    reading_order INTEGER,
    raw_engine_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(ocr_run_id, book_page_id, block_index)
);
CREATE INDEX ix_ocr_blocks_page ON ocr_blocks(book_page_id);

CREATE TABLE review_edits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ocr_block_id UUID NOT NULL REFERENCES ocr_blocks(id) ON DELETE CASCADE,
    previous_text TEXT NOT NULL,
    edited_text TEXT NOT NULL,
    action VARCHAR(20) NOT NULL,
    reviewer_id TEXT,
    review_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_review_edits_block ON review_edits(ocr_block_id, created_at);

CREATE TABLE correction_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    language_code VARCHAR(8) NOT NULL DEFAULT 'te',
    incorrect_text TEXT NOT NULL,
    corrected_text TEXT NOT NULL,
    left_context TEXT,
    right_context TEXT,
    correction_type VARCHAR(50),
    scope VARCHAR(20) NOT NULL DEFAULT 'global_suggestion',
    book_id UUID REFERENCES books(id) ON DELETE SET NULL,
    source_ocr_block_id UUID REFERENCES ocr_blocks(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    approved_count INTEGER NOT NULL DEFAULT 1 CHECK (approved_count >= 0),
    rejected_count INTEGER NOT NULL DEFAULT 0 CHECK (rejected_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_correction_memory_incorrect
    ON correction_memory(language_code, incorrect_text, status);

CREATE TABLE training_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    book_page_id UUID NOT NULL REFERENCES book_pages(id) ON DELETE CASCADE,
    image_crop_storage_key TEXT NOT NULL,
    image_crop_sha256 CHAR(64) NOT NULL,
    ocr_text TEXT,
    verified_text TEXT NOT NULL,
    annotation_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewer_id TEXT,
    allowed_for_training BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    job_type VARCHAR(40) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    error_details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
```

## 5. Text version model

The schema above stores OCR output and human edits separately. For a complete book text, add a versioned page/document transcript layer when the review UI is implemented:

- `document_text_versions`: book ID, version number, origin (`raw_ocr`, `ai_proposal`, `human_approved`), status, created time.
- `document_text_blocks`: version ID, page ID, block ID, final text, reading order, paragraph/heading type.

This is preferable to a single mutable `final_text` column because users need to compare and roll back versions.

## 6. Correction memory rules

- `scope='book_only'`: suggestion applies only within one book.
- `scope='global_suggestion'`: reusable candidate across books, but must pass context checks and remain a suggestion.
- `status='active'|'disabled'|'superseded'|'rejected'`.
- Increase `approved_count` only after a user accepts the correction in another context or confirms it again.
- Keep rejection events; do not erase negative evidence.
- Context may be stored as left/right token windows or a short sentence span. Do not rely on the incorrect word alone.

## 7. Indexing and normalization

- Store raw text exactly as emitted by OCR.
- Store NFC-normalized text in a separate field for search/metrics.
- Index `incorrect_text` for exact correction-memory lookup.
- Use trigram indexes only if fuzzy correction lookup is later measured to help.
- Do not add vector search in the first release.

## 8. Data protection and retention

- Training use is opt-in and separate from processing permission.
- A book without training consent must not be included in training datasets.
- Provide deletion for source PDF, page images, OCR artifacts and associated records.
- Keep audit metadata only where legally and operationally appropriate.
- Back up database and local storage together so references do not become orphaned.

## 9. Calibration & Word-Level Memory Extensions (Migration `0005_calibration_word_memory`)

- **`books`**: added `processing_state` (`uploaded`, `calibration_pending`, `calibration_processing`, `calibration_review`, `calibration_completed`, `remaining_processing`, `review_in_progress`, `completed`, `paused`), `calibration_start_page`, `calibration_page_count`, `calibration_end_page`, and `calibration_completed_at`.
- **`correction_memory`**: added `normalized_incorrect` (indexed `(language_code, normalized_incorrect, status)`), `unit_type` (`word` | `char_pattern` | `phrase`), `source_page_number`, and `last_used_at`.
- **`review_edits`**: added `applied_rules` (`JSONB`, nullable) to record structured provenance when calibration/memory corrections are auto-applied (`action='auto_applied'`) without overwriting `ocr_blocks.raw_text`.
