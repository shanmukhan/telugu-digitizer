"""OCR Calibration phase orchestration, word/pattern learning, and safe remaining-page auto-application."""

from __future__ import annotations

import difflib
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.cache_state import bump_sentence_context_epoch
from src.common.logging_utils import log_event
from src.core.config import AppSettings
from src.db.models import (
    Book,
    BookPage,
    CorrectionMemory,
    DocumentTextBlock,
    DocumentTextVersion,
    OCRBlock,
    OCRRun,
    ReviewEdit,
)
from src.evaluation.metrics import normalize_nfc
from src.services.correction_service import (
    _context_score,
    _strip_edge_punctuation,
    build_suggestion_index,
    compute_reliability_score,
    create_correction_memory_entry,
    extract_word_level_corrections,
    is_safe_auto_memory_rule,
    normalize_lookup_form,
)

LOGGER = logging.getLogger("telugu_digitizer.services.calibration")

ALLOWED_PROCESSING_STATES = {
    "uploaded",
    "calibration_pending",
    "calibration_processing",
    "calibration_review",
    "calibration_completed",
    "remaining_processing",
    "review_in_progress",
    "completed",
    "paused",
}

_SPLIT_KEEP_WS_RE = re.compile(r"(\s+)")
_TELUGU_WORD_RE = re.compile(r"^[\u0C00-\u0C63\u0C78-\u0C7F\u200C\u200D]+$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def validate_calibration_config(
    *,
    page_count: int,
    start_page: int,
    calibration_page_count: int,
    end_page: int | None = None,
) -> tuple[int, int, int, int]:
    """Validate PDF starting page, calibration count, and optional ending page.

    Returns ``(start_page, calibration_page_count, calibration_range_end, effective_end_page)``.
    """
    if page_count <= 0:
        raise AppError("EMPTY_BOOK", "Book has no pages.", status_code=400)
    if start_page < 1 or start_page > page_count:
        raise AppError(
            "INVALID_CALIBRATION_START_PAGE",
            f"PDF starting page must be between 1 and {page_count} (got {start_page}).",
            status_code=400,
        )
    if calibration_page_count < 1:
        raise AppError(
            "INVALID_CALIBRATION_PAGE_COUNT",
            "Calibration page count must be at least 1.",
            status_code=400,
        )
    cal_end = start_page + calibration_page_count - 1
    if cal_end > page_count:
        max_allowed = page_count - start_page + 1
        raise AppError(
            "CALIBRATION_RANGE_EXCEEDS_BOOK",
            f"Calibration range PDF pages {start_page}–{cal_end} exceeds total PDF pages ({page_count}). "
            f"Maximum calibration pages from page {start_page} is {max_allowed}.",
            status_code=400,
        )
    eff_end = page_count if end_page is None else int(end_page)
    if eff_end < cal_end or eff_end > page_count:
        raise AppError(
            "INVALID_END_PAGE",
            f"Ending PDF page must be between {cal_end} and {page_count} (got {eff_end}).",
            status_code=400,
        )
    return start_page, calibration_page_count, cal_end, eff_end


def extract_recurring_char_patterns(
    word_pairs: list[tuple[str, str]],
    *,
    min_distinct_words: int = 2,
) -> list[dict[str, Any]]:
    """Extract recurring compact Telugu character/diacritic confusion patterns across distinct calibrated words."""
    words_by_pattern: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for raw_inc, raw_cor in word_pairs:
        inc = normalize_nfc(raw_inc).strip()
        cor = normalize_nfc(raw_cor).strip()
        if not inc or not cor or inc == cor or " " in inc or " " in cor:
            continue
        matcher = difflib.SequenceMatcher(None, inc, cor)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "replace":
                continue
            src_seg = inc[i1:i2]
            dst_seg = cor[j1:j2]
            if 1 <= len(src_seg) <= 2 and 1 <= len(dst_seg) <= 2 and src_seg != dst_seg:
                words_by_pattern[(src_seg, dst_seg)].add((inc, cor))

    patterns: list[dict[str, Any]] = []
    for (src_seg, dst_seg), examples in words_by_pattern.items():
        if len(examples) >= min_distinct_words:
            patterns.append(
                {
                    "from_seq": src_seg,
                    "to_seq": dst_seg,
                    "occurrences": len(examples),
                    "examples": [f"{a} → {b}" for a, b in sorted(examples)[:4]],
                }
            )
    patterns.sort(key=lambda item: (-item["occurrences"], item["from_seq"]))
    return patterns


