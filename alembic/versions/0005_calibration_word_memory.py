"""Add OCR calibration workflow fields and word-level correction memory metadata.

Revision ID: 0005_calibration_word_memory
Revises: 0004_custom_dictionary_words
Create Date: 2026-11-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_calibration_word_memory"
down_revision = "0004_custom_dictionary_words"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Book calibration configuration and explicit processing lifecycle state.
    op.add_column(
        "books",
        sa.Column("processing_state", sa.String(32), nullable=False, server_default="uploaded"),
    )
    op.add_column("books", sa.Column("calibration_start_page", sa.Integer(), nullable=True))
    op.add_column("books", sa.Column("calibration_page_count", sa.Integer(), nullable=True))
    op.add_column("books", sa.Column("calibration_end_page", sa.Integer(), nullable=True))
    op.add_column(
        "books",
        sa.Column("calibration_completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # 2. Correction memory word-level classification, normalized lookup, provenance, and last-used timestamp.
    op.add_column("correction_memory", sa.Column("normalized_incorrect", sa.Text(), nullable=True))
    op.add_column(
        "correction_memory",
        sa.Column("unit_type", sa.String(20), nullable=False, server_default="word"),
    )
    op.add_column("correction_memory", sa.Column("source_page_number", sa.Integer(), nullable=True))
    op.add_column(
        "correction_memory",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_correction_memory_norm_incorrect",
        "correction_memory",
        ["language_code", "normalized_incorrect", "status"],
    )

    # Backfill normalized_incorrect and unit_type for existing records safely.
    op.execute(
        """
        UPDATE correction_memory
        SET normalized_incorrect = trim(both '.,!?;:"''()[]{}—–-।॥ ' FROM incorrect_text),
            unit_type = CASE
                WHEN position(' ' in trim(incorrect_text)) > 0 THEN 'phrase'
                ELSE 'word'
            END
        WHERE normalized_incorrect IS NULL
        """
    )

    # 3. Review edit provenance for auto-applied calibration/memory corrections.
    op.add_column(
        "review_edits",
        sa.Column("applied_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_edits", "applied_rules")

    op.drop_index("ix_correction_memory_norm_incorrect", table_name="correction_memory")
    op.drop_column("correction_memory", "last_used_at")
    op.drop_column("correction_memory", "source_page_number")
    op.drop_column("correction_memory", "unit_type")
    op.drop_column("correction_memory", "normalized_incorrect")

    op.drop_column("books", "calibration_completed_at")
    op.drop_column("books", "calibration_end_page")
    op.drop_column("books", "calibration_page_count")
    op.drop_column("books", "calibration_start_page")
    op.drop_column("books", "processing_state")
