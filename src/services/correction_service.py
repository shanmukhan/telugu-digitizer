"""Phase 4 correction memory service: contextual storage, lookup, conflicts, and governance."""

from __future__ import annotations

import difflib
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.logging_utils import log_event
from src.db.models import CorrectionMemory
from src.evaluation.metrics import normalize_nfc

LOGGER = logging.getLogger("telugu_digitizer.services.corrections")

ALLOWED_SCOPES = {"book_only", "global_suggestion"}
ALLOWED_STATUSES = {"active", "disabled", "superseded", "rejected"}


def extract_span_and_context(
    previous_text: str,
    edited_text: str,
    context_window: int = 2,
) -> tuple[str, str, str | None, str | None]:
    """Extract the minimal changed token span and surrounding left/right context tokens."""
    prev_tokens = previous_text.split()
    edit_tokens = edited_text.split()
    if not prev_tokens or not edit_tokens:
        return previous_text.strip(), edited_text.strip(), None, None

    matcher = difflib.SequenceMatcher(None, prev_tokens, edit_tokens)
    changed_opcodes = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    if not changed_opcodes:
        return previous_text.strip(), edited_text.strip(), None, None

    i1 = changed_opcodes[0][1]
    i2 = changed_opcodes[-1][2]
    j1 = changed_opcodes[0][3]
    j2 = changed_opcodes[-1][4]

    # Expand pure insertion/deletion slightly so incorrect_text is never empty.
    if i1 == i2:
        if i1 > 0:
            i1 -= 1
            j1 = max(0, j1 - 1)
        elif i2 < len(prev_tokens):
            i2 += 1
            j2 = min(len(edit_tokens), j2 + 1)
    if j1 == j2:
        if j1 > 0:
            j1 -= 1
            i1 = max(0, i1 - 1)
        elif j2 < len(edit_tokens):
            j2 += 1
            i2 = min(len(prev_tokens), i2 + 1)

    incorrect_span = " ".join(prev_tokens[i1:i2]).strip()
    corrected_span = " ".join(edit_tokens[j1:j2]).strip()
    if not incorrect_span or not corrected_span:
        return previous_text.strip(), edited_text.strip(), None, None

    left_tokens = prev_tokens[max(0, i1 - context_window) : i1]
    right_tokens = prev_tokens[i2 : min(len(prev_tokens), i2 + context_window)]
    left_ctx = " ".join(left_tokens) if left_tokens else None
    right_ctx = " ".join(right_tokens) if right_tokens else None
    return incorrect_span, corrected_span, left_ctx, right_ctx


def _context_score(
    entry: CorrectionMemory,
    query_left: str | None,
    query_right: str | None,
    query_book_id: uuid.UUID | None,
) -> tuple[str, int]:
    """Compute heuristic application context_match ('strong' | 'medium' | 'weak') and sort rank."""
    q_left_tokens = normalize_nfc(query_left or "").split()
    q_right_tokens = normalize_nfc(query_right or "").split()
    e_left_tokens = normalize_nfc(entry.left_context or "").split()
    e_right_tokens = normalize_nfc(entry.right_context or "").split()

    left_match = bool(
        e_left_tokens
        and q_left_tokens
        and q_left_tokens[-len(e_left_tokens) :] == e_left_tokens
    )
    right_match = bool(
        e_right_tokens
        and q_right_tokens
        and q_right_tokens[: len(e_right_tokens)] == e_right_tokens
    )
    same_book = bool(query_book_id is not None and entry.book_id == query_book_id)

    if left_match and right_match:
        return "strong", 3
    if (left_match and not e_right_tokens) or (right_match and not e_left_tokens):
        return "strong", 3
    if left_match or right_match or (entry.scope == "book_only" and same_book):
        return "medium", 2
    if same_book:
        return "medium", 2
    return "weak", 1


