"""Phase 3 review service: block alignment, flagging, append-only edits, and page review status."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.logging_utils import log_event
from src.db.models import (
    Book,
    BookPage,
    CorrectionMemory,
    DocumentTextBlock,
    DocumentTextVersion,
    ModelRegistry,
    OCRBlock,
    OCRRun,
    ProcessingJob,
    ReviewEdit,
)
from src.evaluation.metrics import normalize_nfc
from src.services.correction_service import (
    create_correction_memory_entry,
    extract_span_and_context,
    find_block_suggestions,
)

LOGGER = logging.getLogger("telugu_digitizer.services.review")

ALLOWED_EDIT_ACTIONS = {"corrected", "approved", "reverted"}
ALLOWED_REVIEW_STATUSES = {"not_started", "in_review", "approved", "needs_attention"}


def _bbox_from_block(block: OCRBlock) -> list[float] | None:
    payload = block.raw_engine_payload or {}
    raw_bbox = payload.get("bbox")
    if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
        return [float(v) for v in raw_bbox]
    poly = block.polygon
    if isinstance(poly, list) and poly:
        xs = [float(pt[0]) for pt in poly if isinstance(pt, list) and len(pt) >= 2]
        ys = [float(pt[1]) for pt in poly if isinstance(pt, list) and len(pt) >= 2]
        if xs and ys:
            return [min(xs), min(ys), max(xs), max(ys)]
    return None


def _vertical_overlap_ratio(box_a: list[float], box_b: list[float]) -> float:
    ya1, ya2 = box_a[1], box_a[3]
    yb1, yb2 = box_b[1], box_b[3]
    inter = max(0.0, min(ya2, yb2) - max(ya1, yb1))
    min_h = max(min(ya2 - ya1, yb2 - yb1), 1.0)
    return inter / min_h


def _is_low_confidence(engine_name: str | None, confidence: float | None) -> bool:
    if confidence is None:
        return False
    if engine_name == "tesseract":
        return confidence < 75.0
    return confidence < 0.85


def _match_comparator_block(
    primary_block: OCRBlock,
    primary_bbox: list[float] | None,
    comparator_blocks: list[OCRBlock],
    fallback_idx: int,
) -> OCRBlock | None:
    if not comparator_blocks:
        return None
    if primary_bbox is not None:
        best_score = 0.0
        best_block: OCRBlock | None = None
        for comp in comparator_blocks:
            comp_bbox = _bbox_from_block(comp)
            if comp_bbox is None:
                continue
            y_ov = _vertical_overlap_ratio(primary_bbox, comp_bbox)
            if y_ov <= 0.3:
                continue
            # Prefer horizontal overlap as tiebreaker for multi-column lines.
            x_inter = max(0.0, min(primary_bbox[2], comp_bbox[2]) - max(primary_bbox[0], comp_bbox[0]))
            x_union = max(max(primary_bbox[2], comp_bbox[2]) - min(primary_bbox[0], comp_bbox[0]), 1.0)
            score = y_ov + 0.5 * (x_inter / x_union)
            if score > best_score:
                best_score = score
                best_block = comp
        if best_block is not None:
            return best_block
    if 0 <= fallback_idx < len(comparator_blocks):
        return comparator_blocks[fallback_idx]
    return None


def _get_or_create_human_draft_version(db: Session, book_id: uuid.UUID) -> DocumentTextVersion:
    existing = db.scalars(
        select(DocumentTextVersion)
        .where(
            DocumentTextVersion.book_id == book_id,
            DocumentTextVersion.origin == "human_approved",
        )
        .order_by(DocumentTextVersion.version_number.desc())
    ).first()
    if existing is not None:
        return existing

    max_ver = db.scalar(
        select(func.coalesce(func.max(DocumentTextVersion.version_number), 0)).where(
            DocumentTextVersion.book_id == book_id
        )
    )
    version = DocumentTextVersion(
        book_id=book_id,
        version_number=int(max_ver or 0) + 1,
        origin="human_approved",
        status="draft",
    )
    db.add(version)
    db.flush()
    return version


def list_book_ocr_runs(db: Session, book_id: uuid.UUID) -> list[dict[str, Any]]:
    """List OCR runs for a book ordered newest first."""
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    runs = list(
        db.scalars(
            select(OCRRun).where(OCRRun.book_id == book_id).order_by(OCRRun.created_at.desc())
        ).all()
    )
    items: list[dict[str, Any]] = []
    for run in runs:
        model = db.get(ModelRegistry, run.model_registry_id) if run.model_registry_id else None
        job = db.get(ProcessingJob, run.processing_job_id) if run.processing_job_id else None
        items.append(
            {
                "ocr_run_id": run.id,
                "engine": model.engine_name if model else None,
                "model_id": model.model_id if model else None,
                "status": run.status,
                "progress_current": job.progress_current if job else 0,
                "progress_total": job.progress_total if job else 0,
                "started_at": run.started_at,
                "error_summary": run.error_summary,
                "config": run.config or {},
                "created_at": run.created_at,
                "completed_at": run.completed_at,
            }
        )
    return items


def get_page_review_payload(
    *,
    db: Session,
    book_id: uuid.UUID,
    page_number: int,
    primary_run_id: uuid.UUID | None = None,
    comparator_run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Build combined side-by-side review payload for one book page."""
    if page_number < 1:
        raise AppError("INVALID_PAGE_NUMBER", "page_number must be >= 1.", status_code=400)
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    page = db.scalars(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.page_number == page_number)
    ).first()
    if page is None:
        raise AppError(
            "PAGE_NOT_FOUND",
            f"Page {page_number} not found for book {book_id}.",
            status_code=404,
        )

    runs_info = list_book_ocr_runs(db, book_id)
    usable_runs = [r for r in runs_info if r["status"] in ("completed", "partial")]

    primary_info: dict[str, Any] | None = None
    if primary_run_id is not None:
        primary_info = next((r for r in runs_info if r["ocr_run_id"] == primary_run_id), None)
        if primary_info is None:
            raise AppError(
                "OCR_RUN_NOT_FOUND",
                f"OCR run {primary_run_id} not found for book {book_id}.",
                status_code=404,
            )
    elif usable_runs:
        # Prefer PaddleOCR PP-OCRv5 Telugu as primary when both engines exist.
        paddle_runs = [r for r in usable_runs if r["engine"] == "paddleocr"]
        primary_info = paddle_runs[0] if paddle_runs else usable_runs[0]

    comparator_info: dict[str, Any] | None = None
    if comparator_run_id is not None:
        comparator_info = next((r for r in runs_info if r["ocr_run_id"] == comparator_run_id), None)
    elif primary_info is not None:
        others = [
            r
            for r in usable_runs
            if r["ocr_run_id"] != primary_info["ocr_run_id"] and r["engine"] != primary_info["engine"]
        ]
        comparator_info = others[0] if others else None

    primary_blocks: list[OCRBlock] = []
    if primary_info is not None:
        primary_blocks = list(
            db.scalars(
                select(OCRBlock)
                .where(
                    OCRBlock.ocr_run_id == primary_info["ocr_run_id"],
                    OCRBlock.book_page_id == page.id,
                )
                .order_by(OCRBlock.reading_order, OCRBlock.block_index)
            ).all()
        )

    comparator_blocks: list[OCRBlock] = []
    if comparator_info is not None:
        comparator_blocks = list(
            db.scalars(
                select(OCRBlock)
                .where(
                    OCRBlock.ocr_run_id == comparator_info["ocr_run_id"],
                    OCRBlock.book_page_id == page.id,
                )
                .order_by(OCRBlock.reading_order, OCRBlock.block_index)
            ).all()
        )

    active_corrections = list(
        db.scalars(
            select(CorrectionMemory).where(
                CorrectionMemory.language_code == book.language_code,
                CorrectionMemory.status == "active",
            )
        ).all()
    )

    review_blocks: list[dict[str, Any]] = []
    primary_engine = primary_info["engine"] if primary_info else None
    for idx, blk in enumerate(primary_blocks):
        edits = list(
            db.scalars(
                select(ReviewEdit)
                .where(ReviewEdit.ocr_block_id == blk.id)
                .order_by(ReviewEdit.created_at.asc(), ReviewEdit.id.asc())
            ).all()
        )
        latest_edit = edits[-1] if edits else None
        current_text = latest_edit.edited_text if latest_edit else blk.raw_text
        bbox = _bbox_from_block(blk)
        comp_block = _match_comparator_block(blk, bbox, comparator_blocks, idx)
        comp_text = comp_block.raw_text if comp_block else None

        disagreement = False
        if comp_text is not None:
            disagreement = normalize_nfc(blk.raw_text).strip() != normalize_nfc(comp_text).strip()

        low_conf = _is_low_confidence(primary_engine, blk.confidence)
        short_or_empty = len(blk.raw_text.strip()) <= 1
        suggestions = find_block_suggestions(
            active_entries=active_corrections,
            block_text=current_text,
            book_id=book.id,
        )

        review_blocks.append(
            {
                "block_id": blk.id,
                "block_index": blk.block_index,
                "reading_order": blk.reading_order,
                "block_type": blk.block_type,
                "raw_text": blk.raw_text,
                "normalized_text": blk.normalized_text,
                "current_text": current_text,
                "is_edited": bool(latest_edit and current_text != blk.raw_text),
                "latest_action": latest_edit.action if latest_edit else None,
                "confidence": blk.confidence,
                "low_confidence_flag": low_conf,
                "disagreement_flag": disagreement,
                "short_or_empty_flag": short_or_empty,
                "comparator_text": comp_text,
                "polygon": blk.polygon,
                "bbox": bbox,
                "suggestions": suggestions,
                "edit_history": [
                    {
                        "edit_id": e.id,
                        "previous_text": e.previous_text,
                        "edited_text": e.edited_text,
                        "action": e.action,
                        "reviewer_id": e.reviewer_id,
                        "review_note": e.review_note,
                        "created_at": e.created_at,
                    }
                    for e in edits[-10:]
                ],
            }
        )

    return {
        "book_id": book.id,
        "book_title": book.title,
        "page_id": page.id,
        "page_number": page.page_number,
        "page_count": book.page_count,
        "page_kind": page.page_kind,
        "width_px": page.width_px,
        "height_px": page.height_px,
        "render_dpi": page.render_dpi,
        "review_status": page.review_status,
        "digital_text_content": page.digital_text_content,
        "available_runs": runs_info,
        "primary_run_id": primary_info["ocr_run_id"] if primary_info else None,
        "primary_engine": primary_engine,
        "primary_model_id": primary_info["model_id"] if primary_info else None,
        "comparator_run_id": comparator_info["ocr_run_id"] if comparator_info else None,
        "comparator_engine": comparator_info["engine"] if comparator_info else None,
        "blocks": review_blocks,
    }