def derive_book_processing_state(
    db: Session,
    book: Book,
    *,
    runs: list[OCRRun] | None = None,
) -> str:
    """Derive the accurate live processing state for a book from persisted settings, OCR runs, and approvals."""
    book_runs = (
        runs
        if runs is not None
        else list(
            db.scalars(
                select(OCRRun).where(OCRRun.book_id == book.id).order_by(OCRRun.created_at.desc())
            ).all()
        )
    )
    active_runs = [r for r in book_runs if r.status in ("running", "queued")]
    if active_runs:
        for run in active_runs:
            phase = str((run.config or {}).get("run_phase") or "")
            if phase == "calibration":
                return "calibration_processing"
            if phase == "remaining":
                return "remaining_processing"
        if book.calibration_start_page and not book.calibration_completed_at:
            return "calibration_processing"
        return "remaining_processing"

    # Respect explicit paused state when no job is actively running.
    if book.processing_state == "paused":
        return "paused"

    # Check page approvals across configured book range (or entire book if unconfigured).
    start_p = book.calibration_start_page or 1
    end_p = book.calibration_end_page or book.page_count
    total_target_pages = max(1, end_p - start_p + 1)
    approved_target = int(
        db.scalar(
            select(func.count(BookPage.id)).where(
                BookPage.book_id == book.id,
                BookPage.page_number >= start_p,
                BookPage.page_number <= end_p,
                BookPage.review_status == "approved",
            )
        )
        or 0
    )
    if approved_target >= total_target_pages:
        return "completed"

    usable_runs = [r for r in book_runs if r.status in ("completed", "partial")]
    if not usable_runs:
        if book.calibration_start_page is not None:
            return "calibration_pending"
        return "uploaded"

    # Calibration configured: distinguish calibration_review vs calibration_completed vs review_in_progress.
    if book.calibration_start_page is not None and book.calibration_page_count is not None:
        cal_end = min(book.page_count, book.calibration_start_page + book.calibration_page_count - 1)
        has_remaining_run = any(
            str((r.config or {}).get("run_phase") or "") == "remaining"
            or (
                isinstance((r.config or {}).get("end_page"), int)
                and int((r.config or {})["end_page"]) > cal_end
            )
            for r in usable_runs
        )
        if has_remaining_run:
            return "review_in_progress"
        if book.calibration_completed_at is not None:
            return "calibration_completed"
        return "calibration_review"

    return "review_in_progress"