def create_correction_memory_entry(
    *,
    db: Session,
    incorrect_text: str,
    corrected_text: str,
    left_context: str | None = None,
    right_context: str | None = None,
    correction_type: str | None = None,
    scope: str = "book_only",
    book_id: uuid.UUID | None = None,
    source_ocr_block_id: uuid.UUID | None = None,
    language_code: str = "te",
) -> CorrectionMemory:
    """Create a contextual correction memory record (never globally auto-applied)."""
    if scope not in ALLOWED_SCOPES:
        raise AppError(
            "INVALID_CORRECTION_SCOPE",
            f"Unsupported scope {scope!r}. Allowed: {sorted(ALLOWED_SCOPES)}.",
            status_code=400,
        )
    if scope == "book_only" and book_id is None:
        raise AppError(
            "BOOK_ID_REQUIRED",
            "book_id is required when scope='book_only'.",
            status_code=400,
        )
    inc = incorrect_text.strip()
    cor = corrected_text.strip()
    if not inc or not cor:
        raise AppError(
            "INVALID_CORRECTION_TEXT",
            "Both incorrect_text and corrected_text must be non-empty.",
            status_code=400,
        )

    entry = CorrectionMemory(
        language_code=language_code,
        incorrect_text=inc,
        corrected_text=cor,
        left_context=left_context.strip() if left_context and left_context.strip() else None,
        right_context=right_context.strip() if right_context and right_context.strip() else None,
        correction_type=correction_type.strip() if correction_type and correction_type.strip() else None,
        scope=scope,
        book_id=book_id,
        source_ocr_block_id=source_ocr_block_id,
        status="active",
        approved_count=1,
        rejected_count=0,
    )
    db.add(entry)
    db.flush()
    log_event(
        LOGGER,
        logging.INFO,
        "Created correction memory candidate",
        correction_id=str(entry.id),
        scope=scope,
        book_id=str(book_id) if book_id else None,
    )
    return entry


