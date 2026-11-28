"""v1 REST API routes matching docs/07-api-contracts.md (Phase 2 scope)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session, defer

from src.api.errors import AppError
from src.api.schemas import (
    BlockEditRequest,
    BlockEditResponse,
    BookCalibrationStatusResponse,
    BookListResponse,
    BookOCRRunsResponse,
    BookOCRRunSummary,
    BookPagesResponse,
    BookStateUpdateRequest,
    BookSummaryResponse,
    BookUploadResponse,
    CalibrationProcessRemainingRequest,
    CalibrationRunResponse,
    CalibrationStartRequest,
    CapabilitiesResponse,
    CorrectionListResponse,
    CorrectionMemoryRecord,
    CorrectionRejectRequest,
    CorrectionSearchResponse,
    CorrectionStatusRequest,
    CorrectionSuggestionItem,
    CorrectionUpdateRequest,
    CustomDictionaryWordCreateRequest,
    CustomDictionaryWordListResponse,
    CustomDictionaryWordRecord,
    DictionarySearchResponse,
    DictionaryStatsResponse,
    DictionaryTextCheckRequest,
    DictionaryTextCheckResponse,
    DictionaryWordDetailResponse,
    DigitalTextPageResponse,
    DigitalTextUpdateRequest,
    ExportCreateRequest,
    ExportListResponse,
    ExportRecordResponse,
    HealthResponse,
    ManualBlockCreateRequest,
    ManualBlockCreateResponse,
    OCRBlockResponse,
    OCRRunCreateRequest,
    OCRRunCreateResponse,
    OCRRunStatusResponse,
    PageAutocorrectRequest,
    PageAutocorrectResponse,
    PageBatchSaveRequest,
    PageBatchSaveResponse,
    PageOCRResponse,
    PageReviewResponse,
    PageReviewStatusRequest,
    PageReviewStatusResponse,
    PageSummaryResponse,
)
from src.core.config import AppSettings
from src.core.storage import LocalFilesystemStorage
from src.db.models import Book, BookPage, DocumentExport, ModelRegistry, OCRBlock, OCRRun, ProcessingJob
from src.services.book_service import (
    delete_book_and_artifacts,
    ensure_page_image_rendered,
    get_book_with_counts,
    import_pdf_book,
    list_books_with_counts,
)
from src.services.calibration_service import (
    complete_book_calibration,
    get_book_calibration_status,
    start_book_calibration,
    start_remaining_pages_ocr,
    update_book_processing_state,
)
from src.services.correction_service import (
    approve_correction,
    delete_correction_entry,
    list_corrections_enriched,
    reject_correction,
    search_corrections,
    serialize_correction_record_dict,
    update_correction_entry,
    update_correction_status,
)
from src.services.dictionary_service import (
    check_telugu_text,
    create_custom_word,
    delete_custom_word,
    get_dictionary_stats,
    get_dictionary_word,
    list_custom_words,
    search_dictionary,
)
from src.services.export_service import create_book_export, list_book_exports
from src.services.lexicon_service import propose_page_autocorrections
from src.services.ocr_service import (
    OCRJobExecutor,
    cancel_ocr_run,
    create_or_reuse_ocr_runs,
    inspect_host_ocr_capabilities,
    resume_ocr_run,
)
from src.services.review_service import (
    batch_save_and_approve_page,
    get_page_review_payload,
    insert_manual_review_block,
    list_book_ocr_runs,
    submit_block_edit,
    update_digital_page_text,
    update_page_review_status,
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


def require_admin_for_destructive(
    request: Request,
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> None:
    """Protect destructive DELETE endpoints in public/proxy mode using Admin Basic Auth."""
    admin_creds = settings.effective_admin_credentials
    if admin_creds is None:
        if settings.is_network_exposed:
            raise AppError(
                "ADMIN_AUTH_REQUIRED",
                "Destructive delete operations require APP_ADMIN_USERNAME and APP_ADMIN_PASSWORD when network-exposed.",
                status_code=403,
            )
        return

    admin_user, admin_pass = admin_creds
    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    client_ip = request.client.host if request.client and request.client.host else "unknown"
    if rate_limiter is not None:
        locked, retry_after = rate_limiter.is_limited(
            "admin_auth_fail",
            client_ip,
            limit=settings.rate_limit_auth_failures,
            window_seconds=300.0,
        )
        if locked:
            raise AppError(
                "RATE_LIMIT_EXCEEDED",
                "Too many failed admin authentication attempts. Please retry later.",
                status_code=429,
                details={"retry_after_seconds": retry_after},
            )

    auth_header = request.headers.get("authorization", "")
    authorized = False
    provided_creds = False
    if auth_header.startswith("Basic "):
        token = auth_header[6:].strip()
        try:
            decoded = base64.b64decode(token, validate=True).decode("utf-8")
            if ":" in decoded:
                provided_creds = True
                user, password = decoded.split(":", 1)
                authorized = hmac.compare_digest(
                    user.encode("utf-8"), admin_user.encode("utf-8")
                ) and hmac.compare_digest(
                    password.encode("utf-8"), admin_pass.encode("utf-8")
                )
        except (binascii.Error, UnicodeDecodeError):
            provided_creds = True
            authorized = False

    if not authorized:
        if provided_creds and rate_limiter is not None:
            rate_limiter.allow(
                "admin_auth_fail",
                client_ip,
                limit=settings.rate_limit_auth_failures,
                window_seconds=300.0,
            )
        raise AppError(
            "UNAUTHORIZED",
            "Admin credentials required for destructive delete operations.",
            status_code=401,
        )


@router.get("/health", response_model=HealthResponse)
def health_check(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> HealthResponse:
    db.execute(text("SELECT 1"))
    workspace_status = "ready" if settings.workspace_dir.exists() else "uninitialized"
    return HealthResponse(
        status="ok",
        database="connected",
        workspace=workspace_status,
    )


@router.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities(
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> CapabilitiesResponse:
    return CapabilitiesResponse(**inspect_host_ocr_capabilities(settings))


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
    max_bytes = settings.max_upload_mb * 1024 * 1024
    tmp_dir = storage.workspace_root / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="upload_", suffix=".pdf", dir=tmp_dir)
    tmp_path = Path(tmp_name)
    hasher = hashlib.sha256()
    total_bytes = 0
    first_chunk_checked = False
    try:
        with os.fdopen(fd, "wb") as out_handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if not first_chunk_checked:
                    first_chunk_checked = True
                    if not chunk.startswith(b"%PDF-"):
                        raise AppError(
                            "INVALID_PDF_SIGNATURE",
                            "Uploaded file does not begin with a valid %PDF- signature.",
                            status_code=400,
                        )
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise AppError(
                        "PDF_TOO_LARGE",
                        f"Uploaded PDF exceeds maximum allowed size of {settings.max_upload_mb} MiB.",
                        status_code=413,
                        details={"size_bytes": total_bytes, "max_bytes": max_bytes},
                    )
                hasher.update(chunk)
                out_handle.write(chunk)
            out_handle.flush()

        if total_bytes == 0:
            raise AppError("EMPTY_UPLOAD", "Uploaded PDF file is empty.", status_code=400)

        source_sha256 = hasher.hexdigest()
        book, duplicate = await run_in_threadpool(
            import_pdf_book,
            db=db,
            storage=storage,
            settings=settings,
            pdf_path=tmp_path,
            source_sha256=source_sha256,
            size_bytes=total_bytes,
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
    finally:
        await file.close()
        tmp_path.unlink(missing_ok=True)


@router.get("/books", response_model=BookListResponse)
def list_books(db: Annotated[Session, Depends(get_db)]) -> BookListResponse:
    items = [BookSummaryResponse(**row) for row in list_books_with_counts(db)]
    return BookListResponse(items=items)


@router.get("/books/{book_id}", response_model=BookSummaryResponse)
def get_book(book_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> BookSummaryResponse:
    return BookSummaryResponse(**get_book_with_counts(db, book_id))


@router.patch("/books/{book_id}/state", response_model=BookCalibrationStatusResponse)
def patch_book_state(
    book_id: uuid.UUID,
    payload: BookStateUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> BookCalibrationStatusResponse:
    return BookCalibrationStatusResponse(
        **update_book_processing_state(db, book_id, payload.processing_state)
    )


@router.get("/books/{book_id}/calibration", response_model=BookCalibrationStatusResponse)
def get_book_calibration(
    book_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> BookCalibrationStatusResponse:
    return BookCalibrationStatusResponse(**get_book_calibration_status(db, book_id))


@router.post(
    "/books/{book_id}/calibration/start",
    response_model=CalibrationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_start_book_calibration(
    book_id: uuid.UUID,
    payload: CalibrationStartRequest,
    db: Annotated[Session, Depends(get_db)],
    executor: Annotated[OCRJobExecutor, Depends(get_executor)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> CalibrationRunResponse:
    res = start_book_calibration(
        db=db,
        executor=executor,
        settings=settings,
        book_id=book_id,
        start_page=payload.start_page,
        calibration_page_count=payload.calibration_page_count,
        end_page=payload.end_page,
        engines=payload.engines,
        render_dpi=payload.render_dpi,
        preprocessing_profile=payload.preprocessing_profile,
        tesseract_psm=payload.tesseract_psm,
        include_digital_text_pages=payload.include_digital_text_pages,
        force_rerun=payload.force_rerun,
    )
    return CalibrationRunResponse(**res)


@router.post(
    "/books/{book_id}/calibration/complete",
    response_model=BookCalibrationStatusResponse,
)
def post_complete_book_calibration(
    book_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> BookCalibrationStatusResponse:
    return BookCalibrationStatusResponse(**complete_book_calibration(db, book_id))


@router.post(
    "/books/{book_id}/calibration/process-remaining",
    response_model=CalibrationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def post_process_remaining_pages(
    book_id: uuid.UUID,
    payload: CalibrationProcessRemainingRequest,
    db: Annotated[Session, Depends(get_db)],
    executor: Annotated[OCRJobExecutor, Depends(get_executor)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> CalibrationRunResponse:
    res = start_remaining_pages_ocr(
        db=db,
        executor=executor,
        settings=settings,
        book_id=book_id,
        engines=payload.engines,
        render_dpi=payload.render_dpi,
        preprocessing_profile=payload.preprocessing_profile,
        tesseract_psm=payload.tesseract_psm,
        include_digital_text_pages=payload.include_digital_text_pages,
        force_rerun=payload.force_rerun,
        apply_calibration_corrections=payload.apply_calibration_corrections,
    )
    return CalibrationRunResponse(**res)


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(
    book_id: uuid.UUID,
    _admin: Annotated[None, Depends(require_admin_for_destructive)],
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
    executor: Annotated[OCRJobExecutor, Depends(get_executor)],
) -> Response:
    delete_book_and_artifacts(db=db, storage=storage, book_id=book_id, executor=executor)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/books/{book_id}/pdf")
def get_book_pdf(
    book_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> Response:
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)
    if not storage.exists(book.source_storage_key):
        raise AppError("PDF_FILE_MISSING", "Source PDF file is missing from storage.", status_code=404)
    headers = {"Cache-Control": "private, max-age=3600"}
    if book.source_sha256:
        headers["ETag"] = f'"{book.source_sha256}"'
    return FileResponse(
        path=storage.resolve_key(book.source_storage_key),
        media_type="application/pdf",
        headers=headers,
    )


@router.get("/books/{book_id}/ocr-runs", response_model=BookOCRRunsResponse)
def get_book_ocr_runs(
    book_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> BookOCRRunsResponse:
    items = [BookOCRRunSummary(**row) for row in list_book_ocr_runs(db, book_id)]
    return BookOCRRunsResponse(book_id=book_id, items=items)


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
            select(BookPage)
            .options(defer(BookPage.digital_text_content))
            .where(BookPage.book_id == book_id)
            .order_by(BookPage.page_number)
        ).all()
    )
    pages_dir = storage.workspace_root / "pages" / str(book_id)
    existing_filenames: set[str] = (
        {entry.name for entry in pages_dir.iterdir() if entry.is_file()}
        if pages_dir.is_dir()
        else set()
    )
    expected_prefix = f"pages/{book_id}/"
    has_source_pdf = bool(book.source_storage_key and storage.exists(book.source_storage_key))
    items = []
    for p in pages:
        key = p.image_storage_key
        if has_source_pdf:
            has_img = True
        elif not key:
            has_img = False
        elif key.startswith(expected_prefix) and "/" not in key[len(expected_prefix) :]:
            has_img = key[len(expected_prefix) :] in existing_filenames
        else:
            has_img = storage.exists(key)
        items.append(
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
                has_image=has_img,
            )
        )
    return BookPagesResponse(book_id=book.id, page_count=book.page_count, items=items)


@router.get("/books/{book_id}/pages/{page_number}/image")
def get_page_image(
    book_id: uuid.UUID,
    page_number: int,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> Response:
    if page_number < 1:
        raise AppError("INVALID_PAGE_NUMBER", "page_number must be >= 1.", status_code=400)
    page = db.scalars(
        select(BookPage)
        .options(defer(BookPage.digital_text_content))
        .where(BookPage.book_id == book_id, BookPage.page_number == page_number)
    ).first()
    if page is None:
        raise AppError(
            "PAGE_NOT_FOUND",
            f"Page {page_number} not found for book {book_id}.",
            status_code=404,
        )
    if not page.image_storage_key or not storage.exists(page.image_storage_key):
        book = db.get(Book, book_id)
        if book is None:
            raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)
        img_path = ensure_page_image_rendered(
            db=db,
            storage=storage,
            book=book,
            page=page,
            max_render_pixels=request.app.state.settings.max_render_pixels,
        )
    else:
        img_path = storage.resolve_key(page.image_storage_key)

    headers = {"Cache-Control": "private, max-age=86400"}
    if page.image_sha256:
        etag = f'"{page.image_sha256}"'
        headers["ETag"] = etag
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and etag in {t.strip() for t in if_none_match.split(",")}:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    return FileResponse(
        path=img_path,
        media_type="image/png",
        headers=headers,
    )


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


@router.post(
    "/ocr-runs/{run_id}/cancel",
    response_model=OCRRunStatusResponse,
    status_code=status.HTTP_200_OK,
)
def cancel_existing_ocr_run(
    run_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    executor: Annotated[OCRJobExecutor, Depends(get_executor)],
) -> OCRRunStatusResponse:
    ocr_run = cancel_ocr_run(db=db, executor=executor, run_id=run_id)
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


@router.get("/books/{book_id}/pages/{page_number}/review", response_model=PageReviewResponse)
def get_page_review(
    book_id: uuid.UUID,
    page_number: int,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AppSettings, Depends(get_settings)],
    primary_run_id: uuid.UUID | None = None,
    comparator_run_id: uuid.UUID | None = None,
) -> PageReviewResponse:
    payload = get_page_review_payload(
        db=db,
        book_id=book_id,
        page_number=page_number,
        primary_run_id=primary_run_id,
        comparator_run_id=comparator_run_id,
        low_conf_threshold_tesseract=settings.low_conf_threshold_tesseract,
        low_conf_threshold_paddle=settings.low_conf_threshold_paddle,
    )
    return PageReviewResponse(**payload)


@router.post("/ocr-blocks/{block_id}/edits", response_model=BlockEditResponse, status_code=status.HTTP_201_CREATED)
def post_block_edit(
    block_id: uuid.UUID,
    payload: BlockEditRequest,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> BlockEditResponse:
    result = submit_block_edit(
        db=db,
        block_id=block_id,
        edited_text=payload.edited_text,
        action=payload.action,
        block_role=payload.block_role,
        review_note=payload.review_note,
        reviewer_id=payload.reviewer_id,
        add_to_correction_memory=payload.add_to_correction_memory,
        memory_scope=payload.memory_scope,
        correction_type=payload.correction_type,
        incorrect_span=payload.incorrect_span,
        corrected_span=payload.corrected_span,
        auto_filter_noise=payload.auto_filter_noise,
        reject_auto_applied_rules=payload.reject_auto_applied_rules,
        storage=storage,
    )
    return BlockEditResponse(**result)


@router.post(
    "/books/{book_id}/pages/{page_number}/autocorrect",
    response_model=PageAutocorrectResponse,
)
def post_page_autocorrect(
    book_id: uuid.UUID,
    page_number: int,
    payload: PageAutocorrectRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> PageAutocorrectResponse:
    result = propose_page_autocorrections(
        db=db,
        book_id=book_id,
        page_number=page_number,
        primary_run_id=payload.primary_run_id,
        use_correction_memory=payload.use_correction_memory,
        use_dictionary=payload.use_dictionary,
        use_sentence_context=payload.use_sentence_context,
        min_confidence=payload.min_confidence,
        current_texts=payload.current_texts,
        lexicon_path=settings.lexicon_path,
    )
    return PageAutocorrectResponse(**result)


@router.post(
    "/books/{book_id}/pages/{page_number}/batch-save",
    response_model=PageBatchSaveResponse,
)
def post_page_batch_save(
    book_id: uuid.UUID,
    page_number: int,
    payload: PageBatchSaveRequest,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> PageBatchSaveResponse:
    result = batch_save_and_approve_page(
        db=db,
        storage=storage,
        book_id=book_id,
        page_number=page_number,
        primary_run_id=payload.primary_run_id,
        edits=[e.model_dump() for e in payload.edits],
        approve_remaining_blocks=payload.approve_remaining_blocks,
        mark_page_approved=payload.mark_page_approved,
    )
    return PageBatchSaveResponse(**result)


@router.post(
    "/books/{book_id}/pages/{page_number}/blocks",
    response_model=ManualBlockCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_manual_page_block(
    book_id: uuid.UUID,
    page_number: int,
    payload: ManualBlockCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> ManualBlockCreateResponse:
    result = insert_manual_review_block(
        db=db,
        book_id=book_id,
        page_number=page_number,
        text=payload.text,
        block_role=payload.block_role,
        primary_run_id=payload.primary_run_id,
        bbox=payload.bbox,
    )
    return ManualBlockCreateResponse(**result)


@router.patch(
    "/books/{book_id}/pages/{page_number}/digital-text",
    response_model=DigitalTextPageResponse,
)
def patch_page_digital_text(
    book_id: uuid.UUID,
    page_number: int,
    payload: DigitalTextUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> DigitalTextPageResponse:
    result = update_digital_page_text(
        db=db,
        book_id=book_id,
        page_number=page_number,
        digital_text_content=payload.text,
    )
    return DigitalTextPageResponse(**result)


@router.patch("/books/{book_id}/pages/{page_number}/review-status", response_model=PageReviewStatusResponse)
def patch_page_review_status(
    book_id: uuid.UUID,
    page_number: int,
    payload: PageReviewStatusRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PageReviewStatusResponse:
    result = update_page_review_status(
        db=db,
        book_id=book_id,
        page_number=page_number,
        review_status=payload.review_status,
        primary_run_id=payload.primary_run_id,
    )
    return PageReviewStatusResponse(**result)


def _serialize_correction_record(
    row,
    *,
    targets_by_norm: dict[str, set[str]] | None = None,
    book_titles: dict[uuid.UUID, str] | None = None,
) -> CorrectionMemoryRecord:
    return CorrectionMemoryRecord(
        **serialize_correction_record_dict(
            row,
            targets_by_norm=targets_by_norm,
            book_titles=book_titles,
        )
    )


@router.get("/corrections/search", response_model=CorrectionSearchResponse)
def search_correction_memory(
    incorrect_text: str,
    db: Annotated[Session, Depends(get_db)],
    left_context: str | None = None,
    right_context: str | None = None,
    book_id: uuid.UUID | None = None,
) -> CorrectionSearchResponse:
    items = [
        CorrectionSuggestionItem(**row)
        for row in search_corrections(
            db=db,
            incorrect_text=incorrect_text,
            left_context=left_context,
            right_context=right_context,
            book_id=book_id,
        )
    ]
    return CorrectionSearchResponse(items=items)


@router.get("/corrections", response_model=CorrectionListResponse)
def get_correction_memory_list(
    db: Annotated[Session, Depends(get_db)],
    book_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    scope_filter: str | None = None,
    unit_type: str | None = None,
    conflict_only: bool = False,
    q: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> CorrectionListResponse:
    rows, total_count, meta = list_corrections_enriched(
        db=db,
        book_id=book_id,
        status=status_filter,
        scope=scope_filter,
        unit_type=unit_type,
        conflict_only=conflict_only,
        query=q,
        limit=limit,
        offset=offset,
    )
    return CorrectionListResponse(
        items=[
            _serialize_correction_record(
                r,
                targets_by_norm=meta["targets_by_norm"],
                book_titles=meta["book_titles"],
            )
            for r in rows
        ],
        total_count=total_count,
        global_count=meta["global_count"],
        book_specific_count=meta["book_specific_count"],
        conflicts_count=meta["conflicts_count"],
    )


@router.post("/corrections/{correction_id}/approve", response_model=CorrectionMemoryRecord)
def post_approve_correction(
    correction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> CorrectionMemoryRecord:
    return _serialize_correction_record(approve_correction(db, correction_id))


@router.post("/corrections/{correction_id}/reject", response_model=CorrectionMemoryRecord)
def post_reject_correction(
    correction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    payload: CorrectionRejectRequest | None = None,
) -> CorrectionMemoryRecord:
    disable = bool(payload.disable) if payload else False
    return _serialize_correction_record(reject_correction(db, correction_id, disable=disable))


@router.patch("/corrections/{correction_id}/status", response_model=CorrectionMemoryRecord)
def patch_correction_status(
    correction_id: uuid.UUID,
    payload: CorrectionStatusRequest,
    db: Annotated[Session, Depends(get_db)],
) -> CorrectionMemoryRecord:
    return _serialize_correction_record(
        update_correction_status(db, correction_id, payload.status, scope=payload.scope)
    )


@router.patch("/corrections/{correction_id}", response_model=CorrectionMemoryRecord)
def patch_correction_entry(
    correction_id: uuid.UUID,
    payload: CorrectionUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> CorrectionMemoryRecord:
    updated = update_correction_entry(
        db,
        correction_id,
        corrected_text=payload.corrected_text,
        left_context=payload.left_context,
        right_context=payload.right_context,
        correction_type=payload.correction_type,
        unit_type=payload.unit_type,
        scope=payload.scope,
        status=payload.status,
        clear_context=payload.clear_context,
    )
    return _serialize_correction_record(updated)


@router.delete("/corrections/{correction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_correction_memory_entry(
    correction_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    delete_correction_entry(db, correction_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _serialize_export_record(row: DocumentExport) -> ExportRecordResponse:
    return ExportRecordResponse(
        export_id=row.id,
        book_id=row.book_id,
        transcript_version_id=row.transcript_version_id,
        format=row.format,
        layout_mode=row.layout_mode,
        text_version=row.text_version,
        font_family=row.font_family,
        filename=row.filename,
        status=row.status,
        is_fully_reviewed=row.is_fully_reviewed,
        validation=row.validation or {},
        download_url=f"/api/v1/exports/{row.id}/download",
        manifest_url=f"/api/v1/exports/{row.id}/manifest",
        created_at=row.created_at,
    )


@router.post(
    "/books/{book_id}/exports",
    response_model=ExportRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_create_export(
    book_id: uuid.UUID,
    payload: ExportCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> ExportRecordResponse:
    row = create_book_export(
        db=db,
        storage=storage,
        book_id=book_id,
        export_format=payload.format,
        layout_mode=payload.layout_mode,
        text_version=payload.text_version,
        primary_run_id=payload.primary_run_id,
        font_family=payload.font_family,
        body_font_size=payload.body_font_size,
        include_page_numbers=payload.include_page_numbers,
        include_table_of_contents=payload.include_table_of_contents,
    )
    return _serialize_export_record(row)


@router.get("/books/{book_id}/exports", response_model=ExportListResponse)
def get_book_exports(
    book_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> ExportListResponse:
    rows = list_book_exports(db, book_id)
    return ExportListResponse(book_id=book_id, items=[_serialize_export_record(r) for r in rows])


@router.get("/exports/{export_id}", response_model=ExportRecordResponse)
def get_export_metadata(
    export_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> ExportRecordResponse:
    row = db.get(DocumentExport, export_id)
    if row is None:
        raise AppError("EXPORT_NOT_FOUND", f"Export {export_id} not found.", status_code=404)
    return _serialize_export_record(row)


@router.get("/exports/{export_id}/download")
def download_export_file(
    export_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> Response:
    row = db.get(DocumentExport, export_id)
    if row is None:
        raise AppError("EXPORT_NOT_FOUND", f"Export {export_id} not found.", status_code=404)
    if not storage.exists(row.storage_key):
        raise AppError("EXPORT_FILE_MISSING", "Generated export file is missing from storage.", status_code=404)

    content_path = storage.resolve_key(row.storage_key)
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if row.format == "docx"
        else "text/plain; charset=utf-8"
    )
    ascii_fallback = "".join(ch if ch.isascii() and ch not in '\\"' else "_" for ch in row.filename)
    if not ascii_fallback.strip("_."):
        ascii_fallback = f"export.{row.format}"
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(row.filename)}"
    return FileResponse(
        path=content_path,
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@router.get("/exports/{export_id}/manifest")
def get_export_manifest(
    export_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalFilesystemStorage, Depends(get_storage)],
) -> dict:
    row = db.get(DocumentExport, export_id)
    if row is None:
        raise AppError("EXPORT_NOT_FOUND", f"Export {export_id} not found.", status_code=404)
    if not storage.exists(row.manifest_storage_key):
        raise AppError("EXPORT_MANIFEST_MISSING", "Export manifest sidecar is missing.", status_code=404)
    return storage.read_json(row.manifest_storage_key)


def _serialize_custom_word(row) -> CustomDictionaryWordRecord:
    return CustomDictionaryWordRecord(
        word_id=row.id,
        language_code=row.language_code,
        word=row.word,
        translit=row.translit,
        meaning_en=row.meaning_en,
        meaning_te=row.meaning_te,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/dictionary/stats", response_model=DictionaryStatsResponse)
def get_telugu_dictionary_stats(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> DictionaryStatsResponse:
    return DictionaryStatsResponse(
        **get_dictionary_stats(
            db=db,
            dictionary_db_path=settings.dictionary_db_path,
            lexicon_path=settings.lexicon_path,
        )
    )


@router.get("/dictionary/search", response_model=DictionarySearchResponse)
def search_telugu_dictionary(
    q: str,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AppSettings, Depends(get_settings)],
    mode: str = "auto",
    limit: int = 25,
) -> DictionarySearchResponse:
    return DictionarySearchResponse(
        **search_dictionary(
            db=db,
            query=q,
            mode=mode,
            limit=limit,
            dictionary_db_path=settings.dictionary_db_path,
            lexicon_path=settings.lexicon_path,
        )
    )


@router.get("/dictionary/word/{word}", response_model=DictionaryWordDetailResponse)
def get_telugu_dictionary_word(
    word: str,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> DictionaryWordDetailResponse:
    return DictionaryWordDetailResponse(
        **get_dictionary_word(
            db=db,
            word=word,
            dictionary_db_path=settings.dictionary_db_path,
            lexicon_path=settings.lexicon_path,
        )
    )


@router.post("/dictionary/check-text", response_model=DictionaryTextCheckResponse)
def post_check_telugu_text(
    payload: DictionaryTextCheckRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> DictionaryTextCheckResponse:
    return DictionaryTextCheckResponse(
        **check_telugu_text(
            db=db,
            text=payload.text,
            lexicon_path=settings.lexicon_path,
        )
    )


@router.get("/dictionary/custom", response_model=CustomDictionaryWordListResponse)
def get_custom_dictionary_words(
    db: Annotated[Session, Depends(get_db)],
    q: str | None = None,
) -> CustomDictionaryWordListResponse:
    rows = list_custom_words(db, query=q)
    return CustomDictionaryWordListResponse(items=[_serialize_custom_word(r) for r in rows])


@router.post(
    "/dictionary/custom",
    response_model=CustomDictionaryWordRecord,
    status_code=status.HTTP_201_CREATED,
)
def post_custom_dictionary_word(
    payload: CustomDictionaryWordCreateRequest,
    db: Annotated[Session, Depends(get_db)],
) -> CustomDictionaryWordRecord:
    row = create_custom_word(
        db=db,
        word=payload.word,
        translit=payload.translit,
        meaning_en=payload.meaning_en,
        meaning_te=payload.meaning_te,
        notes=payload.notes,
    )
    return _serialize_custom_word(row)


@router.delete("/dictionary/custom/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_custom_dictionary_word_route(
    word_id: uuid.UUID,
    _admin: Annotated[None, Depends(require_admin_for_destructive)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    delete_custom_word(db, word_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
