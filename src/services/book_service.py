"""Book import, PDF validation, page classification, and safe deletion services."""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.cache_state import bump_sentence_context_epoch
from src.common.io import sha256_bytes, sha256_file
from src.common.logging_utils import log_event
from src.core.config import AppSettings
from src.core.storage import LocalFilesystemStorage
from src.db.models import Book, BookPage, OCRRun
from src.pdf.rasterizer import (
    DEFAULT_MAX_RENDER_PIXELS,
    bounded_pixmap_matrix,
    bounded_render_dimensions,
    classify_and_extract_pdf_page,
)

LOGGER = logging.getLogger("telugu_digitizer.services.books")

# Pre-render all pages synchronously only for small PDFs (<= 10 pages); larger books
# pre-render page 1 synchronously and rasterize remaining pages lazily on demand so
# HTTP upload completes in ~2 seconds instead of hitting reverse-proxy 502 timeouts.
EAGER_RENDER_MAX_PAGES = 10

_STRIPE_LOCK_COUNT = 64
_PAGE_RENDER_LOCKS: tuple[threading.Lock, ...] = tuple(
    threading.Lock() for _ in range(_STRIPE_LOCK_COUNT)
)

# Guard Pillow against adversarial decompression bombs across all render/inspection paths.
Image.MAX_IMAGE_PIXELS = 40_000_000


def _get_page_render_lock(book_id: uuid.UUID, page_number: int) -> threading.Lock:
    idx = hash((book_id, page_number)) % _STRIPE_LOCK_COUNT
    return _PAGE_RENDER_LOCKS[idx]


def ensure_page_image_rendered(
    *,
    db: Session | None,
    storage: LocalFilesystemStorage,
    book: Book,
    page: BookPage,
    max_render_pixels: int = DEFAULT_MAX_RENDER_PIXELS,
) -> Path:
    """Ensure a page PNG exists on disk, lazily rasterizing from the immutable source PDF if needed."""
    img_key = page.image_storage_key or f"pages/{book.id}/page-{page.page_number:04d}.png"
    if storage.exists(img_key):
        return storage.resolve_key(img_key)

    if not book.source_storage_key or not storage.exists(book.source_storage_key):
        raise AppError(
            "PAGE_IMAGE_NOT_FOUND",
            "Rendered page image and source PDF are missing from storage.",
            status_code=404,
        )

    lock = _get_page_render_lock(book.id, page.page_number)
    with lock:
        if storage.exists(img_key):
            return storage.resolve_key(img_key)

        dpi = int(page.render_dpi or 300)
        source_pdf_path = storage.resolve_key(book.source_storage_key)
        with pymupdf.open(source_pdf_path) as doc:
            if page.page_number < 1 or page.page_number > doc.page_count:
                raise AppError("PAGE_NOT_FOUND", f"Page {page.page_number} out of range.", status_code=404)
            pdf_page = doc.load_page(page.page_number - 1)
            matrix, effective_dpi, clamped = bounded_pixmap_matrix(
                pdf_page.rect,
                dpi,
                max_pixels=max_render_pixels,
            )
            if clamped:
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "Clamped oversized PDF page render dimensions",
                    book_id=str(book.id),
                    page_number=page.page_number,
                    requested_dpi=dpi,
                    effective_dpi=round(effective_dpi, 2),
                )
            pix = pdf_page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)
            png_bytes = pix.tobytes("png")
            width_px = int(pix.width)
            height_px = int(pix.height)

        img_path = storage.write_bytes(img_key, png_bytes, read_only=False)
        img_sha = sha256_bytes(png_bytes)
        page.image_storage_key = img_key
        page.image_sha256 = img_sha
        page.width_px = width_px
        page.height_px = height_px
        page.render_dpi = dpi
        if db is not None:
            db.commit()
        return img_path


