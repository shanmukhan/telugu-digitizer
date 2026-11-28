"""SQLAlchemy ORM models aligned with docs/06-database-design.md."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Book(Base):
    __tablename__ = "books"
    __table_args__ = (
        CheckConstraint("page_count > 0", name="ck_books_page_count_positive"),
        Index("ix_books_source_sha256", "source_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    publisher: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language_code: Mapped[str] = mapped_column(String(8), nullable=False, default="te")
    orthography_profile: Mapped[str] = mapped_column(
        String(80), nullable=False, default="unspecified"
    )
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rights_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    training_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_utcnow,
        onupdate=_utcnow,
    )

    pages: Mapped[list["BookPage"]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="BookPage.page_number"
    )
    ocr_runs: Mapped[list["OCRRun"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["ProcessingJob"]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )


class BookPage(Base):
    __tablename__ = "book_pages"
    __table_args__ = (
        CheckConstraint("page_number > 0", name="ck_book_pages_page_number_positive"),
        UniqueConstraint("book_id", "page_number", name="uq_book_pages_book_page"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    page_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="scanned_image")
    image_storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    render_dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_text_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_coverage_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    digital_text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )

    book: Mapped["Book"] = relationship(back_populates="pages")
    ocr_blocks: Mapped[list["OCRBlock"]] = relationship(
        back_populates="book_page", cascade="all, delete-orphan"
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    engine_name: Mapped[str] = mapped_column(String(80), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_family: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model_id: Mapped[str] = mapped_column(String(160), nullable=False)
    model_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    runtime_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    device: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("ix_processing_jobs_book_id", "book_id"),
        Index("ix_processing_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    book: Mapped["Book"] = relationship(back_populates="jobs")


class OCRRun(Base):
    __tablename__ = "ocr_runs"
    __table_args__ = (
        Index("ix_ocr_runs_book_created", "book_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    model_registry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_registry.id"), nullable=True
    )
    processing_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("processing_jobs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )

    book: Mapped["Book"] = relationship(back_populates="ocr_runs")
    model_registry: Mapped["ModelRegistry | None"] = relationship()
    processing_job: Mapped["ProcessingJob | None"] = relationship()
    blocks: Mapped[list["OCRBlock"]] = relationship(
        back_populates="ocr_run", cascade="all, delete-orphan"
    )


class OCRBlock(Base):
    __tablename__ = "ocr_blocks"
    __table_args__ = (
        UniqueConstraint("ocr_run_id", "book_page_id", "block_index", name="uq_ocr_blocks_run_page_idx"),
        Index("ix_ocr_blocks_page", "book_page_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ocr_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ocr_runs.id", ondelete="CASCADE"), nullable=False
    )
    book_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("book_pages.id", ondelete="CASCADE"), nullable=False
    )
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(30), nullable=False, default="text_line")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    polygon: Mapped[list[list[float]] | None] = mapped_column(JSONB, nullable=True)
    reading_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_engine_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )

    ocr_run: Mapped["OCRRun"] = relationship(back_populates="blocks")
    book_page: Mapped["BookPage"] = relationship(back_populates="ocr_blocks")


class ReviewEdit(Base):
    __tablename__ = "review_edits"
    __table_args__ = (Index("ix_review_edits_block", "ocr_block_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ocr_block_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ocr_blocks.id", ondelete="CASCADE"), nullable=False
    )
    previous_text: Mapped[str] = mapped_column(Text, nullable=False)
    edited_text: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )


class CorrectionMemory(Base):
    __tablename__ = "correction_memory"
    __table_args__ = (
        CheckConstraint("approved_count >= 0", name="ck_correction_memory_approved_nonneg"),
        CheckConstraint("rejected_count >= 0", name="ck_correction_memory_rejected_nonneg"),
        Index("ix_correction_memory_incorrect", "language_code", "incorrect_text", "status"),
        Index("ix_correction_memory_book_id", "book_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    language_code: Mapped[str] = mapped_column(String(8), nullable=False, default="te")
    incorrect_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[str] = mapped_column(Text, nullable=False)
    left_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    right_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="global_suggestion")
    book_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="SET NULL"), nullable=True
    )
    source_ocr_block_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ocr_blocks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    approved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=_utcnow,
        onupdate=_utcnow,
    )


class TrainingSample(Base):
    __tablename__ = "training_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    book_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("book_pages.id", ondelete="CASCADE"), nullable=False
    )
    image_crop_storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    image_crop_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_text: Mapped[str] = mapped_column(Text, nullable=False)
    annotation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_for_training: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )


class DocumentTextVersion(Base):
    __tablename__ = "document_text_versions"
    __table_args__ = (
        UniqueConstraint("book_id", "version_number", name="uq_doc_versions_book_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )


class DocumentTextBlock(Base):
    __tablename__ = "document_text_blocks"
    __table_args__ = (
        Index("ix_doc_text_blocks_version_ocr_block", "version_id", "ocr_block_id"),
        Index("ix_doc_text_blocks_version_page", "version_id", "book_page_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_text_versions.id", ondelete="CASCADE"), nullable=False
    )
    book_page_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("book_pages.id", ondelete="CASCADE"), nullable=False
    )
    ocr_block_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ocr_blocks.id", ondelete="SET NULL"), nullable=True
    )
    final_text: Mapped[str] = mapped_column(Text, nullable=False)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    block_role: Mapped[str] = mapped_column(String(30), nullable=False, default="paragraph")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )


class DocumentExport(Base):
    __tablename__ = "exports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False
    )
    transcript_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_text_versions.id", ondelete="SET NULL"), nullable=True
    )
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    layout_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    text_version: Mapped[str] = mapped_column(String(30), nullable=False)
    font_family: Mapped[str] = mapped_column(String(80), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    is_fully_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    validation: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )


class CustomDictionaryWord(Base):
    __tablename__ = "custom_dictionary_words"
    __table_args__ = (
        UniqueConstraint("language_code", "word", name="uq_custom_dict_lang_word"),
        Index("ix_custom_dict_word", "word"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    language_code: Mapped[str] = mapped_column(String(16), nullable=False, default="te")
    word: Mapped[str] = mapped_column(String(120), nullable=False)
    translit: Mapped[str | None] = mapped_column(String(160), nullable=True)
    meaning_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    meaning_te: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=_utcnow, onupdate=_utcnow
    )
