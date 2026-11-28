"""Phase 5 DOCX (editable-flow, page-preserving) and UTF-8 TXT export service."""

from __future__ import annotations

import io
import logging
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pymupdf
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
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
    DocumentTextBlock,
    DocumentTextVersion,
    ModelRegistry,
    OCRBlock,
    OCRRun,
    ProcessingJob,
    ReviewEdit,
)
from src.evaluation.metrics import normalize_nfc

LOGGER = logging.getLogger("telugu_digitizer.services.export")

ALLOWED_FORMATS = {"docx", "txt"}
ALLOWED_LAYOUT_MODES = {"editable_flow", "page_preserving"}
ALLOWED_TEXT_VERSIONS = {"human_approved", "raw_ocr"}

# XML 1.0 forbids C0 control characters outside \t, \n, \r (frequently found in dirty digital PDF text layers).
_XML_ILLEGAL_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W_P_TAG = f"{{{_W_NS}}}p"
_W_T_TAG = f"{{{_W_NS}}}t"
_W_BR_TAG = f"{{{_W_NS}}}br"
_W_TAB_TAG = f"{{{_W_NS}}}tab"
_W_TYPE_ATTR = f"{{{_W_NS}}}type"


@dataclass
class ExportBlockItem:
    text: str
    role: str = "paragraph"


@dataclass
class PageExportContent:
    page_number: int
    page_kind: str
    review_status: str
    width_pt: float | None
    height_pt: float | None
    blocks: list[str]
    block_items: list[ExportBlockItem] | None = None


def _sanitize_xml_text(value: str, *, normalize_unicode_nfc: bool = False) -> str:
    cleaned = _XML_ILLEGAL_CTRL_RE.sub("", value)
    return normalize_nfc(cleaned) if normalize_unicode_nfc else cleaned


def sanitize_export_stem(title: str, book_id: uuid.UUID) -> str:
    """Create a deterministic, filesystem-safe filename stem from a book title."""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", title).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = cleaned.strip(".-")
    if not cleaned:
        return f"book-{str(book_id)[:8]}"
    return cleaned[:80]


def _set_telugu_rpr_fonts(element_rpr: Any, font_family: str) -> None:
    rfonts = element_rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        element_rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), font_family)
    rfonts.set(qn("w:hAnsi"), font_family)
    rfonts.set(qn("w:cs"), font_family)
    lang = element_rpr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        element_rpr.append(lang)
    lang.set(qn("w:val"), "te-IN")
    lang.set(qn("w:bidi"), "te-IN")


def _configure_telugu_font(style: Any, font_family: str, size_pt: float, bold: bool = False) -> None:
    style.font.name = font_family
    style.font.size = Pt(size_pt)
    style.font.bold = bold
    rpr = style.element.get_or_add_rPr()
    _set_telugu_rpr_fonts(rpr, font_family)


def _apply_run_telugu_font(run: Any, font_family: str, size_pt: float, *, bold: bool = False) -> None:
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    rpr = run._r.get_or_add_rPr()
    _set_telugu_rpr_fonts(rpr, font_family)


def _append_field(paragraph: Any, instruction: str) -> None:
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "

    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")

    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")

    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(fld_end)


def _list_ranked_usable_ocr_runs(
    db: Session,
    book_id: uuid.UUID,
) -> list[OCRRun]:
    """Return all completed/partial OCR runs for a book ordered from highest to lowest priority."""
    rows = db.execute(
        select(OCRRun, ModelRegistry, ProcessingJob)
        .outerjoin(ModelRegistry, OCRRun.model_registry_id == ModelRegistry.id)
        .outerjoin(ProcessingJob, OCRRun.processing_job_id == ProcessingJob.id)
        .where(OCRRun.book_id == book_id, OCRRun.status.in_(["completed", "partial"]))
        .order_by(OCRRun.created_at.desc())
    ).all()
    if not rows:
        return []
    ranked = sorted(
        rows,
        key=lambda row: (
            (row[2].progress_current if row[2] else 0) > 0 or row[0].status == "completed",
            row[0].status == "completed",
            bool(row[1] and row[1].engine_name == "paddleocr"),
            row[2].progress_current if row[2] else 0,
            row[0].created_at,
        ),
        reverse=True,
    )
    return [row[0] for row in ranked]


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

    ranked = _list_ranked_usable_ocr_runs(db, book_id)
    return ranked[0] if ranked else None


