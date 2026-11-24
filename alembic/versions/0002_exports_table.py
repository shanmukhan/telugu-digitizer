"""Add exports table for Phase 5 DOCX/TXT outputs.

Revision ID: 0002_exports_table
Revises: 0001_initial_schema
Create Date: 2026-11-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_exports_table"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("book_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("transcript_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_text_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("format", sa.String(length=20), nullable=False),
        sa.Column("layout_mode", sa.String(length=30), nullable=False),
        sa.Column("text_version", sa.String(length=30), nullable=False),
        sa.Column("font_family", sa.String(length=80), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("manifest_storage_key", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("is_fully_reviewed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_exports_book_id", "exports", ["book_id"])


def downgrade() -> None:
    op.drop_index("ix_exports_book_id", table_name="exports")
    op.drop_table("exports")
