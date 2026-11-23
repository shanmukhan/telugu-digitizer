"""Pydantic request and response models for the v1 REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    database: str
    workspace_dir: str


class BookUploadResponse(BaseModel):
    book_id: UUID
    title: str
    page_count: int
    source_sha256: str
    status: str
    duplicate: bool = False


class BookSummaryResponse(BaseModel):
    book_id: UUID
    title: str
    author: str | None
    publisher: str | None
    publication_year: int | None
    language_code: str
    orthography_profile: str
    original_filename: str
    source_sha256: str
    page_count: int
    rights_status: str
    training_consent: bool
    created_at: datetime
    updated_at: datetime
    scanned_pages_count: int
    digital_text_pages_count: int
    mixed_pages_count: int


class BookListResponse(BaseModel):
    items: list[BookSummaryResponse]


class PageSummaryResponse(BaseModel):
    page_id: UUID
    page_number: int
    page_kind: str
    width_px: int | None
    height_px: int | None
    render_dpi: int | None
    extracted_text_char_count: int
    image_coverage_ratio: float
    review_status: str
    has_image: bool


class BookPagesResponse(BaseModel):
    book_id: UUID
    page_count: int
    items: list[PageSummaryResponse]


class DigitalTextPageResponse(BaseModel):
    book_id: UUID
    page_number: int
    page_kind: str
    source: str = "pdf_digital_text_extraction"
    extracted_text_char_count: int
    text: str


class PageRangeSpec(BaseModel):
    start: int = Field(ge=1)
    end: int = Field(ge=1)


class OCRRunCreateRequest(BaseModel):
    engines: list[str] = Field(default_factory=lambda: ["paddle_ppocrv5_te", "tesseract_tel_best"], min_length=1)
    page_range: PageRangeSpec | None = None
    render_dpi: int = Field(default=300, ge=72, le=600)
    preprocessing_profile: str = Field(default="none")
    tesseract_psm: int = Field(default=6, ge=0, le=13)
    include_digital_text_pages: bool = False
    force_rerun: bool = False


class OCRRunCreateResponse(BaseModel):
    ocr_run_id: UUID
    ocr_run_ids: list[UUID]
    job_id: UUID
    status: str
    pages_total: int
    reused_existing: bool = False


class OCRRunStatusResponse(BaseModel):
    ocr_run_id: UUID
    book_id: UUID
    job_id: UUID | None
    engine: str | None
    model_id: str | None
    status: str
    progress_current: int
    progress_total: int
    config: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    error_summary: str | None
    error_details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class OCRBlockResponse(BaseModel):
    block_id: UUID
    block_index: int
    reading_order: int | None
    block_type: str
    text: str
    normalized_text: str | None
    confidence: float | None
    polygon: list[list[float]] | None


class PageOCRResponse(BaseModel):
    ocr_run_id: UUID
    page_number: int
    page_kind: str
    engine: str | None
    model_id: str | None
    status: str
    blocks: list[OCRBlockResponse]
