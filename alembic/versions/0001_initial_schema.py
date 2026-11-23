"""Initial PostgreSQL schema aligned with docs/06-database-design.md.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

    op.create_table(
        "books",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("publisher", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("language_code", sa.String(length=8), nullable=False, server_default="te"),
        sa.Column("orthography_profile", sa.String(length=80), nullable=False, server_default="unspecified"),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("source_storage_key", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("rights_status", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("training_consent", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("page_count > 0", name="ck_books_page_count_positive"),
    )
    op.create_index("ix_books_source_sha256", "books", ["source_sha256"])

    op.create_table(
        "book_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("page_kind", sa.String(length=20), nullable=False, server_default="scanned_image"),
        sa.Column("image_storage_key", sa.Text(), nullable=True),
        sa.Column("image_sha256", sa.String(length=64), nullable=True),
        sa.Column("width_px", sa.Integer(), nullable=True),
        sa.Column("height_px", sa.Integer(), nullable=True),
        sa.Column("render_dpi", sa.Integer(), nullable=True),
        sa.Column("extracted_text_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("image_coverage_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("digital_text_content", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="not_started"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("page_number > 0", name="ck_book_pages_page_number_positive"),
        sa.UniqueConstraint("book_id", "page_number", name="uq_book_pages_book_page"),
    )

    op.create_table(
        "model_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("engine_name", sa.String(length=80), nullable=False),
        sa.Column("engine_version", sa.String(length=80), nullable=True),
        sa.Column("model_family", sa.String(length=80), nullable=True),
        sa.Column("model_id", sa.String(length=160), nullable=False),
        sa.Column("model_sha256", sa.String(length=64), nullable=True),
        sa.Column("runtime_name", sa.String(length=80), nullable=True),
        sa.Column("runtime_version", sa.String(length=80), nullable=True),
        sa.Column("device", sa.String(length=40), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "ocr_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_registry_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("model_registry.id"), nullable=True),
        sa.Column("processing_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ocr_runs_idempotency_key", "ocr_runs", ["idempotency_key"])

    op.create_table(
        "ocr_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ocr_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ocr_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("book_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=30), nullable=False, server_default="text_line"),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("polygon", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reading_order", sa.Integer(), nullable=True),
        sa.Column("raw_engine_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("ocr_run_id", "book_page_id", "block_index", name="uq_ocr_blocks_run_page_idx"),
    )
    op.create_index("ix_ocr_blocks_page", "ocr_blocks", ["book_page_id"])

    op.create_table(
        "review_edits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ocr_block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ocr_blocks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_text", sa.Text(), nullable=False),
        sa.Column("edited_text", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("reviewer_id", sa.Text(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_review_edits_block", "review_edits", ["ocr_block_id", "created_at"])

    op.create_table(
        "correction_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("language_code", sa.String(length=8), nullable=False, server_default="te"),
        sa.Column("incorrect_text", sa.Text(), nullable=False),
        sa.Column("corrected_text", sa.Text(), nullable=False),
        sa.Column("left_context", sa.Text(), nullable=True),
        sa.Column("right_context", sa.Text(), nullable=True),
        sa.Column("correction_type", sa.String(length=50), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="global_suggestion"),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("books.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_ocr_block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ocr_blocks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("approved_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("approved_count >= 0", name="ck_correction_memory_approved_nonneg"),
        sa.CheckConstraint("rejected_count >= 0", name="ck_correction_memory_rejected_nonneg"),
    )
    op.create_index("ix_correction_memory_incorrect", "correction_memory", ["language_code", "incorrect_text", "status"])

    op.create_table(
        "training_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("book_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_crop_storage_key", sa.Text(), nullable=False),
        sa.Column("image_crop_sha256", sa.String(length=64), nullable=False),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("verified_text", sa.Text(), nullable=False),
        sa.Column("annotation_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reviewer_id", sa.Text(), nullable=True),
        sa.Column("allowed_for_training", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "document_text_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("book_id", "version_number", name="uq_doc_versions_book_version"),
    )

    op.create_table(
        "document_text_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_text_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("book_page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("book_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ocr_block_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ocr_blocks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("final_text", sa.Text(), nullable=False),
        sa.Column("reading_order", sa.Integer(), nullable=False),
        sa.Column("block_role", sa.String(length=30), nullable=False, server_default="paragraph"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("document_text_blocks")
    op.drop_table("document_text_versions")
    op.drop_table("training_samples")
    op.drop_index("ix_correction_memory_incorrect", table_name="correction_memory")
    op.drop_table("correction_memory")
    op.drop_index("ix_review_edits_block", table_name="review_edits")
    op.drop_table("review_edits")
    op.drop_index("ix_ocr_blocks_page", table_name="ocr_blocks")
    op.drop_table("ocr_blocks")
    op.drop_index("ix_ocr_runs_idempotency_key", table_name="ocr_runs")
    op.drop_table("ocr_runs")
    op.drop_table("processing_jobs")
    op.drop_table("model_registry")
    op.drop_table("book_pages")
    op.drop_index("ix_books_source_sha256", table_name="books")
    op.drop_table("books")