def get_book_calibration_status(db: Session, book_id: uuid.UUID) -> dict[str, Any]:
    """Return full calibration configuration, learned rules stats, and remaining-page metadata for a book."""
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    runs = list(
        db.scalars(
            select(OCRRun).where(OCRRun.book_id == book.id).order_by(OCRRun.created_at.desc())
        ).all()
    )
    state = derive_book_processing_state(db, book, runs=runs)

    start_page = book.calibration_start_page
    cal_count = book.calibration_page_count
    end_page = book.calibration_end_page or book.page_count
    cal_range_end = (
        min(book.page_count, start_page + cal_count - 1)
        if (start_page is not None and cal_count is not None)
        else None
    )

    if cal_range_end is not None and cal_range_end < end_page:
        rem_start: int | None = cal_range_end + 1
        rem_end: int | None = end_page
        rem_count = rem_end - rem_start + 1
    else:
        rem_start = None
        rem_end = None
        rem_count = 0

    cal_pages_approved = 0
    cal_pages_ocred = 0
    if start_page is not None and cal_range_end is not None:
        cal_pages_approved = int(
            db.scalar(
                select(func.count(BookPage.id)).where(
                    BookPage.book_id == book.id,
                    BookPage.page_number >= start_page,
                    BookPage.page_number <= cal_range_end,
                    BookPage.review_status == "approved",
                )
            )
            or 0
        )
        cal_pages_ocred = int(
            db.scalar(
                select(func.count(func.distinct(OCRBlock.book_page_id)))
                .join(BookPage, OCRBlock.book_page_id == BookPage.id)
                .where(
                    BookPage.book_id == book.id,
                    BookPage.page_number >= start_page,
                    BookPage.page_number <= cal_range_end,
                )
            )
            or 0
        )

    # Book-specific + book-originated active rules.
    book_rules = list(
        db.scalars(
            select(CorrectionMemory).where(
                CorrectionMemory.language_code == book.language_code,
                CorrectionMemory.status == "active",
                CorrectionMemory.book_id == book.id,
            )
        ).all()
    )
    targets_by_norm: dict[str, set[str]] = defaultdict(set)
    for r in book_rules:
        key = r.normalized_incorrect or normalize_lookup_form(r.incorrect_text)
        targets_by_norm[key].add(normalize_nfc(r.corrected_text).strip())
    conflicts_count = sum(1 for v in targets_by_norm.values() if len(v) > 1)

    char_patterns = extract_recurring_char_patterns(
        [(r.incorrect_text, r.corrected_text) for r in book_rules if r.approved_count > r.rejected_count]
    )

    auto_applied_blocks_count = int(
        db.scalar(
            select(func.count(func.distinct(ReviewEdit.ocr_block_id)))
            .join(OCRBlock, ReviewEdit.ocr_block_id == OCRBlock.id)
            .join(BookPage, OCRBlock.book_page_id == BookPage.id)
            .where(
                BookPage.book_id == book.id,
                ReviewEdit.action == "auto_applied",
            )
        )
        or 0
    )

    return {
        "book_id": book.id,
        "page_count": book.page_count,
        "processing_state": state,
        "calibration_start_page": start_page,
        "calibration_page_count": cal_count,
        "calibration_range_end": cal_range_end,
        "book_end_page": end_page,
        "skipped_front_pages_count": max(0, (start_page - 1)) if start_page is not None else 0,
        "remaining_start_page": rem_start,
        "remaining_end_page": rem_end,
        "remaining_pages_count": rem_count,
        "calibration_pages_ocred": cal_pages_ocred,
        "calibration_pages_approved": cal_pages_approved,
        "calibration_completed_at": book.calibration_completed_at,
        "learned_word_rules_count": len([r for r in book_rules if r.approved_count > r.rejected_count]),
        "learned_char_patterns": char_patterns,
        "conflicting_rules_count": conflicts_count,
        "auto_applied_blocks_count": auto_applied_blocks_count,
    }


