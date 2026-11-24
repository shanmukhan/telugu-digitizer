"""Phase 5 DOCX (editable-flow, page-preserving) and UTF-8 TXT export service."""

from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import docx
import pymupdf
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Mm, Pt
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.logging_utils import log_event
from src.core.storage import LocalFilesystemStorage
from src.db.models import (
    Book,
    BookPage,
    DocumentExport,
    DocumentTextVersion,
    ModelRegistry,
    OCRBlock,
    OCRRun,
    ReviewEdit,
)
from src.evaluation.metrics import normalize_nfc

LOGGER = logging.getLogger("telugu_digitizer.services.export")

ALLOWED_FORMATS = {"docx", "txt"}
ALLOWED_LAYOUT_MODES = {"editable_flow", "page_preserving"}
ALLOWED_TEXT_VERSIONS = {"human_approved", "raw_ocr"}


@dataclass
class PageExportContent:
    page_number: int
    page_kind: str
    review_status: str
    width_pt: float | None
    height_pt: float | None
    blocks: list[str]


def sanitize_export_stem(title: str, book_id: uuid.UUID) -> str:
    """Create a deterministic, filesystem-safe filename stem from a book title."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", title).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = cleaned.strip(".-")
    if not cleaned:
        return f"book-{str(book_id)[:8]}"
    return cleaned[:80]


def _configure_telugu_font(style: Any, font_family: str, size_pt: float, bold: bool = False) -> None:
    style.font.name = font_family
    style.font.size = Pt(size_pt)
    style.font.bold = bold
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), font_family)
    rfonts.set(qn("w:hAnsi"), font_family)
    rfonts.set(qn("w:cs"), font_family)
    lang = rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        rpr.append(lang)
    lang.set(qn("w:val"), "te-IN")
    lang.set(qn("w:bidi"), "te-IN")


def _append_field(paragraph: Any, instruction: str) -> None:
    run = paragraph.add_run()
    fld_begin = parse_xml(rf'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
    instr = parse_xml(rf'<w:instrText {nsdecls("w")} xml:space="preserve"> {instruction} </w:instrText>')
    fld_sep = parse_xml(rf'<w:fldChar {nsdecls("w")} w:fldCharType="separate"/>')
    fld_end = parse_xml(rf'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(fld_end)


def _select_ocr_run(
    db: Session,
    book_id: uuid.UUID,
    primary_run_id: uuid.UUID | None,
) -> OCRRun | None:
    if primary_run_id is not None:
        run = db.get(OCRRun, primary_run_id)
        if run is None or run.book_id != book_id:
            raise AppError(
                "OCR_RUN_NOT_FOUND",
                f"OCR run {primary_run_id} not found for book {book_id}.",
                status_code=404,
            )
        return run

    runs = list(
        db.scalars(
            select(OCRRun)
            .where(OCRRun.book_id == book_id, OCRRun.status.in_(["completed", "partial"]))
            .order_by(OCRRun.created_at.desc())
        ).all()
    )
    if not runs:
        return None
    for run in runs:
        model = db.get(ModelRegistry, run.model_registry_id) if run.model_registry_id else None
        if model and model.engine_name == "paddleocr":
            return run
    return runs[0]


def _collect_export_pages(
    *,
    db: Session,
    storage: LocalFilesystemStorage,
    book: Book,
    text_version: str,
    primary_run_id: uuid.UUID | None,
) -> tuple[list[PageExportContent], uuid.UUID | None, list[int], bool]:
    pages = list(
        db.scalars(
            select(BookPage).where(BookPage.book_id == book.id).order_by(BookPage.page_number)
        ).all()
    )
    selected_run = _select_ocr_run(db, book.id, primary_run_id)
    version_row = (
        db.scalars(
            select(DocumentTextVersion)
            .where(
                DocumentTextVersion.book_id == book.id,
                DocumentTextVersion.origin == "human_approved",
            )
            .order_by(DocumentTextVersion.version_number.desc())
        ).first()
        if text_version == "human_approved"
        else None
    )

    page_dims: dict[int, tuple[float, float]] = {}
    if storage.exists(book.source_storage_key):
        pdf_path = storage.resolve_key(book.source_storage_key)
        with pymupdf.open(pdf_path) as pdf_doc:
            for idx in range(pdf_doc.page_count):
                rect = pdf_doc.load_page(idx).rect
                page_dims[idx + 1] = (float(rect.width), float(rect.height))

    collected: list[PageExportContent] = []
    reviewed_pages: list[int] = []
    scanned_or_mixed_count = 0
    total_blocks = 0

    for page in pages:
        dims = page_dims.get(page.page_number)
        width_pt, height_pt = dims if dims else (None, None)

        if page.page_kind == "digital_text":
            lines = [ln.strip() for ln in (page.digital_text_content or "").splitlines() if ln.strip()]
            total_blocks += len(lines)
            collected.append(
                PageExportContent(
                    page_number=page.page_number,
                    page_kind=page.page_kind,
                    review_status=page.review_status,
                    width_pt=width_pt,
                    height_pt=height_pt,
                    blocks=lines,
                )
            )
            reviewed_pages.append(page.page_number)
            continue

        scanned_or_mixed_count += 1
        if page.review_status == "approved" and text_version == "human_approved":
            reviewed_pages.append(page.page_number)

        page_blocks: list[str] = []
        if selected_run is not None:
            ocr_blocks = list(
                db.scalars(
                    select(OCRBlock)
                    .where(
                        OCRBlock.ocr_run_id == selected_run.id,
                        OCRBlock.book_page_id == page.id,
                    )
                    .order_by(OCRBlock.reading_order, OCRBlock.block_index)
                ).all()
            )
            for blk in ocr_blocks:
                if text_version == "raw_ocr":
                    txt = blk.raw_text
                else:
                    latest_edit = db.scalars(
                        select(ReviewEdit)
                        .where(ReviewEdit.ocr_block_id == blk.id)
                        .order_by(ReviewEdit.created_at.desc(), ReviewEdit.id.desc())
                    ).first()
                    txt = latest_edit.edited_text if latest_edit else blk.raw_text
                if txt.strip():
                    page_blocks.append(txt)
        elif page.page_kind == "mixed" and page.digital_text_content:
            page_blocks = [ln.strip() for ln in page.digital_text_content.splitlines() if ln.strip()]

        total_blocks += len(page_blocks)
        collected.append(
            PageExportContent(
                page_number=page.page_number,
                page_kind=page.page_kind,
                review_status=page.review_status,
                width_pt=width_pt,
                height_pt=height_pt,
                blocks=page_blocks,
            )
        )

    if scanned_or_mixed_count > 0 and selected_run is None and total_blocks == 0:
        raise AppError(
            "NO_OCR_RUN_AVAILABLE",
            "No completed OCR run exists for this book yet. Run OCR on scanned pages before exporting.",
            status_code=409,
            details={"book_id": str(book.id), "scanned_or_mixed_pages": scanned_or_mixed_count},
        )

    is_fully_reviewed = (
        text_version == "human_approved"
        and (
            scanned_or_mixed_count == 0
            or sum(1 for p in collected if p.page_kind != "digital_text" and p.review_status == "approved")
            == scanned_or_mixed_count
        )
    )
    return collected, (version_row.id if version_row else None), reviewed_pages, is_fully_reviewed


def _build_docx_bytes(
    *,
    book: Book,
    pages: list[PageExportContent],
    layout_mode: str,
    text_version: str,
    font_family: str,
    body_font_size: int,
    include_page_numbers: bool,
    include_table_of_contents: bool,
    is_fully_reviewed: bool,
) -> tuple[bytes, dict[str, Any]]:
    doc = Document()
    doc.core_properties.title = book.title
    if book.author:
        doc.core_properties.author = book.author
    doc.core_properties.comments = (
        f"Telugu Book Digitizer export ({layout_mode}, {text_version}, source_sha256={book.source_sha256})"
    )

    _configure_telugu_font(doc.styles["Normal"], font_family, body_font_size, bold=False)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.2
    doc.styles["Normal"].paragraph_format.space_after = Pt(6)
    _configure_telugu_font(doc.styles["Heading 1"], font_family, 20, bold=True)
    _configure_telugu_font(doc.styles["Heading 2"], font_family, 15, bold=True)

    section = doc.sections[0]
    section.top_margin = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin = Inches(1.0)
    section.right_margin = Inches(1.0)

    if layout_mode == "page_preserving" and pages and pages[0].width_pt and pages[0].height_pt:
        section.page_width = Inches(pages[0].width_pt / 72.0)
        section.page_height = Inches(pages[0].height_pt / 72.0)
    else:
        section.page_width = Mm(210)
        section.page_height = Mm(297)

    if include_page_numbers:
        footer_para = section.footer.paragraphs[0]
        footer_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer_para.add_run("Page ")
        _append_field(footer_para, "PAGE")

    # Document header block in editable_flow or unreviewed notice banner
    if layout_mode == "editable_flow":
        doc.add_heading(book.title, level=1)
        if book.author:
            author_p = doc.add_paragraph(book.author)
            author_p.paragraph_format.space_after = Pt(10)

    if text_version == "raw_ocr":
        notice = doc.add_paragraph(
            "[UNREVIEWED MACHINE OCR OUTPUT — exported directly from raw OCR without human review]"
        )
        notice.paragraph_format.space_after = Pt(10)
    elif not is_fully_reviewed:
        approved_cnt = sum(1 for p in pages if p.page_kind != "digital_text" and p.review_status == "approved")
        scanned_cnt = sum(1 for p in pages if p.page_kind != "digital_text")
        notice = doc.add_paragraph(
            f"[PARTIAL HUMAN REVIEW — {approved_cnt} of {scanned_cnt} scanned/mixed pages marked approved]"
        )
        notice.paragraph_format.space_after = Pt(10)

    if layout_mode == "editable_flow" and include_table_of_contents:
        toc_heading = doc.add_heading("Table of Contents", level=2)
        toc_heading.paragraph_format.space_after = Pt(4)
        toc_para = doc.add_paragraph()
        _append_field(toc_para, 'TOC \\o "1-3" \\h \\z \\u')

    expected_blocks: list[str] = []
    for idx, page in enumerate(pages):
        if layout_mode == "page_preserving":
            if idx > 0:
                doc.add_page_break()
            if include_page_numbers:
                marker = doc.add_paragraph(f"— Source Page {page.page_number} —")
                marker.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                marker.paragraph_format.space_after = Pt(4)

        for block_text in page.blocks:
            p = doc.add_paragraph()
            run = p.add_run(block_text)
            run.font.name = font_family
            run.font.size = Pt(body_font_size)
            expected_blocks.append(block_text)

    buf = io.BytesIO()
    doc.save(buf)
    raw_bytes = buf.getvalue()

    # Quality validation: re-open DOCX and verify every block is present in order.
    validation = _validate_docx_bytes(
        raw_bytes=raw_bytes,
        expected_blocks=expected_blocks,
        expected_page_breaks=(len(pages) - 1) if (layout_mode == "page_preserving" and len(pages) > 1) else 0,
    )
    return raw_bytes, validation


def _validate_docx_bytes(
    *,
    raw_bytes: bytes,
    expected_blocks: list[str],
    expected_page_breaks: int,
) -> dict[str, Any]:
    reopened = docx.Document(io.BytesIO(raw_bytes))
    extracted_paras = [normalize_nfc(p.text).strip() for p in reopened.paragraphs if p.text.strip()]

    # Verify ordered subsequence match of all expected transcript blocks
    cursor = 0
    matched = 0
    for expected in expected_blocks:
        exp_nfc = normalize_nfc(expected).strip()
        while cursor < len(extracted_paras):
            if extracted_paras[cursor] == exp_nfc:
                matched += 1
                cursor += 1
                break
            cursor += 1

    # Count explicit page breaks in XML
    page_breaks = len(reopened.element.body.xpath(".//w:br[@w:type='page']"))
    passed = matched == len(expected_blocks) and page_breaks >= expected_page_breaks
    if not passed:
        raise AppError(
            "EXPORT_VALIDATION_FAILED",
            "DOCX export quality verification detected missing blocks or page breaks.",
            status_code=500,
            details={
                "blocks_expected": len(expected_blocks),
                "blocks_verified": matched,
                "page_breaks_expected": expected_page_breaks,
                "page_breaks_found": page_breaks,
            },
        )
    return {
        "passed": True,
        "utf8_valid": True,
        "paragraph_count": len(extracted_paras),
        "blocks_expected": len(expected_blocks),
        "blocks_verified": matched,
        "page_breaks_verified": page_breaks,
    }


def _build_txt_bytes(
    *,
    pages: list[PageExportContent],
) -> tuple[bytes, dict[str, Any]]:
    page_chunks: list[str] = []
    expected_blocks: list[str] = []
    for page in pages:
        expected_blocks.extend(page.blocks)
        page_chunks.append("\n".join(page.blocks))

    # Form-feed delimiter between pages per 09-document-export-specification.md §2.C
    txt_content = "\n\f\n".join(page_chunks)
    if txt_content and not txt_content.endswith("\n"):
        txt_content += "\n"

    raw_bytes = txt_content.encode("utf-8")
    decoded = raw_bytes.decode("utf-8")
    lines = [normalize_nfc(ln).strip() for ln in decoded.replace("\f", "\n").splitlines() if ln.strip()]
    expected_lines = [normalize_nfc(ln).strip() for blk in expected_blocks for ln in blk.splitlines() if ln.strip()]
    passed = len(lines) == len(expected_lines) and all(a == b for a, b in zip(lines, expected_lines))
    if not passed:
        raise AppError(
            "EXPORT_VALIDATION_FAILED",
            "TXT export verification failed line-by-line integrity check.",
            status_code=500,
        )
    return raw_bytes, {
        "passed": True,
        "utf8_valid": True,
        "blocks_expected": len(expected_blocks),
        "blocks_verified": len(expected_blocks),
        "page_breaks_verified": max(len(pages) - 1, 0),
    }


def create_book_export(
    *,
    db: Session,
    storage: LocalFilesystemStorage,
    book_id: uuid.UUID,
    export_format: str = "docx",
    layout_mode: str = "page_preserving",
    text_version: str = "human_approved",
    primary_run_id: uuid.UUID | None = None,
    font_family: str = "Noto Serif Telugu",
    body_font_size: int = 12,
    include_page_numbers: bool = True,
    include_table_of_contents: bool = False,
) -> DocumentExport:
    """Generate, validate, persist, and register a DOCX or UTF-8 TXT book export."""
    fmt = export_format.strip().lower()
    if fmt not in ALLOWED_FORMATS:
        raise AppError(
            "UNSUPPORTED_EXPORT_FORMAT",
            f"Unsupported export format {export_format!r}. Allowed: {sorted(ALLOWED_FORMATS)}.",
            status_code=400,
        )
    if fmt == "docx" and layout_mode not in ALLOWED_LAYOUT_MODES:
        raise AppError(
            "UNSUPPORTED_LAYOUT_MODE",
            f"Unsupported layout_mode {layout_mode!r}. Allowed: {sorted(ALLOWED_LAYOUT_MODES)}.",
            status_code=400,
        )
    if text_version not in ALLOWED_TEXT_VERSIONS:
        raise AppError(
            "UNSUPPORTED_TEXT_VERSION",
            f"Unsupported text_version {text_version!r}. Allowed: {sorted(ALLOWED_TEXT_VERSIONS)}.",
            status_code=400,
        )

    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    pages, version_id, reviewed_pages, is_fully_reviewed = _collect_export_pages(
        db=db,
        storage=storage,
        book=book,
        text_version=text_version,
        primary_run_id=primary_run_id,
    )

    stem = sanitize_export_stem(book.title, book.id)
    if fmt == "docx":
        mode_slug = "editable-flow" if layout_mode == "editable_flow" else "page-preserving"
        filename = f"{stem}_{mode_slug}.docx"
        out_bytes, validation = _build_docx_bytes(
            book=book,
            pages=pages,
            layout_mode=layout_mode,
            text_version=text_version,
            font_family=font_family,
            body_font_size=body_font_size,
            include_page_numbers=include_page_numbers,
            include_table_of_contents=include_table_of_contents,
            is_fully_reviewed=is_fully_reviewed,
        )
        effective_mode = layout_mode
        exporter_lib = f"python-docx=={docx.__version__}"
    else:
        filename = f"{stem}.txt"
        out_bytes, validation = _build_txt_bytes(pages=pages)
        effective_mode = "plain_text"
        exporter_lib = "python-utf8"

    export_id = uuid.uuid4()
    storage_key = f"exports/{book.id}/{export_id}/{filename}"
    manifest_key = f"exports/{book.id}/{export_id}/export-manifest.json"
    created_at = datetime.now(timezone.utc)

    manifest_payload = {
        "export_id": str(export_id),
        "book_id": str(book.id),
        "title": book.title,
        "transcript_version_id": str(version_id) if version_id else None,
        "text_version": text_version,
        "format": fmt,
        "layout_mode": effective_mode,
        "font_family": font_family,
        "exporter_library": exporter_lib,
        "created_at": created_at.isoformat(),
        "source_pdf_sha256": book.source_sha256,
        "included_pages": [p.page_number for p in pages],
        "reviewed_pages": reviewed_pages,
        "is_fully_reviewed": is_fully_reviewed,
        "validation": validation,
    }

    storage.write_bytes(storage_key, out_bytes, read_only=False)
    storage.write_json(manifest_key, manifest_payload)

    export_row = DocumentExport(
        id=export_id,
        book_id=book.id,
        transcript_version_id=version_id,
        format=fmt,
        layout_mode=effective_mode,
        text_version=text_version,
        font_family=font_family,
        filename=filename,
        storage_key=storage_key,
        manifest_storage_key=manifest_key,
        status="completed",
        is_fully_reviewed=is_fully_reviewed,
        options={
            "body_font_size": body_font_size,
            "include_page_numbers": include_page_numbers,
            "include_table_of_contents": include_table_of_contents,
            "primary_run_id": str(primary_run_id) if primary_run_id else None,
        },
        validation=validation,
        created_at=created_at,
    )
    db.add(export_row)
    db.commit()
    db.refresh(export_row)

    log_event(
        LOGGER,
        logging.INFO,
        "Created validated book export",
        export_id=str(export_id),
        book_id=str(book.id),
        format=fmt,
        layout_mode=effective_mode,
        is_fully_reviewed=is_fully_reviewed,
    )
    return export_row


def list_book_exports(db: Session, book_id: uuid.UUID) -> list[DocumentExport]:
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)
    return list(
        db.scalars(
            select(DocumentExport)
            .where(DocumentExport.book_id == book_id)
            .order_by(DocumentExport.created_at.desc())
        ).all()
    )
