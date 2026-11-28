"""Phase 4 correction memory service: contextual storage, lookup, conflicts, and governance."""

from __future__ import annotations

import difflib
import logging
import re
import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.cache_state import bump_sentence_context_epoch
from src.common.logging_utils import log_event
from src.db.models import CorrectionMemory
from src.evaluation.metrics import normalize_nfc

LOGGER = logging.getLogger("telugu_digitizer.services.corrections")

ALLOWED_SCOPES = {"book_only", "global_suggestion"}
ALLOWED_STATUSES = {"active", "disabled", "superseded", "rejected"}

_TELUGU_LETTER_RE = re.compile(r"[\u0C05-\u0C39\u0C58-\u0C61]")
_DIGITS_AND_PUNCT_ONLY_RE = re.compile(r"^[\d\u0C66-\u0C6F\s\W_]+$")


def is_safe_auto_memory_rule(incorrect_span: str, corrected_span: str) -> tuple[bool, str | None]:
    """Filter out noisy/non-reusable spans (e.g., 'ర్మ -> 43' or full-line rewrites) during auto-capture."""
    inc = normalize_nfc(incorrect_span).strip()
    cor = normalize_nfc(corrected_span).strip()
    if not inc or not cor:
        return False, "empty_span"
    if inc == cor:
        return False, "identical_span"
    if _DIGITS_AND_PUNCT_ONLY_RE.fullmatch(cor):
        return False, "numeric_or_punctuation_target"
    if not _TELUGU_LETTER_RE.search(cor) or not _TELUGU_LETTER_RE.search(inc):
        return False, "non_telugu_span"
    inc_tokens = inc.split()
    cor_tokens = cor.split()
    if len(inc_tokens) > 2 or len(cor_tokens) > 3:
        return False, "span_too_wide"
    if len(inc) > 45 or len(cor) > 45:
        return False, "span_too_long"
    if len(inc) == 1 and len(cor) >= 4:
        return False, "single_char_expansion"
    return True, None