def harvest_calibration_corrections(
    db: Session,
    book: Book,
) -> dict[str, int]:
    """Harvest any approved/corrected word-level edits from calibration pages into book-specific memory."""
    start_page = book.calibration_start_page or 1
    cal_end = (
        min(book.page_count, start_page + book.calibration_page_count - 1)
        if book.calibration_page_count
        else min(book.page_count, start_page + 4)
    )

    cal_pages = list(
        db.scalars(
            select(BookPage)
            .where(
                BookPage.book_id == book.id,
                BookPage.page_number >= start_page,
                BookPage.page_number <= cal_end,
            )
            .order_by(BookPage.page_number)
        ).all()
    )
    if not cal_pages:
        return {"created_rules": 0, "existing_rules": 0}

    page_num_by_id = {p.id: p.page_number for p in cal_pages}
    page_ids = list(page_num_by_id.keys())

    # Preload blocks on calibration pages that have human edits.
    blocks = list(
        db.scalars(select(OCRBlock).where(OCRBlock.book_page_id.in_(page_ids))).all()
    )
    if not blocks:
        return {"created_rules": 0, "existing_rules": 0}

    block_ids = [b.id for b in blocks]
    latest_edit_by_block: dict[uuid.UUID, ReviewEdit] = {}
    for edit in db.scalars(
        select(ReviewEdit)
        .where(
            ReviewEdit.ocr_block_id.in_(block_ids),
            ReviewEdit.action.in_(["corrected", "approved"]),
        )
        .order_by(ReviewEdit.created_at.asc(), ReviewEdit.id.asc())
    ).all():
        latest_edit_by_block[edit.ocr_block_id] = edit

    # Preload already-recorded (source_ocr_block_id, normalized_incorrect, corrected_text) to stay idempotent.
    existing_rules = list(
        db.scalars(
            select(CorrectionMemory).where(
                CorrectionMemory.language_code == book.language_code,
                CorrectionMemory.book_id == book.id,
            )
        ).all()
    )
    seen_from_block: set[tuple[uuid.UUID | None, str, str]] = {
        (
            r.source_ocr_block_id,
            r.normalized_incorrect or normalize_lookup_form(r.incorrect_text),
            normalize_nfc(r.corrected_text).strip(),
        )
        for r in existing_rules
    }

    created_count = 0
    existing_count = len(existing_rules)
    for blk in blocks:
        latest = latest_edit_by_block.get(blk.id)
        if latest is None:
            continue
        raw_txt = normalize_nfc(blk.raw_text).strip()
        edited_txt = normalize_nfc(latest.edited_text).strip()
        if not raw_txt or not edited_txt or raw_txt == edited_txt:
            continue

        pairs = extract_word_level_corrections(raw_txt, edited_txt)
        for inc, cor, left_ctx, right_ctx in pairs:
            ok, _ = is_safe_auto_memory_rule(inc, cor)
            if not ok:
                continue
            norm_inc = normalize_lookup_form(inc)
            cor_nfc = normalize_nfc(cor).strip()
            if (blk.id, norm_inc, cor_nfc) in seen_from_block:
                continue
            create_correction_memory_entry(
                db=db,
                incorrect_text=inc,
                corrected_text=cor,
                left_context=left_ctx,
                right_context=right_ctx,
                scope="book_only",
                book_id=book.id,
                source_ocr_block_id=blk.id,
                source_page_number=page_num_by_id.get(blk.book_page_id),
                language_code=book.language_code,
            )
            seen_from_block.add((blk.id, norm_inc, cor_nfc))
            created_count += 1

    return {"created_rules": created_count, "existing_rules": existing_count}


def complete_book_calibration(db: Session, book_id: uuid.UUID) -> dict[str, Any]:
    """Finalize calibration review, consolidate learned word rules, and mark calibration completed."""
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    harvested = harvest_calibration_corrections(db, book)
    book.calibration_completed_at = _utcnow()
    book.processing_state = "calibration_completed"
    db.commit()
    bump_sentence_context_epoch()
    db.refresh(book)

    status_payload = get_book_calibration_status(db, book.id)
    status_payload["newly_harvested_rules_count"] = harvested["created_rules"]
    log_event(
        LOGGER,
        logging.INFO,
        "Completed book OCR calibration",
        book_id=str(book.id),
        newly_harvested=harvested["created_rules"],
        learned_word_rules=status_payload["learned_word_rules_count"],
        char_patterns=len(status_payload["learned_char_patterns"]),
    )
    return status_payload


def update_book_processing_state(
    db: Session,
    book_id: uuid.UUID,
    processing_state: str,
) -> dict[str, Any]:
    """Persist an explicit book processing state (e.g., 'paused' when switching books, or resuming)."""
    if processing_state not in ALLOWED_PROCESSING_STATES:
        raise AppError(
            "INVALID_PROCESSING_STATE",
            f"Unsupported processing_state {processing_state!r}. Allowed: {sorted(ALLOWED_PROCESSING_STATES)}.",
            status_code=400,
        )
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)
    book.processing_state = processing_state
    db.commit()
    db.refresh(book)
    return get_book_calibration_status(db, book.id)