def _resolve_page_pt_dims(
    page: BookPage,
    fallback_first_page_dims: tuple[float, float] | None,
) -> tuple[float | None, float | None]:
    if page.width_px and page.height_px and page.render_dpi and page.render_dpi > 0:
        return (
            round(float(page.width_px) * 72.0 / float(page.render_dpi), 3),
            round(float(page.height_px) * 72.0 / float(page.render_dpi), 3),
        )
    if fallback_first_page_dims is not None:
        return fallback_first_page_dims
    return None, None


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
    if primary_run_id is not None:
        explicit_run = _select_ocr_run(db, book.id, primary_run_id)
        candidate_runs = [explicit_run] if explicit_run is not None else []
    else:
        candidate_runs = _list_ranked_usable_ocr_runs(db, book.id)
    selected_run = candidate_runs[0] if candidate_runs else None
    candidate_run_ids = [r.id for r in candidate_runs]
    run_priority = {r.id: idx for idx, r in enumerate(candidate_runs)}
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

    fallback_first_page_dims: tuple[float, float] | None = None
    if pages and not (pages[0].width_px and pages[0].height_px and pages[0].render_dpi):
        if storage.exists(book.source_storage_key):
            pdf_path = storage.resolve_key(book.source_storage_key)
            with pymupdf.open(pdf_path) as pdf_doc:
                if pdf_doc.page_count > 0:
                    rect = pdf_doc.load_page(0).rect
                    fallback_first_page_dims = (float(rect.width), float(rect.height))

    # Project only needed scalar columns (never hydrating raw_engine_payload / polygon JSONB blobs).
    # Group by (page_id, run_id) so auto-export seamlessly stitches multi-range runs (e.g., 1-5 + 6-406)
    # and preserves human-reviewed blocks from whichever run the user approved on each page.
    blocks_by_page_and_run: dict[uuid.UUID, dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str, str]]]] = {}
    latest_edit_by_block: dict[uuid.UUID, str] = {}
    latest_action_by_block: dict[uuid.UUID, str] = {}
    doc_block_by_ocr_id: dict[uuid.UUID, tuple[str, str]] = {}

    if candidate_run_ids:
        raw_block_rows = db.execute(
            select(
                OCRBlock.id,
                OCRBlock.ocr_run_id,
                OCRBlock.book_page_id,
                OCRBlock.block_type,
                OCRBlock.raw_text,
            )
            .where(OCRBlock.ocr_run_id.in_(candidate_run_ids))
            .order_by(OCRBlock.book_page_id, OCRBlock.reading_order, OCRBlock.block_index)
        ).all()
        for blk_id, blk_run_id, blk_page_id, blk_type, blk_raw_text in raw_block_rows:
            blocks_by_page_and_run.setdefault(blk_page_id, {}).setdefault(blk_run_id, []).append(
                (blk_id, blk_page_id, blk_type, blk_raw_text)
            )

        if text_version != "raw_ocr" and raw_block_rows:
            # Fetch ONLY the latest ReviewEdit per block in SQL across candidate runs.
            latest_edit_rows = db.execute(
                select(ReviewEdit.ocr_block_id, ReviewEdit.edited_text, ReviewEdit.action)
                .join(OCRBlock, ReviewEdit.ocr_block_id == OCRBlock.id)
                .where(OCRBlock.ocr_run_id.in_(candidate_run_ids))
                .distinct(ReviewEdit.ocr_block_id)
                .order_by(ReviewEdit.ocr_block_id, ReviewEdit.created_at.desc(), ReviewEdit.id.desc())
            ).all()
            for eb_id, eb_text, eb_action in latest_edit_rows:
                latest_edit_by_block[eb_id] = eb_text
                latest_action_by_block[eb_id] = eb_action

            if version_row is not None:
                doc_rows = db.execute(
                    select(
                        DocumentTextBlock.ocr_block_id,
                        DocumentTextBlock.final_text,
                        DocumentTextBlock.block_role,
                    ).where(
                        DocumentTextBlock.version_id == version_row.id,
                        DocumentTextBlock.ocr_block_id.is_not(None),
                    )
                ).all()
                for d_ocr_id, d_final_text, d_role in doc_rows:
                    if d_ocr_id is not None:
                        doc_block_by_ocr_id[d_ocr_id] = (d_final_text, d_role)

    # Resolve the best single run per page so multi-range runs stitch cleanly without duplicating lines.
    blocks_by_page: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str, str]]] = {}
    for page_id, per_run in blocks_by_page_and_run.items():
        if len(per_run) == 1:
            blocks_by_page[page_id] = next(iter(per_run.values()))
            continue

        def _page_run_sort_key(item: tuple[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str, str]]]) -> tuple[int, int, int]:
            rid, blks = item
            if text_version != "raw_ocr":
                reviewed_hits = sum(
                    1 for b_id, _, _, _ in blks if b_id in doc_block_by_ocr_id or b_id in latest_edit_by_block
                )
            else:
                reviewed_hits = 0
            # Prefer runs with human-approved/edited blocks on this page, then overall run priority.
            return (1 if reviewed_hits > 0 else 0, reviewed_hits, -run_priority.get(rid, 9999))

        _best_rid, best_blocks = max(per_run.items(), key=_page_run_sort_key)
        blocks_by_page[page_id] = best_blocks

    collected: list[PageExportContent] = []
    reviewed_pages: list[int] = []
    scanned_or_mixed_count = 0
    total_blocks = 0

    for page in pages:
        width_pt, height_pt = _resolve_page_pt_dims(page, fallback_first_page_dims)

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
                    block_items=[ExportBlockItem(text=ln, role="paragraph") for ln in lines],
                )
            )
            reviewed_pages.append(page.page_number)
            continue

        scanned_or_mixed_count += 1
        if page.review_status == "approved" and text_version == "human_approved":
            reviewed_pages.append(page.page_number)

        page_blocks: list[str] = []
        page_block_items: list[ExportBlockItem] = []
        if selected_run is not None:
            for blk_id, _blk_page_id, blk_type, blk_raw_text in blocks_by_page.get(page.id, []):
                if text_version == "raw_ocr":
                    if blk_type == "manual_line":
                        continue
                    txt = blk_raw_text
                    role = "paragraph"
                else:
                    dblk = doc_block_by_ocr_id.get(blk_id)
                    action = latest_action_by_block.get(blk_id)
                    role = dblk[1] if dblk is not None else ("ignore" if action == "ignored" else "paragraph")
                    if role == "ignore" or action == "ignored":
                        continue
                    txt = dblk[0] if dblk is not None else latest_edit_by_block.get(blk_id, blk_raw_text)
                if txt.strip():
                    page_blocks.append(txt)
                    page_block_items.append(ExportBlockItem(text=txt, role=role))
        elif page.page_kind == "mixed" and page.digital_text_content:
            page_blocks = [ln.strip() for ln in page.digital_text_content.splitlines() if ln.strip()]
            page_block_items = [ExportBlockItem(text=ln, role="paragraph") for ln in page_blocks]

        total_blocks += len(page_blocks)
        collected.append(
            PageExportContent(
                page_number=page.page_number,
                page_kind=page.page_kind,
                review_status=page.review_status,
                width_pt=width_pt,
                height_pt=height_pt,
                blocks=page_blocks,
                block_items=page_block_items,
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
    from docx.enum.style import WD_STYLE_TYPE

    doc = Document()
    normalize_out = text_version != "raw_ocr"
    doc.core_properties.title = _sanitize_xml_text(book.title, normalize_unicode_nfc=normalize_out)
    if book.author:
        doc.core_properties.author = _sanitize_xml_text(book.author, normalize_unicode_nfc=normalize_out)
    doc.core_properties.comments = (
        f"Telugu Book Digitizer export ({layout_mode}, {text_version}, source_sha256={book.source_sha256})"
    )

    _configure_telugu_font(doc.styles["Normal"], font_family, body_font_size, bold=False)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.2
    doc.styles["Normal"].paragraph_format.space_after = Pt(6)
    _configure_telugu_font(doc.styles["Heading 1"], font_family, 20, bold=True)
    _configure_telugu_font(doc.styles["Heading 2"], font_family, 15, bold=True)

    if "TeluguVerse" not in doc.styles:
        verse_style = doc.styles.add_style("TeluguVerse", WD_STYLE_TYPE.PARAGRAPH)
        verse_style.base_style = doc.styles["Normal"]
        _configure_telugu_font(verse_style, font_family, body_font_size, bold=False)
        verse_style.paragraph_format.left_indent = Inches(0.35)
        verse_style.paragraph_format.space_before = Pt(3)
        verse_style.paragraph_format.space_after = Pt(4)
        verse_style.paragraph_format.line_spacing = 1.25

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
        h_title = doc.add_heading("", level=1)
        h_run = h_title.add_run(_sanitize_xml_text(book.title, normalize_unicode_nfc=normalize_out))
        _apply_run_telugu_font(h_run, font_family, 20, bold=True)
        if book.author:
            author_p = doc.add_paragraph()
            a_run = author_p.add_run(_sanitize_xml_text(book.author, normalize_unicode_nfc=normalize_out))
            _apply_run_telugu_font(a_run, font_family, body_font_size)
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

        items = page.block_items or [ExportBlockItem(text=t, role="paragraph") for t in page.blocks]
        for item in items:
            safe_text = _sanitize_xml_text(item.text, normalize_unicode_nfc=normalize_out)
            if not safe_text.strip():
                continue
            if item.role == "heading_1":
                p = doc.add_heading(level=1)
                run = p.add_run(safe_text)
                _apply_run_telugu_font(run, font_family, 20, bold=True)
            elif item.role == "heading_2":
                p = doc.add_heading(level=2)
                run = p.add_run(safe_text)
                _apply_run_telugu_font(run, font_family, 15, bold=True)
            elif item.role == "verse":
                p = doc.add_paragraph(style="TeluguVerse")
                run = p.add_run(safe_text)
                _apply_run_telugu_font(run, font_family, body_font_size)
            else:
                p = doc.add_paragraph()
                run = p.add_run(safe_text)
                _apply_run_telugu_font(run, font_family, body_font_size)
            expected_blocks.append(safe_text)

    buf = io.BytesIO()
    doc.save(buf)
    raw_bytes = buf.getvalue()
    buf.close()
    del doc

    # Streaming O(1)-DOM DOCX XML validation after releasing the builder DOM from RAM.
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
    """Validate DOCX package and text completeness using streaming iterparse (low peak RAM)."""
    extracted_paras: list[str] = []
    page_breaks = 0

    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes), "r") as zf:
            with zf.open("word/document.xml") as doc_xml:
                p_depth = 0
                para_chunks: list[str] = []
                for event, elem in ET.iterparse(doc_xml, events=("start", "end")):
                    tag = elem.tag
                    if event == "start":
                        if tag == _W_P_TAG:
                            if p_depth == 0:
                                para_chunks.clear()
                            p_depth += 1
                    else:
                        if tag == _W_T_TAG and p_depth > 0 and elem.text:
                            para_chunks.append(elem.text)
                        elif tag == _W_TAB_TAG and p_depth > 0:
                            para_chunks.append("\t")
                        elif tag == _W_BR_TAG:
                            if elem.attrib.get(_W_TYPE_ATTR) == "page":
                                page_breaks += 1
                            elif p_depth > 0:
                                para_chunks.append("\n")
                        elif tag == _W_P_TAG:
                            p_depth = max(0, p_depth - 1)
                            if p_depth == 0:
                                text_val = normalize_nfc("".join(para_chunks)).strip()
                                if text_val:
                                    extracted_paras.append(text_val)
                                para_chunks.clear()
                                elem.clear()
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise AppError(
            "EXPORT_VALIDATION_FAILED",
            f"Generated DOCX archive/XML failed validation: {exc}",
            status_code=500,
        ) from exc

    # Verify ordered subsequence match of all expected transcript blocks
    cursor = 0
    matched = 0
    for expected in expected_blocks:
        exp_nfc = _sanitize_xml_text(expected, normalize_unicode_nfc=True).strip()
        if not exp_nfc:
            matched += 1
            continue
        while cursor < len(extracted_paras):
            if extracted_paras[cursor] == exp_nfc:
                matched += 1
                cursor += 1
                break
            cursor += 1

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
    """Generate and validate a DOCX or TXT book export, saving file + export manifest."""
    fmt = export_format.strip().lower()
    layout = layout_mode.strip().lower()
    ver = text_version.strip().lower()
    if fmt not in ALLOWED_FORMATS:
        raise AppError("INVALID_EXPORT_FORMAT", f"Unsupported format {export_format!r}.", status_code=400)
    if layout not in ALLOWED_LAYOUT_MODES:
        raise AppError("INVALID_LAYOUT_MODE", f"Unsupported layout_mode {layout_mode!r}.", status_code=400)
    if ver not in ALLOWED_TEXT_VERSIONS:
        raise AppError("INVALID_TEXT_VERSION", f"Unsupported text_version {text_version!r}.", status_code=400)

    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    pages, version_id, reviewed_pages, is_fully_reviewed = _collect_export_pages(
        db=db,
        storage=storage,
        book=book,
        text_version=ver,
        primary_run_id=primary_run_id,
    )

    clean_font = (font_family or "Noto Serif Telugu").strip() or "Noto Serif Telugu"
    size_pt = max(9, min(int(body_font_size), 24))

    if fmt == "docx":
        out_bytes, validation = _build_docx_bytes(
            book=book,
            pages=pages,
            layout_mode=layout,
            text_version=ver,
            font_family=clean_font,
            body_font_size=size_pt,
            include_page_numbers=include_page_numbers,
            include_table_of_contents=include_table_of_contents,
            is_fully_reviewed=is_fully_reviewed,
        )
        suffix = f"{layout.replace('_', '-')}.docx"
    else:
        out_bytes, validation = _build_txt_bytes(pages=pages)
        suffix = "plain.txt"

    export_id = uuid.uuid4()
    stem = sanitize_export_stem(book.title, book.id)
    filename = f"{stem}_{ver}_{suffix}"
    storage_key = f"exports/{book.id}/{export_id}/{filename}"
    manifest_key = f"exports/{book.id}/{export_id}/export-manifest.json"

    storage.write_bytes(storage_key, out_bytes, read_only=False)
    manifest_payload = {
        "schema_version": 1,
        "export_id": str(export_id),
        "book_id": str(book.id),
        "book_title": book.title,
        "source_pdf_sha256": book.source_sha256,
        "transcript_version_id": str(version_id) if version_id else None,
        "format": fmt,
        "layout_mode": layout,
        "text_version": ver,
        "font_family": clean_font,
        "body_font_size": size_pt,
        "is_fully_reviewed": is_fully_reviewed,
        "included_pages": [p.page_number for p in pages],
        "reviewed_pages": reviewed_pages,
        "validation": validation,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    storage.write_json(manifest_key, manifest_payload)

    record = DocumentExport(
        id=export_id,
        book_id=book.id,
        transcript_version_id=version_id,
        format=fmt,
        layout_mode=layout,
        text_version=ver,
        font_family=clean_font,
        filename=filename,
        storage_key=storage_key,
        manifest_storage_key=manifest_key,
        status="completed",
        is_fully_reviewed=is_fully_reviewed,
        options={
            "body_font_size": size_pt,
            "include_page_numbers": include_page_numbers,
            "include_table_of_contents": include_table_of_contents,
            "primary_run_id": str(primary_run_id) if primary_run_id else None,
        },
        validation=validation,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    log_event(
        LOGGER,
        logging.INFO,
        "Created validated book export",
        book_id=str(book.id),
        export_id=str(export_id),
        format=fmt,
        layout_mode=layout,
        text_version=ver,
        is_fully_reviewed=is_fully_reviewed,
    )
    return record


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