def submit_block_edit(
    *,
    db: Session,
    block_id: uuid.UUID,
    edited_text: str,
    action: str = "corrected",
    review_note: str | None = None,
    reviewer_id: str | None = None,
    add_to_correction_memory: bool = False,
    memory_scope: str = "book_only",
    correction_type: str | None = None,
    incorrect_span: str | None = None,
    corrected_span: str | None = None,
) -> dict[str, Any]:
    """Persist an append-only review edit without ever overwriting ocr_blocks.raw_text."""
    if action not in ALLOWED_EDIT_ACTIONS:
        raise AppError(
            "INVALID_REVIEW_ACTION",
            f"Unsupported action {action!r}. Allowed: {sorted(ALLOWED_EDIT_ACTIONS)}.",
            status_code=400,
        )

    blk = db.get(OCRBlock, block_id)
    if blk is None:
        raise AppError("OCR_BLOCK_NOT_FOUND", f"OCR block {block_id} not found.", status_code=404)

    page = db.get(BookPage, blk.book_page_id)
    if page is None:
        raise AppError("PAGE_NOT_FOUND", "Associated book page not found.", status_code=404)

    latest_edit = db.scalars(
        select(ReviewEdit)
        .where(ReviewEdit.ocr_block_id == blk.id)
        .order_by(ReviewEdit.created_at.desc(), ReviewEdit.id.desc())
    ).first()
    previous_text = latest_edit.edited_text if latest_edit else blk.raw_text

    edit_row = ReviewEdit(
        ocr_block_id=blk.id,
        previous_text=previous_text,
        edited_text=edited_text,
        action=action,
        reviewer_id=reviewer_id,
        review_note=review_note,
    )
    db.add(edit_row)

    # Update or insert the human-approved draft version block for persistence across restarts.
    version = _get_or_create_human_draft_version(db, page.book_id)
    doc_block = db.scalars(
        select(DocumentTextBlock).where(
            DocumentTextBlock.version_id == version.id,
            DocumentTextBlock.ocr_block_id == blk.id,
        )
    ).first()
    if doc_block is None:
        db.add(
            DocumentTextBlock(
                version_id=version.id,
                book_page_id=page.id,
                ocr_block_id=blk.id,
                final_text=edited_text,
                reading_order=blk.reading_order if blk.reading_order is not None else blk.block_index,
                block_role="paragraph",
            )
        )
    else:
        doc_block.final_text = edited_text

    if page.review_status == "not_started":
        page.review_status = "in_review"

    correction_entry_id: uuid.UUID | None = None
    if add_to_correction_memory and action == "corrected" and previous_text.strip() != edited_text.strip():
        inc, cor, left_ctx, right_ctx = extract_span_and_context(previous_text, edited_text)
        if incorrect_span and corrected_span:
            inc = incorrect_span
            cor = corrected_span
        mem = create_correction_memory_entry(
            db=db,
            incorrect_text=inc,
            corrected_text=cor,
            left_context=left_ctx,
            right_context=right_ctx,
            correction_type=correction_type,
            scope=memory_scope,
            book_id=page.book_id,
            source_ocr_block_id=blk.id,
        )
        correction_entry_id = mem.id

    db.commit()
    db.refresh(edit_row)
    db.refresh(page)

    log_event(
        LOGGER,
        logging.INFO,
        "Saved append-only block review edit",
        block_id=str(blk.id),
        page_number=page.page_number,
        action=action,
        correction_memory_id=str(correction_entry_id) if correction_entry_id else None,
    )
    return {
        "edit_id": edit_row.id,
        "block_id": blk.id,
        "raw_text": blk.raw_text,
        "previous_text": edit_row.previous_text,
        "current_text": edit_row.edited_text,
        "action": edit_row.action,
        "page_review_status": page.review_status,
        "correction_memory_id": correction_entry_id,
        "created_at": edit_row.created_at,
    }