def _select_safe_candidate_for_span(
    *,
    candidates: list[CorrectionMemory],
    span_core: str,
    left_ctx: str | None,
    right_ctx: str | None,
    book_id: uuid.UUID,
    lexicon: Any | None,
) -> tuple[CorrectionMemory, str, float, str] | None:
    """Apply strict safety rules before auto-applying a learned correction to a span.

    Safety guarantees:
    1. Only active entries with positive net evidence (approved > rejected) and zero rejections.
    2. Book-specific ('book_only') rules for the current book take precedence over global rules.
    3. Conflicting targets for the same OCR word are NEVER auto-applied unless ONE target has a
       strictly stronger surrounding-word context match ('strong').
    4. Valid known Telugu words are NEVER blindly overwritten unless supported by a strong context
       match or repeated book-specific evidence (approved_count >= 2, rejected_count == 0).
    5. Cross-book global rules require repeated evidence (approved_count >= 2) to auto-apply.
    """
    eligible = [
        c
        for c in candidates
        if c.status == "active" and c.approved_count > c.rejected_count and c.rejected_count == 0
    ]
    if not eligible:
        return None

    # Book-specific scope precedence: if the current book has dedicated book_only rule(s), prefer them.
    book_specific = [c for c in eligible if c.scope == "book_only" and c.book_id == book_id]
    pool = book_specific if book_specific else eligible

    distinct_targets = {normalize_nfc(c.corrected_text).strip() for c in pool}
    has_conflict = len(distinct_targets) > 1

    scored: list[tuple[tuple[int, int, int, int], CorrectionMemory, str, int]] = []
    for entry in pool:
        ctx_label, ctx_rank = _context_score(entry, left_ctx, right_ctx, book_id)
        is_book_rule = 1 if (entry.scope == "book_only" and entry.book_id == book_id) else 0
        same_book = 1 if entry.book_id == book_id else 0
        scored.append(((ctx_rank, is_book_rule, same_book, entry.approved_count), entry, ctx_label, ctx_rank))
    scored.sort(key=lambda item: item[0], reverse=True)

    best_tuple, best_entry, best_ctx_label, best_ctx_rank = scored[0]
    _ = best_tuple

    # Safety Rule 3: Conflict handling — only resolve via strictly stronger context match.
    if has_conflict:
        if best_ctx_label != "strong":
            return None
        best_target = normalize_nfc(best_entry.corrected_text).strip()
        for _score, other_entry, _other_label, other_rank in scored[1:]:
            if normalize_nfc(other_entry.corrected_text).strip() != best_target:
                if other_rank >= best_ctx_rank:
                    return None
                break

    # Safety Rule 5: Evidence threshold for cross-book global rules vs same-book rules.
    is_same_book = best_entry.book_id == book_id
    if not is_same_book and best_entry.approved_count < 2:
        return None

    # Safety Rule 4: Do not blindly overwrite a valid known Telugu word.
    is_known_valid = False
    if lexicon is not None and getattr(lexicon, "words", None) and " " not in span_core:
        try:
            is_known_valid = bool(lexicon.is_known_word(span_core))
        except Exception:
            is_known_valid = False

    if is_known_valid:
        strong_ctx = best_ctx_label == "strong"
        strong_book_evidence = (
            best_entry.scope == "book_only"
            and is_same_book
            and best_entry.approved_count >= 2
            and best_entry.rejected_count == 0
        )
        if not (strong_ctx or strong_book_evidence):
            return None

    reliability = compute_reliability_score(
        best_entry.approved_count,
        best_entry.rejected_count,
        has_conflict=has_conflict and best_ctx_label != "strong",
    )
    reason = (
        f"Book calibration rule ({best_ctx_label} context)"
        if is_same_book
        else f"Global memory rule ({best_ctx_label} context, +{best_entry.approved_count})"
    )
    return best_entry, best_ctx_label, reliability, reason