def search_corrections(
    *,
    db: Session,
    incorrect_text: str,
    left_context: str | None = None,
    right_context: str | None = None,
    book_id: uuid.UUID | None = None,
    language_code: str = "te",
) -> list[dict[str, Any]]:
    """Search active correction memory candidates respecting scope and contextual matching."""
    target_nfc = normalize_nfc(incorrect_text).strip()
    if not target_nfc:
        return []

    rows = list(
        db.scalars(
            select(CorrectionMemory).where(
                CorrectionMemory.language_code == language_code,
                CorrectionMemory.status == "active",
            )
        ).all()
    )

    matched: list[CorrectionMemory] = []
    for row in rows:
        if row.scope == "book_only":
            if book_id is None or row.book_id != book_id:
                continue
        if normalize_nfc(row.incorrect_text).strip() == target_nfc:
            matched.append(row)

    if not matched:
        return []

    distinct_corrections = {normalize_nfc(r.corrected_text).strip() for r in matched}
    has_conflict = len(distinct_corrections) > 1

    books_by_corrected: dict[str, set[uuid.UUID]] = {}
    for row in matched:
        key = normalize_nfc(row.corrected_text).strip()
        if row.book_id is not None:
            books_by_corrected.setdefault(key, set()).add(row.book_id)

    scored: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []
    for row in matched:
        ctx_label, ctx_rank = _context_score(row, left_context, right_context, book_id)
        same_book = 1 if (book_id is not None and row.book_id == book_id) else 0
        net_evidence = row.approved_count - row.rejected_count
        cor_key = normalize_nfc(row.corrected_text).strip()
        src_books = len(books_by_corrected.get(cor_key, set()))
        item = {
            "correction_id": row.id,
            "incorrect_text": row.incorrect_text,
            "corrected_text": row.corrected_text,
            "left_context": row.left_context,
            "right_context": row.right_context,
            "correction_type": row.correction_type,
            "scope": row.scope,
            "status": row.status,
            "book_id": row.book_id,
            "approved_count": row.approved_count,
            "rejected_count": row.rejected_count,
            "context_match": ctx_label,
            "source_book_count": src_books,
            "has_conflict": has_conflict,
            "created_at": row.created_at,
        }
        scored.append(((ctx_rank, same_book, net_evidence, row.approved_count), item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [pair[1] for pair in scored]


def find_block_suggestions(
    *,
    active_entries: list[CorrectionMemory],
    block_text: str,
    book_id: uuid.UUID,
    max_ngram: int = 4,
) -> list[dict[str, Any]]:
    """Find contextual correction candidates for spans inside one OCR block without mutating text."""
    tokens = block_text.split()
    if not tokens or not active_entries:
        return []

    visible_entries = [
        e
        for e in active_entries
        if e.scope == "global_suggestion" or (e.scope == "book_only" and e.book_id == book_id)
    ]
    if not visible_entries:
        return []

    by_incorrect: dict[str, list[CorrectionMemory]] = {}
    books_by_pair: dict[tuple[str, str], set[uuid.UUID]] = {}
    for entry in visible_entries:
        inc_key = normalize_nfc(entry.incorrect_text).strip()
        cor_key = normalize_nfc(entry.corrected_text).strip()
        by_incorrect.setdefault(inc_key, []).append(entry)
        if entry.book_id is not None:
            books_by_pair.setdefault((inc_key, cor_key), set()).add(entry.book_id)

    suggestions: list[dict[str, Any]] = []
    seen_ids: set[uuid.UUID] = set()

    for start in range(len(tokens)):
        for length in range(min(max_ngram, len(tokens) - start), 0, -1):
            span_tokens = tokens[start : start + length]
            span_raw = " ".join(span_tokens)
            span_nfc = normalize_nfc(span_raw).strip()
            candidates = by_incorrect.get(span_nfc)
            if not candidates:
                continue

            left_ctx = " ".join(tokens[max(0, start - 2) : start]) or None
            right_ctx = " ".join(tokens[start + length : min(len(tokens), start + length + 2)]) or None
            distinct_targets = {normalize_nfc(c.corrected_text).strip() for c in candidates}
            has_conflict = len(distinct_targets) > 1

            for entry in candidates:
                if entry.id in seen_ids:
                    continue
                seen_ids.add(entry.id)
                ctx_label, ctx_rank = _context_score(entry, left_ctx, right_ctx, book_id)
                proposed_tokens = tokens[:start] + entry.corrected_text.split() + tokens[start + length :]
                proposed_block_text = " ".join(proposed_tokens)
                cor_key = normalize_nfc(entry.corrected_text).strip()
                suggestions.append(
                    {
                        "_rank": (ctx_rank, 1 if entry.book_id == book_id else 0, entry.approved_count - entry.rejected_count),
                        "correction_id": entry.id,
                        "incorrect_text": entry.incorrect_text,
                        "corrected_text": entry.corrected_text,
                        "left_context": entry.left_context,
                        "right_context": entry.right_context,
                        "correction_type": entry.correction_type,
                        "scope": entry.scope,
                        "status": entry.status,
                        "approved_count": entry.approved_count,
                        "rejected_count": entry.rejected_count,
                        "context_match": ctx_label,
                        "source_book_count": len(books_by_pair.get((span_nfc, cor_key), set())),
                        "has_conflict": has_conflict,
                        "proposed_block_text": proposed_block_text,
                    }
                )

    suggestions.sort(key=lambda s: s["_rank"], reverse=True)
    for s in suggestions:
        s.pop("_rank", None)
    return suggestions


def approve_correction(db: Session, correction_id: uuid.UUID) -> CorrectionMemory:
    """Record positive confirmation on an active correction memory record."""
    entry = db.get(CorrectionMemory, correction_id)
    if entry is None:
        raise AppError("CORRECTION_NOT_FOUND", f"Correction {correction_id} not found.", status_code=404)
    entry.approved_count += 1
    db.commit()
    db.refresh(entry)
    return entry


def reject_correction(
    db: Session,
    correction_id: uuid.UUID,
    *,
    disable: bool = False,
) -> CorrectionMemory:
    """Record rejection evidence; preserve record rather than erasing negative evidence."""
    entry = db.get(CorrectionMemory, correction_id)
    if entry is None:
        raise AppError("CORRECTION_NOT_FOUND", f"Correction {correction_id} not found.", status_code=404)
    entry.rejected_count += 1
    if disable:
        entry.status = "rejected"
    db.commit()
    db.refresh(entry)
    return entry


def update_correction_status(
    db: Session,
    correction_id: uuid.UUID,
    status: str,
) -> CorrectionMemory:
    """Update governance state ('active' | 'disabled' | 'superseded' | 'rejected')."""
    if status not in ALLOWED_STATUSES:
        raise AppError(
            "INVALID_CORRECTION_STATUS",
            f"Unsupported status {status!r}. Allowed: {sorted(ALLOWED_STATUSES)}.",
            status_code=400,
        )
    entry = db.get(CorrectionMemory, correction_id)
    if entry is None:
        raise AppError("CORRECTION_NOT_FOUND", f"Correction {correction_id} not found.", status_code=404)
    entry.status = status
    db.commit()
    db.refresh(entry)
    return entry


def list_corrections(
    *,
    db: Session,
    book_id: uuid.UUID | None = None,
    status: str | None = None,
    query: str | None = None,
    language_code: str = "te",
) -> list[CorrectionMemory]:
    """List correction memory records for governance and audit inspection."""
    stmt = select(CorrectionMemory).where(CorrectionMemory.language_code == language_code)
    if book_id is not None:
        stmt = stmt.where(CorrectionMemory.book_id == book_id)
    if status is not None:
        if status not in ALLOWED_STATUSES:
            raise AppError("INVALID_CORRECTION_STATUS", f"Unsupported status {status!r}.", status_code=400)
        stmt = stmt.where(CorrectionMemory.status == status)
    rows = list(db.scalars(stmt.order_by(CorrectionMemory.created_at.desc())).all())
    if query and query.strip():
        q_nfc = normalize_nfc(query).strip()
        rows = [
            r
            for r in rows
            if q_nfc in normalize_nfc(r.incorrect_text) or q_nfc in normalize_nfc(r.corrected_text)
        ]
    return rows