def extract_word_level_corrections(
    previous_text: str,
    edited_text: str,
    context_window: int = 2,
) -> list[tuple[str, str, str | None, str | None]]:
    """Extract individual replacement spans + contexts from a line edit (separating distinct fixes)."""
    prev_tokens = normalize_nfc(previous_text).split()
    edit_tokens = normalize_nfc(edited_text).split()
    if not prev_tokens or not edit_tokens:
        return []
    matcher = difflib.SequenceMatcher(None, prev_tokens, edit_tokens)
    results: list[tuple[str, str, str | None, str | None]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        src_slice = prev_tokens[i1:i2]
        dst_slice = edit_tokens[j1:j2]

        # When an adjacent stray OCR token was deleted/inserted next to a single word fix
        # (e.g., ['గ', 'అష్టాదశవర్ధనలు'] -> ['అష్టాదశవర్ణనలు']), isolate the closely matching word pair.
        if len(src_slice) > 1 and len(dst_slice) == 1:
            target_tok = dst_slice[0]
            best_idx, best_ratio = max(
                ((idx, difflib.SequenceMatcher(None, tok, target_tok).ratio()) for idx, tok in enumerate(src_slice)),
                key=lambda pair: pair[1],
            )
            if best_ratio >= 0.65:
                i1 = i1 + best_idx
                i2 = i1 + 1
                src_slice = [prev_tokens[i1]]
        elif len(src_slice) == 1 and len(dst_slice) > 1:
            source_tok = src_slice[0]
            best_idx, best_ratio = max(
                ((idx, difflib.SequenceMatcher(None, source_tok, tok).ratio()) for idx, tok in enumerate(dst_slice)),
                key=lambda pair: pair[1],
            )
            if best_ratio >= 0.65:
                j1 = j1 + best_idx
                j2 = j1 + 1
                dst_slice = [edit_tokens[j1]]

        inc = " ".join(src_slice).strip()
        cor = " ".join(dst_slice).strip()
        if not inc or not cor or inc == cor:
            continue
        # Strip matching edge punctuation on single-token replacements for cleaner reusable rules.
        if i2 - i1 == 1 and j2 - j1 == 1:
            l1, c1, r1 = _strip_edge_punctuation(inc)
            l2, c2, r2 = _strip_edge_punctuation(cor)
            if l1 == l2 and r1 == r2 and c1 and c2:
                inc, cor = c1, c2
        left_tokens = prev_tokens[max(0, i1 - context_window) : i1]
        right_tokens = prev_tokens[i2 : min(len(prev_tokens), i2 + context_window)]
        left_ctx = " ".join(left_tokens) if left_tokens else None
        right_ctx = " ".join(right_tokens) if right_tokens else None
        results.append((inc, cor, left_ctx, right_ctx))
    if not results:
        inc, cor, left_ctx, right_ctx = extract_span_and_context(previous_text, edited_text, context_window)
        if inc and cor and inc != cor:
            results.append((inc, cor, left_ctx, right_ctx))
    return results


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
    scope: str = "global_suggestion",
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
    inc = normalize_nfc(incorrect_text).strip()
    cor = normalize_nfc(corrected_text).strip()
    if not inc or not cor:
        raise AppError(
            "INVALID_CORRECTION_TEXT",
            "Both incorrect_text and corrected_text must be non-empty.",
            status_code=400,
        )

    norm_left = normalize_nfc(left_context).strip() if left_context and left_context.strip() else None
    norm_right = normalize_nfc(right_context).strip() if right_context and right_context.strip() else None
    norm_type = correction_type.strip() if correction_type and correction_type.strip() else None

    # Deduplicate if an identical rule with the same scope/book/context already exists.
    existing_stmt = select(CorrectionMemory).where(
        CorrectionMemory.language_code == language_code,
        CorrectionMemory.incorrect_text == inc,
        CorrectionMemory.corrected_text == cor,
        CorrectionMemory.scope == scope,
    )
    if scope == "book_only":
        existing_stmt = existing_stmt.where(CorrectionMemory.book_id == book_id)
    for candidate in db.scalars(existing_stmt).all():
        if candidate.left_context == norm_left and candidate.right_context == norm_right:
            candidate.approved_count += 1
            candidate.status = "active"
            if norm_type and not candidate.correction_type:
                candidate.correction_type = norm_type
            db.flush()
            return candidate

    entry = CorrectionMemory(
        language_code=language_code,
        incorrect_text=inc,
        corrected_text=cor,
        left_context=norm_left,
        right_context=norm_right,
        correction_type=norm_type,
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

    raw_trimmed = incorrect_text.strip()
    lookup_forms = list({target_nfc, raw_trimmed})
    stmt = select(CorrectionMemory).where(
        CorrectionMemory.language_code == language_code,
        CorrectionMemory.incorrect_text.in_(lookup_forms),
        CorrectionMemory.status == "active",
    )
    rows = list(db.scalars(stmt).all())

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


def build_suggestion_index(
    active_entries: list[CorrectionMemory],
    book_id: uuid.UUID,
) -> tuple[dict[str, list[CorrectionMemory]], dict[tuple[str, str], set[uuid.UUID]]]:
    """Pre-index active correction memory entries once per page review request."""
    by_incorrect: dict[str, list[CorrectionMemory]] = {}
    books_by_pair: dict[tuple[str, str], set[uuid.UUID]] = {}
    for entry in active_entries:
        if not (
            entry.scope == "global_suggestion"
            or (entry.scope == "book_only" and entry.book_id == book_id)
        ):
            continue
        inc_key = normalize_nfc(entry.incorrect_text).strip()
        cor_key = normalize_nfc(entry.corrected_text).strip()
        by_incorrect.setdefault(inc_key, []).append(entry)
        if entry.book_id is not None:
            books_by_pair.setdefault((inc_key, cor_key), set()).add(entry.book_id)
    return by_incorrect, books_by_pair


_EDGE_PUNCT = ".,!?;:\"'()[]{}—–-।॥"


def _strip_edge_punctuation(span: str) -> tuple[str, str, str]:
    """Split a token span into (leading_punct, core_text, trailing_punct)."""
    if not span:
        return "", "", ""
    start = 0
    end = len(span)
    while start < end and span[start] in _EDGE_PUNCT:
        start += 1
    while end > start and span[end - 1] in _EDGE_PUNCT:
        end -= 1
    return span[:start], span[start:end], span[end:]


_SPLIT_KEEP_WS_RE = re.compile(r"(\s+)")


def find_block_suggestions_from_index(
    *,
    by_incorrect: dict[str, list[CorrectionMemory]],
    books_by_pair: dict[tuple[str, str], set[uuid.UUID]],
    block_text: str,
    book_id: uuid.UUID,
    max_ngram: int = 4,
) -> list[dict[str, Any]]:
    """Find contextual correction candidates for one block while preserving original whitespace/newlines."""
    if not by_incorrect:
        return []
    parts = _SPLIT_KEEP_WS_RE.split(block_text)
    word_slots = [idx for idx, seg in enumerate(parts) if seg and not seg.isspace()]
    tokens = [parts[idx] for idx in word_slots]
    if not tokens:
        return []

    suggestions: list[dict[str, Any]] = []
    seen_ids: set[uuid.UUID] = set()

    for start in range(len(tokens)):
        for length in range(min(max_ngram, len(tokens) - start), 0, -1):
            span_tokens = tokens[start : start + length]
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
            if not candidates:
                continue

            left_ctx = " ".join(tokens[max(0, start - 2) : start]) or None
            right_ctx = " ".join(tokens[start + length : min(len(tokens), start + length + 2)]) or None
            distinct_targets = {normalize_nfc(c.corrected_text).strip() for c in candidates}
            has_conflict = len(distinct_targets) > 1

            first_part_idx = word_slots[start]
            last_part_idx = word_slots[start + length - 1]
            prefix_ws_preserved = "".join(parts[:first_part_idx])
            suffix_ws_preserved = "".join(parts[last_part_idx + 1 :])

            for entry in candidates:
                if entry.id in seen_ids:
                    continue
                seen_ids.add(entry.id)
                ctx_label, ctx_rank = _context_score(entry, left_ctx, right_ctx, book_id)
                replacement_span = f"{lead_punct}{entry.corrected_text}{trail_punct}"
                proposed_block_text = f"{prefix_ws_preserved}{replacement_span}{suffix_ws_preserved}"
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
                        "source_book_count": len(books_by_pair.get((lookup_key, cor_key), set())),
                        "has_conflict": has_conflict,
                        "proposed_block_text": proposed_block_text,
                    }
                )

    suggestions.sort(key=lambda s: s["_rank"], reverse=True)
    for s in suggestions:
        s.pop("_rank", None)
    return suggestions