def apply_learned_corrections_to_page_blocks(
    *,
    db: Session,
    book: Book,
    page: BookPage,
    blocks: list[OCRBlock],
    lexicon_path: Path | None = None,
) -> int:
    """Safely apply learned calibration & memory corrections to newly OCR'd page blocks.

    Never mutates ``ocr_blocks.raw_text``. Persists append-only ``ReviewEdit(action='auto_applied')``
    rows with structured ``applied_rules`` provenance and updates the human draft version so
    reviewers can inspect, approve, revert, or reject any auto-applied correction.
    """
    if not blocks:
        return 0

    active_entries = list(
        db.scalars(
            select(CorrectionMemory).where(
                CorrectionMemory.language_code == book.language_code,
                CorrectionMemory.status == "active",
                CorrectionMemory.approved_count > CorrectionMemory.rejected_count,
                or_(
                    CorrectionMemory.scope == "global_suggestion",
                    CorrectionMemory.book_id == book.id,
                ),
            )
        ).all()
    )
    if not active_entries:
        return 0

    by_incorrect, _books_by_pair = build_suggestion_index(active_entries, book.id)
    if not by_incorrect:
        return 0

    # Lazily load Telugu lexicon for valid-word protection and optional book char-pattern recovery.
    lexicon = None
    try:
        from src.services.lexicon_service import get_telugu_lexicon

        lexicon = get_telugu_lexicon(lexicon_path)
    except Exception:
        lexicon = None

    book_char_patterns = extract_recurring_char_patterns(
        [
            (e.incorrect_text, e.corrected_text)
            for e in active_entries
            if e.book_id == book.id and e.approved_count > e.rejected_count and e.rejected_count == 0
        ],
        min_distinct_words=2,
    )

    version: DocumentTextVersion | None = None
    auto_applied_blocks = 0
    used_entry_ids: set[uuid.UUID] = set()

    for blk in blocks:
        original_text = normalize_nfc(blk.raw_text)
        if not original_text.strip():
            continue

        parts = _SPLIT_KEEP_WS_RE.split(original_text)
        word_slots = [idx for idx, seg in enumerate(parts) if seg and not seg.isspace()]
        if not word_slots:
            continue

        tokens = [parts[idx] for idx in word_slots]
        applied_rules: list[dict[str, Any]] = []
        consumed_word_indices: set[int] = set()

        # Pass 1: Word & phrase memory rules (longest n-gram first, up to 3 tokens).
        idx = 0
        while idx < len(tokens):
            matched_len = 0
            for length in range(min(3, len(tokens) - idx), 0, -1):
                if any((idx + k) in consumed_word_indices for k in range(length)):
                    continue
                span_tokens = tokens[idx : idx + length]
                span_raw = " ".join(span_tokens)
                span_nfc = normalize_nfc(span_raw).strip()

                lead_punct = ""
                trail_punct = ""
                lookup_key = span_nfc
                candidates = by_incorrect.get(lookup_key)
                if not candidates:
                    lead_punct, core_span, trail_punct = _strip_edge_punctuation(span_nfc)
                    if core_span and core_span != span_nfc:
                        lookup_key = core_span
                        candidates = by_incorrect.get(lookup_key)
                else:
                    _, core_span, _ = _strip_edge_punctuation(span_nfc)

                if not candidates:
                    continue

                left_ctx = " ".join(tokens[max(0, idx - 2) : idx]) or None
                right_ctx = " ".join(tokens[idx + length : min(len(tokens), idx + length + 2)]) or None
                selected = _select_safe_candidate_for_span(
                    candidates=candidates,
                    span_core=core_span or lookup_key,
                    left_ctx=left_ctx,
                    right_ctx=right_ctx,
                    book_id=book.id,
                    lexicon=lexicon,
                )
                if selected is None:
                    continue

                entry, ctx_label, reliability, reason = selected
                replacement_span = f"{lead_punct}{entry.corrected_text}{trail_punct}"
                if normalize_nfc(replacement_span) == span_nfc:
                    continue

                # Apply replacement into parts preserving exact external whitespace.
                first_part = word_slots[idx]
                last_part = word_slots[idx + length - 1]
                parts[first_part] = replacement_span
                for p_idx in range(first_part + 1, last_part + 1):
                    parts[p_idx] = ""
                for k in range(length):
                    consumed_word_indices.add(idx + k)
                used_entry_ids.add(entry.id)
                applied_rules.append(
                    {
                        "correction_id": str(entry.id),
                        "original": span_nfc,
                        "replacement": replacement_span,
                        "scope": entry.scope,
                        "unit_type": entry.unit_type or "word",
                        "context_match": ctx_label,
                        "confidence": reliability,
                        "reason": reason,
                    }
                )
                matched_len = length
                break
            idx += matched_len if matched_len > 0 else 1

        # Pass 2: Recurring book-specific character confusion patterns on unknown Telugu words.
        if book_char_patterns and lexicon is not None and getattr(lexicon, "words", None):
            for w_idx, part_idx in enumerate(word_slots):
                if w_idx in consumed_word_indices:
                    continue
                tok = parts[part_idx]
                lead_p, core, trail_p = _strip_edge_punctuation(normalize_nfc(tok))
                if not core or len(core) < 4 or not _TELUGU_WORD_RE.fullmatch(core):
                    continue
                if lexicon.is_known_word(core):
                    continue
                pattern_candidates: list[tuple[int, str, dict[str, Any]]] = []
                for pat in book_char_patterns[:6]:
                    f_seq = pat["from_seq"]
                    t_seq = pat["to_seq"]
                    if f_seq not in core:
                        continue
                    # Try single occurrence replacement at each matching offset.
                    start_pos = 0
                    while True:
                        pos = core.find(f_seq, start_pos)
                        if pos == -1:
                            break
                        cand = core[:pos] + t_seq + core[pos + len(f_seq) :]
                        if cand != core and lexicon.has_exact(cand):
                            weight = int(lexicon.words.get(cand, 0))
                            if weight >= 15:
                                pattern_candidates.append((weight, cand, pat))
                        start_pos = pos + 1
                unique_words = {c[1] for c in pattern_candidates}
                if len(unique_words) == 1:
                    best_weight, best_word, best_pat = max(pattern_candidates, key=lambda x: x[0])
                    _ = best_weight
                    parts[part_idx] = f"{lead_p}{best_word}{trail_p}"
                    applied_rules.append(
                        {
                            "correction_id": None,
                            "original": core,
                            "replacement": best_word,
                            "scope": "book_only",
                            "unit_type": "char_pattern",
                            "context_match": "book_pattern",
                            "confidence": 0.91,
                            "reason": (
                                f"Book calibration char pattern ({best_pat['from_seq']}→{best_pat['to_seq']}, "
                                f"seen in {best_pat['occurrences']} words)"
                            ),
                        }
                    )

        if not applied_rules:
            continue

        updated_text = "".join(parts)
        if normalize_nfc(updated_text).strip() == original_text.strip():
            continue

        if version is None:
            version = _get_or_create_human_draft_version(db, book.id)

        db.add(
            ReviewEdit(
                ocr_block_id=blk.id,
                previous_text=blk.raw_text,
                edited_text=updated_text,
                action="auto_applied",
                reviewer_id="system:calibration",
                review_note=f"Auto-applied {len(applied_rules)} calibration correction(s)",
                applied_rules=applied_rules,
            )
        )
        db.add(
            DocumentTextBlock(
                version_id=version.id,
                book_page_id=page.id,
                ocr_block_id=blk.id,
                final_text=updated_text,
                reading_order=blk.reading_order if blk.reading_order is not None else blk.block_index,
                block_role="paragraph",
            )
        )
        auto_applied_blocks += 1

    if used_entry_ids:
        now = _utcnow()
        for entry in active_entries:
            if entry.id in used_entry_ids:
                entry.last_used_at = now

    return auto_applied_blocks


