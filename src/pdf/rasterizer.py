"""PDF ingestion, page classification, and 300 DPI PNG rasterization using PyMuPDF."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import pymupdf

from src.common.io import atomic_write_bytes, sanitize_id, sha256_bytes, sha256_file, validate_within_workspace
from src.common.logging_utils import log_event
from src.common.manifest import PageManifestEntry

LOGGER = logging.getLogger("telugu_digitizer.pdf")


def classify_and_extract_pdf_page(page: pymupdf.Page) -> tuple[str, int, float, str]:
    """Classify a PDF page as 'digital_text', 'scanned_image', or 'mixed' and return extracted text.

    Returns (page_kind, extracted_text_char_count, image_coverage_ratio, extracted_text).
    """
    extracted = page.get_text("text") or ""
    char_count = sum(1 for ch in extracted if not ch.isspace())

    page_rect = page.rect
    page_area = max(float(page_rect.width * page_rect.height), 1.0)

    image_area = 0.0
    image_infos = page.get_image_info(xrefs=True)
    for info in image_infos:
        bbox = info.get("bbox")
        if bbox and len(bbox) == 4:
            rect = pymupdf.Rect(bbox) & page_rect
            if not rect.is_empty:
                image_area += float(rect.width * rect.height)
    coverage = min(image_area / page_area, 1.0)

    has_images = len(image_infos) > 0 or len(page.get_images(full=False)) > 0
    if char_count >= 25 and coverage < 0.15:
        kind = "digital_text"
    elif char_count >= 25 and coverage >= 0.15:
        kind = "mixed"
    elif has_images or char_count == 0:
        kind = "scanned_image"
    else:
        kind = "digital_text"

    return kind, char_count, round(coverage, 4), extracted


def classify_pdf_page(page: pymupdf.Page) -> tuple[str, int, float]:
    """Classify a PDF page as 'digital_text', 'scanned_image', or 'mixed'.

    Returns (page_kind, extracted_text_char_count, image_coverage_ratio).
    Direct extracted text is never used as an OCR benchmark result.
    """
    kind, char_count, coverage, _ = classify_and_extract_pdf_page(page)
    return kind, char_count, coverage


def resolve_page_numbers(
    total_pages: int,
    start_page: int | None = None,
    end_page: int | None = None,
    pages: Iterable[int] | None = None,
) -> list[int]:
    """Validate and resolve 1-based PDF page numbers to render."""
    if total_pages <= 0:
        raise ValueError(f"PDF has no pages (total_pages={total_pages}).")

    if pages is not None:
        selected = sorted({int(p) for p in pages})
        if not selected:
            raise ValueError("Explicit page list cannot be empty.")
        for p in selected:
            if p < 1 or p > total_pages:
                raise ValueError(f"Page number {p} out of range 1..{total_pages}.")
        return selected

    start = 1 if start_page is None else int(start_page)
    end = total_pages if end_page is None else int(end_page)
    if start < 1 or end > total_pages or start > end:
        raise ValueError(
            f"Invalid page range {start}..{end} for PDF with {total_pages} pages."
        )
    return list(range(start, end + 1))


def render_pdf_pages(
    pdf_path: Path,
    book_id: str,
    output_dir: Path,
    workspace_root: Path | None = None,
    dpi: int = 300,
    start_page: int | None = None,
    end_page: int | None = None,
    pages: Iterable[int] | None = None,
    split: str = "unspecified",
    page_quality: str = "unspecified",
    layout_type: str = "unspecified",
    skip_existing: bool = False,
) -> list[PageManifestEntry]:
    """Render selected pages of a PDF deterministically at the configured DPI.

    Per-page rendering failures are recorded on the manifest entry instead of
    aborting the entire book.
    """
    if dpi <= 0:
        raise ValueError(f"Render DPI must be positive, got {dpi}.")

    safe_book_id = sanitize_id(book_id)
    pdf_file = Path(pdf_path)
    if not pdf_file.is_file():
        raise FileNotFoundError(f"Input PDF does not exist: {pdf_file}")

    root = workspace_root.resolve() if workspace_root is not None else Path.cwd().resolve()
    book_output_dir = validate_within_workspace(output_dir / safe_book_id, root)
    book_output_dir.mkdir(parents=True, exist_ok=True)

    source_pdf_sha256 = sha256_file(pdf_file)
    matrix = pymupdf.Matrix(dpi / 72.0, dpi / 72.0)

    entries: list[PageManifestEntry] = []
    with pymupdf.open(pdf_file) as doc:
        selected_pages = resolve_page_numbers(
            doc.page_count,
            start_page=start_page,
            end_page=end_page,
            pages=pages,
        )
        log_event(
            LOGGER,
            logging.INFO,
            "Starting PDF rasterization",
            book_id=safe_book_id,
            total_pdf_pages=doc.page_count,
            selected_page_count=len(selected_pages),
            dpi=dpi,
            source_pdf_sha256=source_pdf_sha256,
        )

        for page_number in selected_pages:
            pdf_index = page_number - 1
            image_path = validate_within_workspace(
                book_output_dir / f"page-{page_number:04d}.png",
                root,
            )
            try:
                page = doc.load_page(pdf_index)
                page_kind, char_count, coverage = classify_pdf_page(page)
                rect = page.rect

                if skip_existing and image_path.is_file():
                    png_bytes = image_path.read_bytes()
                    with pymupdf.open(stream=png_bytes, filetype="png") as img_doc:
                        pix_rect = img_doc[0].rect
                        width_px = int(pix_rect.width)
                        height_px = int(pix_rect.height)
                    image_sha = sha256_bytes(png_bytes)
                else:
                    pix = page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)
                    png_bytes = pix.tobytes("png")
                    atomic_write_bytes(image_path, png_bytes)
                    width_px = int(pix.width)
                    height_px = int(pix.height)
                    image_sha = sha256_bytes(png_bytes)

                try:
                    stored_image_path = str(image_path.resolve().relative_to(root))
                except ValueError:
                    stored_image_path = str(image_path)

                try:
                    stored_pdf_path = str(pdf_file.resolve().relative_to(root))
                except ValueError:
                    stored_pdf_path = str(pdf_file)

                entry = PageManifestEntry(
                    book_id=safe_book_id,
                    page_number=page_number,
                    pdf_page_index=pdf_index,
                    source_pdf_path=stored_pdf_path,
                    source_pdf_sha256=source_pdf_sha256,
                    image_path=stored_image_path,
                    image_sha256=image_sha,
                    render_dpi=dpi,
                    page_kind=page_kind,
                    page_width_pt=round(float(rect.width), 3),
                    page_height_pt=round(float(rect.height), 3),
                    width_px=width_px,
                    height_px=height_px,
                    extracted_text_char_count=char_count,
                    image_coverage_ratio=coverage,
                    split=split,
                    page_quality=page_quality,
                    layout_type=layout_type,
                    status="rendered",
                )
                entries.append(entry)
                log_event(
                    LOGGER,
                    logging.INFO,
                    "Rendered page",
                    book_id=safe_book_id,
                    page_number=page_number,
                    page_kind=page_kind,
                    width_px=width_px,
                    height_px=height_px,
                )
            except Exception as exc:
                entry = PageManifestEntry(
                    book_id=safe_book_id,
                    page_number=page_number,
                    pdf_page_index=pdf_index,
                    source_pdf_path=str(pdf_file),
                    source_pdf_sha256=source_pdf_sha256,
                    image_path=str(image_path),
                    image_sha256=None,
                    render_dpi=dpi,
                    page_kind="scanned_image",
                    page_width_pt=0.0,
                    page_height_pt=0.0,
                    width_px=None,
                    height_px=None,
                    split=split,
                    page_quality=page_quality,
                    layout_type=layout_type,
                    status="failed",
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                entries.append(entry)
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "Failed to render page",
                    book_id=safe_book_id,
                    page_number=page_number,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

    return entries