def import_pdf_book(
    *,
    db: Session,
    storage: LocalFilesystemStorage,
    settings: AppSettings,
    pdf_bytes: bytes | None = None,
    pdf_path: Path | None = None,
    source_sha256: str | None = None,
    size_bytes: int | None = None,
    original_filename: str,
    title: str,
    author: str | None = None,
    publisher: str | None = None,
    publication_year: int | None = None,
    orthography_profile: str = "unspecified",
    training_consent: bool = False,
) -> tuple[Book, bool]:
    """Validate and import a PDF book into PostgreSQL + read-only workspace storage.

    Accepts either an already-spooled on-disk ``pdf_path`` (preferred, streaming) or
    in-memory ``pdf_bytes``. Returns ``(book, is_duplicate)``. Duplicate uploads with
    matching source SHA-256 return the existing immutable book without re-rasterizing.
    """
    cleaned_title = title.strip()
    if not cleaned_title:
        raise AppError("INVALID_TITLE", "Book title must not be empty.", status_code=400)

    if pdf_path is None and pdf_bytes is None:
        raise AppError("EMPTY_UPLOAD", "Uploaded PDF file is empty.", status_code=400)

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if pdf_path is not None:
        actual_size = size_bytes if size_bytes is not None else pdf_path.stat().st_size
        if actual_size <= 0:
            raise AppError("EMPTY_UPLOAD", "Uploaded PDF file is empty.", status_code=400)
        if actual_size > max_bytes:
            raise AppError(
                "PDF_TOO_LARGE",
                f"Uploaded PDF exceeds maximum allowed size of {settings.max_upload_mb} MiB.",
                status_code=413,
                details={"size_bytes": actual_size, "max_bytes": max_bytes},
            )
        with pdf_path.open("rb") as handle:
            sig = handle.read(5)
        if sig != b"%PDF-":
            raise AppError(
                "INVALID_PDF_SIGNATURE",
                "Uploaded file does not begin with a valid %PDF- signature.",
                status_code=400,
            )
        source_sha = source_sha256 or sha256_file(pdf_path)
    else:
        assert pdf_bytes is not None
        if not pdf_bytes:
            raise AppError("EMPTY_UPLOAD", "Uploaded PDF file is empty.", status_code=400)
        if len(pdf_bytes) > max_bytes:
            raise AppError(
                "PDF_TOO_LARGE",
                f"Uploaded PDF exceeds maximum allowed size of {settings.max_upload_mb} MiB.",
                status_code=413,
                details={"size_bytes": len(pdf_bytes), "max_bytes": max_bytes},
            )
        if not pdf_bytes.startswith(b"%PDF-"):
            raise AppError(
                "INVALID_PDF_SIGNATURE",
                "Uploaded file does not begin with a valid %PDF- signature.",
                status_code=400,
            )
        source_sha = source_sha256 or sha256_bytes(pdf_bytes)

    existing = db.scalars(select(Book).where(Book.source_sha256 == source_sha)).first()
    if existing is not None:
        return existing, True

    safe_filename = Path(original_filename or "document.pdf").name or "document.pdf"

    try:
        doc = pymupdf.open(pdf_path) if pdf_path is not None else pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise AppError(
            "INVALID_PDF_FILE",
            f"Failed to parse PDF file: {exc}",
            status_code=400,
        ) from exc

    with doc:
        if getattr(doc, "is_encrypted", False):
            raise AppError(
                "ENCRYPTED_PDF_UNSUPPORTED",
                "Encrypted or password-protected PDFs are not supported; please remove password protection before uploading.",
                status_code=400,
            )
        page_count = doc.page_count
        if page_count <= 0:
            raise AppError("EMPTY_PDF", "Uploaded PDF has zero pages.", status_code=400)
        if page_count > settings.max_pdf_pages:
            raise AppError(
                "PDF_PAGE_LIMIT_EXCEEDED",
                f"PDF page count {page_count} exceeds limit of {settings.max_pdf_pages}.",
                status_code=400,
                details={"page_count": page_count, "max_pdf_pages": settings.max_pdf_pages},
            )

        book_id = uuid.uuid4()
        source_key = f"originals/{book_id}/source.pdf"
        dpi = settings.default_render_dpi
        max_pixels = settings.max_render_pixels

        try:
            if pdf_path is not None:
                storage.install_file(source_key, pdf_path, read_only=True)
            else:
                assert pdf_bytes is not None
                storage.write_bytes(source_key, pdf_bytes, read_only=True)

            book = Book(
                id=book_id,
                title=cleaned_title,
                author=author.strip() if author else None,
                publisher=publisher.strip() if publisher else None,
                publication_year=publication_year,
                language_code="te",
                orthography_profile=(orthography_profile or "unspecified").strip() or "unspecified",
                original_filename=safe_filename,
                source_storage_key=source_key,
                source_sha256=source_sha,
                page_count=page_count,
                rights_status="unknown",
                training_consent=bool(training_consent),
            )
            db.add(book)

            eager_render_all = page_count <= EAGER_RENDER_MAX_PAGES
            for zero_idx in range(page_count):
                page_number = zero_idx + 1
                page = doc.load_page(zero_idx)
                page_kind, char_count, coverage, extracted_text = classify_and_extract_pdf_page(page)
                digital_text = extracted_text if page_kind in ("digital_text", "mixed") else None
                img_key = f"pages/{book_id}/page-{page_number:04d}.png"

                if eager_render_all or page_number == 1:
                    matrix, effective_dpi, clamped = bounded_pixmap_matrix(
                        page.rect,
                        dpi,
                        max_pixels=max_pixels,
                    )
                    if clamped:
                        log_event(
                            LOGGER,
                            logging.WARNING,
                            "Clamped oversized PDF page render dimensions during import",
                            book_id=str(book_id),
                            page_number=page_number,
                            requested_dpi=dpi,
                            effective_dpi=round(effective_dpi, 2),
                        )
                    pix = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)
                    png_bytes = pix.tobytes("png")
                    storage.write_bytes(img_key, png_bytes, read_only=False)
                    img_sha: str | None = sha256_bytes(png_bytes)
                    width_px = int(pix.width)
                    height_px = int(pix.height)
                else:
                    # Defer heavy 300 DPI PNG rasterization until first page view or OCR run.
                    width_px, height_px = bounded_render_dimensions(
                        page.rect,
                        dpi,
                        max_pixels=max_pixels,
                    )
                    img_sha = None

                db.add(
                    BookPage(
                        book_id=book_id,
                        page_number=page_number,
                        page_kind=page_kind,
                        image_storage_key=img_key,
                        image_sha256=img_sha,
                        width_px=width_px,
                        height_px=height_px,
                        render_dpi=dpi,
                        extracted_text_char_count=char_count,
                        image_coverage_ratio=coverage,
                        digital_text_content=digital_text,
                        review_status="not_started",
                    )
                )

            db.commit()
            db.refresh(book)
        except Exception:
            db.rollback()
            storage.delete_prefix(f"originals/{book_id}")
            storage.delete_prefix(f"pages/{book_id}")
            raise

    log_event(
        LOGGER,
        logging.INFO,
        "Imported PDF book",
        book_id=str(book.id),
        page_count=book.page_count,
        source_sha256=book.source_sha256,
    )
    return book, False