def start_book_calibration(
    *,
    db: Session,
    executor: Any,
    settings: AppSettings,
    book_id: uuid.UUID,
    start_page: int,
    calibration_page_count: int,
    end_page: int | None = None,
    engines: list[str] | None = None,
    render_dpi: int = 300,
    preprocessing_profile: str = "none",
    tesseract_psm: int = 6,
    include_digital_text_pages: bool = False,
    force_rerun: bool = False,
) -> dict[str, Any]:
    """Persist calibration settings on Book and start OCR strictly on the selected calibration range."""
    from src.services.ocr_service import create_or_reuse_ocr_runs

    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    s_page, cal_cnt, cal_end, eff_end = validate_calibration_config(
        page_count=book.page_count,
        start_page=start_page,
        calibration_page_count=calibration_page_count,
        end_page=end_page,
    )

    book.calibration_start_page = s_page
    book.calibration_page_count = cal_cnt
    book.calibration_end_page = eff_end
    book.calibration_completed_at = None
    book.processing_state = "calibration_processing"
    db.commit()

    selected_engines = engines or ["paddle_ppocrv5_te", "tesseract_tel_best"]
    run_res = create_or_reuse_ocr_runs(
        db=db,
        executor=executor,
        settings=settings,
        book_id=book.id,
        engines=selected_engines,
        start_page=s_page,
        end_page=cal_end,
        render_dpi=render_dpi,
        preprocessing_profile=preprocessing_profile,
        tesseract_psm=tesseract_psm,
        include_digital_text_pages=include_digital_text_pages,
        force_rerun=force_rerun,
        run_phase="calibration",
        apply_calibration_corrections=False,
    )
    if run_res.get("reused_existing") and run_res.get("status") == "completed":
        book.processing_state = "calibration_review"
        db.commit()

    return {
        **run_res,
        "calibration": get_book_calibration_status(db, book.id),
    }


