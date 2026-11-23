"""v1 REST API routes matching docs/07-api-contracts.md (Phase 2 scope)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.api.schemas import (
    BookListResponse,
    BookPagesResponse,
    BookSummaryResponse,
    BookUploadResponse,
    DigitalTextPageResponse,
    HealthResponse,
    OCRBlockResponse,
    OCRRunCreateRequest,
    OCRRunCreateResponse,
    OCRRunStatusResponse,
    PageOCRResponse,
    PageSummaryResponse,
)
from src.core.config import AppSettings
from src.core.storage import LocalFilesystemStorage
from src.db.models import Book, BookPage, ModelRegistry, OCRBlock, OCRRun, ProcessingJob
from src.services.book_service import (
    delete_book_and_artifacts,
    get_book_with_counts,
    import_pdf_book,
    list_books_with_counts,
)
from src.services.ocr_service import (
    OCRJobExecutor,
    create_or_reuse_ocr_runs,
    resume_ocr_run,
)

router = APIRouter(prefix="/api/v1", tags=["v1"])


def get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def get_storage(request: Request) -> LocalFilesystemStorage:
    return request.app.state.storage


def get_executor(request: Request) -> OCRJobExecutor:
    return request.app.state.ocr_executor


def get_db(request: Request):
    session_factory = request.app.state.session_factory
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@router.get("/health", response_model=HealthResponse)
def health_check(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        database="connected",
        workspace_dir=str(settings.workspace_dir),
    )


@router.post("/books", response_model=BookUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_book(
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
    settings: Annotated[AppSettings, Depends(get_settings)],
    file: UploadFile = File(...),
    title: str = Form(...),
    author: str | None = Form(default=None),
    publisher: str | None = Form(default=None),
    publication_year: int | None = Form(default=None),
    orthography_profile: str = Form(default="unspecified"),
    training_consent: bool = Form(default=False),
) -> BookUploadResponse:
    pdf_bytes = await file.read()
    book, duplicate = import_pdf_book(
        db=db,
        storage=storage,
        settings=settings,
        pdf_bytes=pdf_bytes,
        original_filename=file.filename or "document.pdf",
        title=title,
        author=author,
        publisher=publisher,
        publication_year=publication_year,
        orthography_profile=orthography_profile,
        training_consent=training_consent,
    )
    return BookUploadResponse(
        book_id=book.id,
        title=book.title,
        page_count=book.page_count,
        source_sha256=book.source_sha256,
        status="uploaded",
        duplicate=duplicate,
    )


@router.get("/books", response_model=BookListResponse)
def list_books(db: Annotated[Session, Depends(get_db)]) -> BookListResponse:
    items = [BookSummaryResponse(**row) for row in list_books_with_counts(db)]
    return BookListResponse(items=items)


@router.get("/books/{book_id}", response_model=BookSummaryResponse)
def get_book(book_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> BookSummaryResponse:
    return BookSummaryResponse(**get_book_with_counts(db, book_id))


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(
    book_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> Response:
    delete_book_and_artifacts(db=db, storage=storage, book_id=book_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/books/{book_id}/pages", response_model=BookPagesResponse)
def list_book_pages(
    book_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> BookPagesResponse:
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    pages = list(
        db.scalars(
            select(BookPage).where(BookPage.book_id == book_id).order_by(BookPage.page_number)
        ).all()
    )
    items = [
        PageSummaryResponse(
            page_id=p.id,
            page_number=p.page_number,
            page_kind=p.page_kind,
            width_px=p.width_px,
            height_px=p.height_px,
            render_dpi=p.render_dpi,
            extracted_text_char_count=p.extracted_text_char_count,
            image_coverage_ratio=p.image_coverage_ratio,
            review_status=p.review_status,
            has_image=bool(p.image_storage_key and storage.exists(p.image_storage_key)),
        )
        for p in pages
    ]
    return BookPagesResponse(book_id=book.id, page_count=book.page_count, items=items)


@router.get("/books/{book_id}/pages/{page_number}/image")
def get_page_image(
    book_id: uuid.UUID,
    page_number: int,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> Response:
    if page_number < 1:
        raise AppError("INVALID_PAGE_NUMBER", "page_number must be >= 1.", status_code=400)
    page = db.scalars(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.page_number == page_number)
    ).first()
    if page is None:
        raise AppError(
            "PAGE_NOT_FOUND",
            f"Page {page_number} not found for book {book_id}.",
            status_code=404,
        )
    if not page.image_storage_key or not storage.exists(page.image_storage_key):
        raise AppError("PAGE_IMAGE_NOT_FOUND", "Rendered page image is missing.", status_code=404)
    return Response(content=storage.read_bytes(page.image_storage_key), media_type="image/png")


@router.get("/books/{book_id}/pages/{page_number}/digital-text", response_model=DigitalTextPageResponse)
def get_page_digital_text(
    book_id: uuid.UUID,
    page_number: int,
    db: Annotated[Session, Depends(get_db)],
) -> DigitalTextPageResponse:
    if page_number < 1:
        raise AppError("INVALID_PAGE_NUMBER", "page_number must be >= 1.", status_code=400)
    page = db.scalars(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.page_number == page_number)
    ).first()
    if page is None:
        raise AppError(
            "PAGE_NOT_FOUND",
            f"Page {page_number} not found for book {book_id}.",
            status_code=404,
        )
    if page.page_kind == "scanned_image":
        raise AppError(
            "NO_DIGITAL_TEXT",
            "Page is classified as scanned_image; run OCR instead of direct digital text extraction.",
            status_code=409,
            details={"page_kind": page.page_kind},
        )
    return DigitalTextPageResponse(
        book_id=book_id,
        page_number=page.page_number,
        page_kind=page.page_kind,
        extracted_text_char_count=page.extracted_text_char_count,
        text=page.digital_text_content or "",
    )


@router.post(
    "/books/{book_id}/ocr-runs",
    response_model=OCRRunCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_ocr_run(
    book_id: uuid.UUID,
    payload: OCRRunCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    executor: Annotated[OCRJobExecutor, Depends(get_executor)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> OCRRunCreateResponse:
    res = create_or_reuse_ocr_runs(
        db=db,
        executor=executor,
        settings=settings,
        book_id=book_id,
        engines=payload.engines,
        start_page=payload.page_range.start if payload.page_range else None,
        end_page=payload.page_range.end if payload.page_range else None,
        render_dpi=payload.render_dpi,
        preprocessing_profile=payload.preprocessing_profile,
        tesseract_psm=payload.tesseract_psm,
        include_digital_text_pages=payload.include_digital_text_pages,
        force_rerun=payload.force_rerun,
    )
    return OCRRunCreateResponse(**res)


def _serialize_run_status(db: Session, ocr_run: OCRRun) -> OCRRunStatusResponse:
    model = db.get(ModelRegistry, ocr_run.model_registry_id) if ocr_run.model_registry_id else None
    job = db.get(ProcessingJob, ocr_run.processing_job_id) if ocr_run.processing_job_id else None
    return OCRRunStatusResponse(
        ocr_run_id=ocr_run.id,
        book_id=ocr_run.book_id,
        job_id=ocr_run.processing_job_id,
        engine=model.engine_name if model else None,
        model_id=model.model_id if model else None,
        status=ocr_run.status,
        progress_current=job.progress_current if job else 0,
        progress_total=job.progress_total if job else 0,
        config=ocr_run.config or {},
        started_at=ocr_run.started_at,
        completed_at=ocr_run.completed_at,
        error_summary=ocr_run.error_summary,
        error_details=job.error_details if job else {},
        created_at=ocr_run.created_at,
    )


@router.get("/ocr-runs/{run_id}", response_model=OCRRunStatusResponse)
def get_ocr_run_status(
    run_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> OCRRunStatusResponse:
    ocr_run = db.get(OCRRun, run_id)
    if ocr_run is None:
        raise AppError("OCR_RUN_NOT_FOUND", f"OCR run {run_id} not found.", status_code=404)
    return _serialize_run_status(db, ocr_run)


@router.post(
    "/ocr-runs/{run_id}/resume",
    response_model=OCRRunStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_existing_ocr_run(
    run_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    executor: Annotated[OCRJobExecutor, Depends(get_executor)],
) -> OCRRunStatusResponse:
    ocr_run = resume_ocr_run(db=db, executor=executor, run_id=run_id)
    return _serialize_run_status(db, ocr_run)


@router.get("/ocr-runs/{run_id}/pages/{page_number}", response_model=PageOCRResponse)
def get_ocr_run_page(
    run_id: uuid.UUID,
    page_number: int,
    db: Annotated[Session, Depends(get_db)],
) -> PageOCRResponse:
    if page_number < 1:
        raise AppError("INVALID_PAGE_NUMBER", "page_number must be >= 1.", status_code=400)
    ocr_run = db.get(OCRRun, run_id)
    if ocr_run is None:
        raise AppError("OCR_RUN_NOT_FOUND", f"OCR run {run_id} not found.", status_code=404)

    page = db.scalars(
        select(BookPage).where(
            BookPage.book_id == ocr_run.book_id,
            BookPage.page_number == page_number,
        )
    ).first()
    if page is None:
        raise AppError(
            "PAGE_NOT_FOUND",
            f"Page {page_number} not found for book {ocr_run.book_id}.",
            status_code=404,
        )

    model = db.get(ModelRegistry, ocr_run.model_registry_id) if ocr_run.model_registry_id else None
    blocks = list(
        db.scalars(
            select(OCRBlock)
            .where(OCRBlock.ocr_run_id == ocr_run.id, OCRBlock.book_page_id == page.id)
            .order_by(OCRBlock.block_index)
        ).all()
    )
    return PageOCRResponse(
        ocr_run_id=ocr_run.id,
        page_number=page.page_number,
        page_kind=page.page_kind,
        engine=model.engine_name if model else None,
        model_id=model.model_id if model else None,
        status=ocr_run.status,
        blocks=[
            OCRBlockResponse(
                block_id=b.id,
                block_index=b.block_index,
                reading_order=b.reading_order,
                block_type=b.block_type,
                text=b.raw_text,
                normalized_text=b.normalized_text,
                confidence=b.confidence,
                polygon=b.polygon,
            )
            for b in blocks
        ],
    )
