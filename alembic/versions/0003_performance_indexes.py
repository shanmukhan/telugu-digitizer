"""Add indexes for frequent book, OCR run, job, correction memory, and text block queries.

Revision ID: 0003_performance_indexes
Revises: 0002_exports_table
Create Date: 2026-11-24
"""

from __future__ import annotations

from alembic import op

revision = "0003_performance_indexes"
down_revision = "0002_exports_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_processing_jobs_book_id", "processing_jobs", ["book_id"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
    op.create_index("ix_ocr_runs_book_created", "ocr_runs", ["book_id", "created_at"])
    op.create_index("ix_correction_memory_book_id", "correction_memory", ["book_id"])
    op.create_index(
        "ix_doc_text_blocks_version_ocr_block",
        "document_text_blocks",
        ["version_id", "ocr_block_id"],
    )
    op.create_index(
        "ix_doc_text_blocks_version_page",
        "document_text_blocks",
        ["version_id", "book_page_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_doc_text_blocks_version_page", table_name="document_text_blocks")
    op.drop_index("ix_doc_text_blocks_version_ocr_block", table_name="document_text_blocks")
    op.drop_index("ix_correction_memory_book_id", table_name="correction_memory")
    op.drop_index("ix_ocr_runs_book_created", table_name="ocr_runs")
    op.drop_index("ix_processing_jobs_status", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_book_id", table_name="processing_jobs")
