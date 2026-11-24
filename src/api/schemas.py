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


class EngineCapabilityResponse(BaseModel):
    available: bool
    reason: str | None = None
    model_id: str


class CapabilitiesResponse(BaseModel):
    platform_machine: str
    auth_enabled: bool
    max_upload_mb: int
    max_pdf_pages: int
    engines: dict[str, EngineCapabilityResponse]


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


class BookOCRRunSummary(BaseModel):
    ocr_run_id: UUID
    engine: str | None
    model_id: str | None
    status: str
    progress_current: int = 0
    progress_total: int = 0
    started_at: datetime | None = None
    error_summary: str | None = None
    config: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None


class BookOCRRunsResponse(BaseModel):
    book_id: UUID
    items: list[BookOCRRunSummary]


class ReviewEditHistoryItem(BaseModel):
    edit_id: UUID
    previous_text: str
    edited_text: str
    action: str
    reviewer_id: str | None
    review_note: str | None
    created_at: datetime


class CorrectionSuggestionItem(BaseModel):
    correction_id: UUID
    incorrect_text: str
    corrected_text: str
    left_context: str | None
    right_context: str | None
    correction_type: str | None
    scope: str
    status: str
    approved_count: int
    rejected_count: int
    context_match: str
    source_book_count: int
    has_conflict: bool = False
    proposed_block_text: str | None = None


class ReviewBlockResponse(BaseModel):
    block_id: UUID
    block_index: int
    reading_order: int | None
    block_type: str
    raw_text: str
    normalized_text: str | None
    current_text: str
    is_edited: bool
    latest_action: str | None
    confidence: float | None
    low_confidence_flag: bool
    disagreement_flag: bool
    short_or_empty_flag: bool
    comparator_text: str | None
    polygon: list[list[float]] | None
    bbox: list[float] | None
    suggestions: list[CorrectionSuggestionItem] = Field(default_factory=list)
    edit_history: list[ReviewEditHistoryItem]


class PageReviewResponse(BaseModel):
    book_id: UUID
    book_title: str
    page_id: UUID
    page_number: int
    page_count: int
    page_kind: str
    width_px: int | None
    height_px: int | None
    render_dpi: int | None
    review_status: str
    digital_text_content: str | None
    available_runs: list[BookOCRRunSummary]
    primary_run_id: UUID | None
    primary_engine: str | None
    primary_model_id: str | None
    comparator_run_id: UUID | None
    comparator_engine: str | None
    blocks: list[ReviewBlockResponse]


class BlockEditRequest(BaseModel):
    edited_text: str
    action: str = "corrected"
    review_note: str | None = None
    reviewer_id: str | None = None
    add_to_correction_memory: bool = False
    memory_scope: str = "book_only"
    correction_type: str | None = None
    incorrect_span: str | None = None
    corrected_span: str | None = None


class BlockEditResponse(BaseModel):
    edit_id: UUID
    block_id: UUID
    raw_text: str
    previous_text: str
    current_text: str
    action: str
    page_review_status: str
    correction_memory_id: UUID | None = None
    created_at: datetime


class PageReviewStatusRequest(BaseModel):
    review_status: str
    primary_run_id: UUID | None = None


class PageReviewStatusResponse(BaseModel):
    book_id: UUID
    page_number: int
    review_status: str


class CorrectionMemoryRecord(BaseModel):
    correction_id: UUID
    language_code: str
    incorrect_text: str
    corrected_text: str
    left_context: str | None
    right_context: str | None
    correction_type: str | None
    scope: str
    book_id: UUID | None
    source_ocr_block_id: UUID | None
    status: str
    approved_count: int
    rejected_count: int
    created_at: datetime
    updated_at: datetime


class CorrectionSearchResponse(BaseModel):
    items: list[CorrectionSuggestionItem]


class CorrectionListResponse(BaseModel):
    items: list[CorrectionMemoryRecord]


class CorrectionRejectRequest(BaseModel):
    disable: bool = False


class CorrectionStatusRequest(BaseModel):
    status: str


class ExportCreateRequest(BaseModel):
    format: str = "docx"
    layout_mode: str = "page_preserving"
    text_version: str = "human_approved"
    primary_run_id: UUID | None = None
    font_family: str = "Noto Serif Telugu"
    body_font_size: int = Field(default=12, ge=8, le=28)
    include_page_numbers: bool = True
    include_table_of_contents: bool = False


class ExportRecordResponse(BaseModel):
    export_id: UUID
    book_id: UUID
    transcript_version_id: UUID | None
    format: str
    layout_mode: str
    text_version: str
    font_family: str
    filename: str
    status: str
    is_fully_reviewed: bool
    validation: dict[str, Any]
    download_url: str
    manifest_url: str
    created_at: datetime


class ExportListResponse(BaseModel):
    book_id: UUID
    items: list[ExportRecordResponse]
