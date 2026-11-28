"""Add custom_dictionary_words table for user-curated Telugu vocabulary.

Revision ID: 0004_custom_dictionary_words
Revises: 0003_performance_indexes
Create Date: 2026-11-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_custom_dictionary_words"
down_revision = "0003_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_dictionary_words",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("language_code", sa.String(16), nullable=False, server_default="te"),
        sa.Column("word", sa.String(120), nullable=False),
        sa.Column("translit", sa.String(160), nullable=True),
        sa.Column("meaning_en", sa.Text(), nullable=True),
        sa.Column("meaning_te", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("language_code", "word", name="uq_custom_dict_lang_word"),
    )
    op.create_index("ix_custom_dict_word", "custom_dictionary_words", ["word"])


def downgrade() -> None:
    op.drop_index("ix_custom_dict_word", table_name="custom_dictionary_words")
    op.drop_table("custom_dictionary_words")