def update_page_review_status(
    *,
    db: Session,
    book_id: uuid.UUID,
    page_number: int,
    review_status: str,
    primary_run_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Update a page's review status and ensure human text blocks are snapshotted when approved."""
    if review_status not in ALLOWED_REVIEW_STATUSES:
        raise AppError(
            "INVALID_REVIEW_STATUS",
            f"Unsupported review_status {review_status!r}. Allowed: {sorted(ALLOWED_REVIEW_STATUSES)}.",
            status_code=400,
        )

    page = db.scalars(
        select(BookPage).where(BookPage.book_id == book_id, BookPage.page_number == page_number)
    ).first()
    if page is None:
        raise AppError(
            "PAGE_NOT_FOUND",
            f"Page {page_number} not found for book {book_id}.",
            status_code=404,
        )

    page.review_status = review_status
    db.flush()

    if review_status == "approved":
        version = _get_or_create_human_draft_version(db, book_id)
        if primary_run_id is not None:
            run_blocks = list(
                db.scalars(
                    select(OCRBlock)
                    .where(
                        OCRBlock.ocr_run_id == primary_run_id,
                        OCRBlock.book_page_id == page.id,
                    )
                    .order_by(OCRBlock.reading_order, OCRBlock.block_index)
                ).all()
            )
            for blk in run_blocks:
                existing_doc_blk = db.scalars(
                    select(DocumentTextBlock).where(
                        DocumentTextBlock.version_id == version.id,
                        DocumentTextBlock.ocr_block_id == blk.id,
                    )
                ).first()
                if existing_doc_blk is None:
                    latest_edit = db.scalars(
                        select(ReviewEdit)
                        .where(ReviewEdit.ocr_block_id == blk.id)
                        .order_by(ReviewEdit.created_at.desc(), ReviewEdit.id.desc())
                    ).first()
                    final_txt = latest_edit.edited_text if latest_edit else blk.raw_text
                    db.add(
                        DocumentTextBlock(
                            version_id=version.id,
                            book_page_id=page.id,
                            ocr_block_id=blk.id,
                            final_text=final_txt,
                            reading_order=blk.reading_order if blk.reading_order is not None else blk.block_index,
                            block_role="paragraph",
                        )
                    )

        # If all scanned/mixed pages in the book are approved, mark the version approved.
        remaining_unapproved = db.scalar(
            select(func.count(BookPage.id)).where(
                BookPage.book_id == book_id,
                BookPage.page_kind != "digital_text",
                BookPage.review_status != "approved",
            )
        )
        if int(remaining_unapproved or 0) == 0:
            version.status = "approved"

    db.commit()
    db.refresh(page)
    return {
        "book_id": book_id,
        "page_number": page.page_number,
        "review_status": page.review_status,
    }