def _fetch_page_kind_counts(
    db: Session,
    book_ids: list[uuid.UUID] | None = None,
) -> dict[uuid.UUID, dict[str, int]]:
    """Aggregate page classification counts per book in a single GROUP BY query."""
    stmt = select(BookPage.book_id, BookPage.page_kind, func.count(BookPage.id)).group_by(
        BookPage.book_id,
        BookPage.page_kind,
    )
    if book_ids is not None:
        if not book_ids:
            return {}
        stmt = stmt.where(BookPage.book_id.in_(book_ids))

    counts_by_book: dict[uuid.UUID, dict[str, int]] = {}
    for b_id, kind, cnt in db.execute(stmt).all():
        bucket = counts_by_book.setdefault(b_id, {})
        bucket[str(kind)] = int(cnt)
    return counts_by_book


def list_books_with_counts(db: Session) -> list[dict[str, Any]]:
    """Return all books along with page classification counts in 2 queries (no N+1)."""
    books = list(db.scalars(select(Book).order_by(Book.created_at.desc())).all())
    if not books:
        return []
    counts_by_book = _fetch_page_kind_counts(db, [b.id for b in books])
    return [_serialize_book_summary_from_counts(book, counts_by_book.get(book.id, {})) for book in books]


def get_book_with_counts(db: Session, book_id: uuid.UUID) -> dict[str, Any]:
    """Fetch a single book summary or raise 404 without loading full BookPage rows."""
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)
    counts_by_book = _fetch_page_kind_counts(db, [book.id])
    return _serialize_book_summary_from_counts(book, counts_by_book.get(book.id, {}))


def _serialize_book_summary_from_counts(book: Book, kind_counts: dict[str, int]) -> dict[str, Any]:
    return {
        "book_id": book.id,
        "title": book.title,
        "author": book.author,
        "publisher": book.publisher,
        "publication_year": book.publication_year,
        "language_code": book.language_code,
        "orthography_profile": book.orthography_profile,
        "original_filename": book.original_filename,
        "source_sha256": book.source_sha256,
        "page_count": book.page_count,
        "rights_status": book.rights_status,
        "training_consent": book.training_consent,
        "created_at": book.created_at,
        "updated_at": book.updated_at,
        "scanned_pages_count": int(kind_counts.get("scanned_image", 0)),
        "digital_text_pages_count": int(kind_counts.get("digital_text", 0)),
        "mixed_pages_count": int(kind_counts.get("mixed", 0)),
    }


def delete_book_and_artifacts(
    *,
    db: Session,
    storage: LocalFilesystemStorage,
    book_id: uuid.UUID,
    executor: Any | None = None,
) -> None:
    """Cancel any active OCR jobs, then delete DB records and all workspace files for a book."""
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    if executor is not None:
        active_run_ids = list(
            db.scalars(
                select(OCRRun.id).where(
                    OCRRun.book_id == book_id,
                    OCRRun.status.in_(["queued", "running"]),
                )
            ).all()
        )
        for rid in active_run_ids:
            executor.cancel_run(rid)
        if active_run_ids and hasattr(executor, "wait_for_runs_settled"):
            executor.wait_for_runs_settled(active_run_ids, timeout=5.0)

    db.delete(book)
    db.commit()
    bump_sentence_context_epoch()

    storage.delete_prefix(f"originals/{book_id}")
    storage.delete_prefix(f"pages/{book_id}")
    storage.delete_prefix(f"ocr/{book_id}")
    storage.delete_prefix(f"exports/{book_id}")
    storage.delete_prefix(f"training_crops/{book_id}")
    log_event(LOGGER, logging.INFO, "Deleted book and storage artifacts", book_id=str(book_id))