def start_remaining_pages_ocr(
    *,
    db: Session,
    executor: Any,
    settings: AppSettings,
    book_id: uuid.UUID,
    engines: list[str] | None = None,
    render_dpi: int = 300,
    preprocessing_profile: str = "none",
    tesseract_psm: int = 6,
    include_digital_text_pages: bool = False,
    force_rerun: bool = False,
    apply_calibration_corrections: bool = True,
) -> dict[str, Any]:
    """Complete calibration learning and start OCR on remaining pages after the calibration range."""
    from src.services.ocr_service import create_or_reuse_ocr_runs

    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    # Always harvest any newly approved/corrected calibration edits before running remaining pages.
    harvest_calibration_corrections(db, book)
    if book.calibration_completed_at is None:
        book.calibration_completed_at = _utcnow()

    start_page = book.calibration_start_page or 1
    cal_count = book.calibration_page_count or min(5, book.page_count)
    cal_end = min(book.page_count, start_page + cal_count - 1)
    eff_end = book.calibration_end_page or book.page_count

    rem_start = cal_end + 1
    if rem_start > eff_end:
        book.processing_state = "review_in_progress"
        db.commit()
        raise AppError(
            "NO_REMAINING_PAGES",
            f"All pages in the configured range (PDF pages {start_page}–{eff_end}) were already included in calibration.",
            status_code=400,
        )

    book.processing_state = "remaining_processing"
    db.commit()
    bump_sentence_context_epoch()

    selected_engines = engines or ["paddle_ppocrv5_te", "tesseract_tel_best"]
    run_res = create_or_reuse_ocr_runs(
        db=db,
        executor=executor,
        settings=settings,
        book_id=book.id,
        engines=selected_engines,
        start_page=rem_start,
        end_page=eff_end,
        render_dpi=render_dpi,
        preprocessing_profile=preprocessing_profile,
        tesseract_psm=tesseract_psm,
        include_digital_text_pages=include_digital_text_pages,
        force_rerun=force_rerun,
        run_phase="remaining",
        apply_calibration_corrections=apply_calibration_corrections,
    )
    if run_res.get("reused_existing") and run_res.get("status") == "completed":
        book.processing_state = "review_in_progress"
        db.commit()

    return {
        **run_res,
        "calibration": get_book_calibration_status(db, book.id),
    }