def find_block_suggestions(
    *,
    active_entries: list[CorrectionMemory],
    block_text: str,
    book_id: uuid.UUID,
    max_ngram: int = 4,
) -> list[dict[str, Any]]:
    """Find contextual correction candidates for spans inside one OCR block without mutating text."""
    if not active_entries or not block_text:
        return []
    by_incorrect, books_by_pair = build_suggestion_index(active_entries, book_id)
    return find_block_suggestions_from_index(
        by_incorrect=by_incorrect,
        books_by_pair=books_by_pair,
        block_text=block_text,
        book_id=book_id,
        max_ngram=max_ngram,
    )


def approve_correction(db: Session, correction_id: uuid.UUID) -> CorrectionMemory:
    """Record positive confirmation on an active correction memory record."""
    entry = db.get(CorrectionMemory, correction_id)
    if entry is None:
        raise AppError("CORRECTION_NOT_FOUND", f"Correction {correction_id} not found.", status_code=404)
    entry.approved_count += 1
    db.commit()
    bump_sentence_context_epoch()
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
    bump_sentence_context_epoch()
    db.refresh(entry)
    return entry


def update_correction_status(
    db: Session,
    correction_id: uuid.UUID,
    status: str,
    scope: str | None = None,
) -> CorrectionMemory:
    """Update governance state ('active' | 'disabled' | 'superseded' | 'rejected') and optional scope."""
    if status not in ALLOWED_STATUSES:
        raise AppError(
            "INVALID_CORRECTION_STATUS",
            f"Unsupported status {status!r}. Allowed: {sorted(ALLOWED_STATUSES)}.",
            status_code=400,
        )
    if scope is not None and scope not in ALLOWED_SCOPES:
        raise AppError(
            "INVALID_CORRECTION_SCOPE",
            f"Unsupported scope {scope!r}. Allowed: {sorted(ALLOWED_SCOPES)}.",
            status_code=400,
        )
    entry = db.get(CorrectionMemory, correction_id)
    if entry is None:
        raise AppError("CORRECTION_NOT_FOUND", f"Correction {correction_id} not found.", status_code=404)
    entry.status = status
    if scope is not None:
        if scope == "book_only" and entry.book_id is None:
            raise AppError(
                "BOOK_ID_REQUIRED",
                "Cannot set scope='book_only' on a correction record without a source book_id.",
                status_code=400,
            )
        entry.scope = scope
    db.commit()
    bump_sentence_context_epoch()
    db.refresh(entry)
    return entry


def list_corrections(
    *,
    db: Session,
    book_id: uuid.UUID | None = None,
    status: str | None = None,
    query: str | None = None,
    language_code: str = "te",
    limit: int = 200,
    offset: int = 0,
) -> list[CorrectionMemory]:
    """List correction memory records with SQL filtering and bounded pagination."""
    stmt = select(CorrectionMemory).where(CorrectionMemory.language_code == language_code)
    if book_id is not None:
        stmt = stmt.where(CorrectionMemory.book_id == book_id)
    if status is not None:
        if status not in ALLOWED_STATUSES:
            raise AppError("INVALID_CORRECTION_STATUS", f"Unsupported status {status!r}.", status_code=400)
        stmt = stmt.where(CorrectionMemory.status == status)
    if query and query.strip():
        q_nfc = normalize_nfc(query).strip()
        pat = f"%{q_nfc}%"
        stmt = stmt.where(
            or_(
                CorrectionMemory.incorrect_text.ilike(pat),
                CorrectionMemory.corrected_text.ilike(pat),
            )
        )
    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    return list(
        db.scalars(
            stmt.order_by(CorrectionMemory.created_at.desc(), CorrectionMemory.id.desc())
            .limit(safe_limit)
            .offset(safe_offset)
        ).all()
    )
