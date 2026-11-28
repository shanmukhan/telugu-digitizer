"""Phase 4+ correction memory service: word-level learning, contextual lookup, conflicts, and governance."""

from __future__ import annotations

import difflib
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.cache_state import bump_sentence_context_epoch
from src.common.logging_utils import log_event
from src.db.models import Book, CorrectionMemory
from src.evaluation.metrics import normalize_nfc

LOGGER = logging.getLogger("telugu_digitizer.services.corrections")

ALLOWED_SCOPES = {"book_only", "global_suggestion"}
ALLOWED_STATUSES = {"active", "disabled", "superseded", "rejected"}
ALLOWED_UNIT_TYPES = {"word", "char_pattern", "phrase"}

_TELUGU_LETTER_RE = re.compile(r"[\u0C05-\u0C39\u0C58-\u0C61]")
_DIGITS_AND_PUNCT_ONLY_RE = re.compile(r"^[\d\u0C66-\u0C6F\s\W_]+$")
_EDGE_PUNCT = ".,!?;:\"'()[]{}—–-।॥“”‘’"
_SPLIT_KEEP_WS_RE = re.compile(r"(\s+)")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


def normalize_lookup_form(text: str) -> str:
    """Compute canonical NFC, edge-punctuation-trimmed lookup form for correction matching."""
    cleaned = " ".join(normalize_nfc(text).strip().split())
    if not cleaned:
        return ""
    _, core, _ = _strip_edge_punctuation(cleaned)
    return core if core else cleaned


def classify_unit_type(
    incorrect_text: str,
    corrected_text: str,
    explicit_unit_type: str | None = None,
) -> str:
    """Classify a correction entry as 'word', 'char_pattern', or 'phrase'."""
    if explicit_unit_type in ALLOWED_UNIT_TYPES:
        return explicit_unit_type
    inc = normalize_nfc(incorrect_text).strip()
    cor = normalize_nfc(corrected_text).strip()
    inc_tokens = inc.split()
    cor_tokens = cor.split()
    if len(inc_tokens) > 1 or len(cor_tokens) > 1:
        return "phrase"
    if len(inc) <= 2 and len(cor) <= 3:
        return "char_pattern"
    return "word"


def compute_reliability_score(
    approved_count: int,
    rejected_count: int,
    *,
    has_conflict: bool = False,
) -> float:
    """Compute a bounded [0.0, 0.99] reliability score from positive/negative evidence and conflicts."""
    pos = max(0, int(approved_count))
    neg = max(0, int(rejected_count))
    base = (pos + 0.5) / (pos + neg + 1.5)
    # Gently reward repeated human confirmation when rejections are absent or low.
    if neg == 0 and pos >= 4:
        base += 0.14
    elif neg == 0 and pos >= 2:
        base += 0.08
    elif pos > neg and pos >= 3:
        base += 0.04
    if has_conflict:
        base *= 0.62
    return round(max(0.05, min(0.99, base)), 3)


def is_safe_auto_memory_rule(incorrect_span: str, corrected_span: str) -> tuple[bool, str | None]:
    """Filter out noisy/non-reusable spans (e.g., 'ర్మ -> 43' or full-sentence rewrites) during auto-capture."""
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


def _strip_shared_edge_punct(inc: str, cor: str) -> tuple[str, str]:
    """Independently strip matching leading or trailing punctuation while preserving OCR-error punctuation."""
    l1, c1, r1 = _strip_edge_punctuation(inc)
    l2, c2, r2 = _strip_edge_punctuation(cor)
    if not c1 or not c2:
        return inc, cor
    eff_l1 = "" if (l1 == l2 and l1) else l1
    eff_l2 = "" if (l1 == l2 and l1) else l2
    eff_r1 = "" if (r1 == r2 and r1) else r1
    eff_r2 = "" if (r1 == r2 and r1) else r2
    cleaned_inc = f"{eff_l1}{c1}{eff_r1}".strip()
    cleaned_cor = f"{eff_l2}{c2}{eff_r2}".strip()
    return (cleaned_inc or inc), (cleaned_cor or cor)


def _align_unequal_word_slices(
    src_slice: list[str],
    dst_slice: list[str],
) -> list[tuple[int, int]]:
    """Monotonically pair closely matching tokens between unequal replacement slices."""
    m, n = len(src_slice), len(dst_slice)
    scores: list[list[float]] = [
        [difflib.SequenceMatcher(None, src_slice[i], dst_slice[j]).ratio() for j in range(n)]
        for i in range(m)
    ]
    # DP maximizing total similarity over monotonic 1-to-1 pairings (min similarity 0.42).
    dp = [[0.0] * (n + 1) for _ in range(m + 1)]
    back: list[list[tuple[int, int, bool]]] = [[(0, 0, False)] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            best_val = dp[i - 1][j]
            best_prev = (i - 1, j, False)
            if dp[i][j - 1] > best_val:
                best_val = dp[i][j - 1]
                best_prev = (i, j - 1, False)
            sim = scores[i - 1][j - 1]
            if sim >= 0.42 and dp[i - 1][j - 1] + sim > best_val:
                best_val = dp[i - 1][j - 1] + sim
                best_prev = (i - 1, j - 1, True)
            dp[i][j] = best_val
            back[i][j] = best_prev

    pairs: list[tuple[int, int]] = []
    i, j = m, n
    while i > 0 and j > 0:
        pi, pj, matched = back[i][j]
        if matched:
            pairs.append((i - 1, j - 1))
        i, j = pi, pj
    pairs.reverse()
    return pairs


def extract_word_level_corrections(
    previous_text: str,
    edited_text: str,
    context_window: int = 2,
) -> list[tuple[str, str, str | None, str | None]]:
    """Extract word-level replacement pairs + surrounding sentence context without sentence-level bloat.

    Splits adjacent multi-word edits (e.g., two consecutive misspelled words in a line) into
    independent word-to-word correction pairs so each word generalizes across the entire book.
    Phrase-level pairs are only emitted for genuine word-boundary splits/merges (<= 3 tokens).
    """
    prev_tokens = normalize_nfc(previous_text).split()
    edit_tokens = normalize_nfc(edited_text).split()
    if not prev_tokens or not edit_tokens:
        return []

    matcher = difflib.SequenceMatcher(None, prev_tokens, edit_tokens)
    results: list[tuple[str, str, str | None, str | None]] = []

    def _emit_pair(
        inc_raw: str,
        cor_raw: str,
        src_start: int,
        src_end: int,
        *,
        single_token: bool,
    ) -> None:
        inc = inc_raw.strip()
        cor = cor_raw.strip()
        if not inc or not cor or inc == cor:
            return
        if single_token:
            inc, cor = _strip_shared_edge_punct(inc, cor)
            if not inc or not cor or inc == cor:
                return
        left_tokens = prev_tokens[max(0, src_start - context_window) : src_start]
        right_tokens = prev_tokens[src_end : min(len(prev_tokens), src_end + context_window)]
        left_ctx = " ".join(left_tokens) if left_tokens else None
        right_ctx = " ".join(right_tokens) if right_tokens else None
        results.append((inc, cor, left_ctx, right_ctx))

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        src_slice = prev_tokens[i1:i2]
        dst_slice = edit_tokens[j1:j2]

        # Case 1: Clean single-word replacement.
        if len(src_slice) == 1 and len(dst_slice) == 1:
            _emit_pair(src_slice[0], dst_slice[0], i1, i2, single_token=True)
            continue

        # Case 2: Equal-length multi-word replacement (e.g. 2+ consecutive words fixed in one edit).
        # Split into individual word-to-word rules rather than storing a multi-word phrase/sentence.
        if len(src_slice) == len(dst_slice) and len(src_slice) > 1:
            ratios = [
                difflib.SequenceMatcher(None, src_slice[k], dst_slice[k]).ratio()
                for k in range(len(src_slice))
            ]
            avg_ratio = sum(ratios) / len(ratios)
            if avg_ratio >= 0.30 or len(src_slice) > 2:
                for k in range(len(src_slice)):
                    _emit_pair(src_slice[k], dst_slice[k], i1 + k, i1 + k + 1, single_token=True)
                continue

        # Case 3: Multi-token source -> single-token target (merged split word OR deleted stray OCR token).
        if len(src_slice) > 1 and len(dst_slice) == 1:
            target_tok = dst_slice[0]
            joined_src = "".join(src_slice)
            merge_ratio = difflib.SequenceMatcher(None, joined_src, target_tok).ratio()
            best_idx, best_ratio = max(
                (
                    (idx, difflib.SequenceMatcher(None, tok, target_tok).ratio())
                    for idx, tok in enumerate(src_slice)
                ),
                key=lambda pair: pair[1],
            )
            # Genuine word-boundary merge (e.g., "పుస్త కం" -> "పుస్తకం"):
            if len(src_slice) == 2 and merge_ratio >= 0.72 and merge_ratio > best_ratio + 0.08:
                _emit_pair(" ".join(src_slice), target_tok, i1, i2, single_token=False)
            elif best_ratio >= 0.55:
                _emit_pair(src_slice[best_idx], target_tok, i1 + best_idx, i1 + best_idx + 1, single_token=True)
            elif len(src_slice) <= 2:
                _emit_pair(" ".join(src_slice), target_tok, i1, i2, single_token=False)
            continue

        # Case 4: Single-token source -> multi-token target (split merged word OR inserted word).
        if len(src_slice) == 1 and len(dst_slice) > 1:
            source_tok = src_slice[0]
            joined_dst = "".join(dst_slice)
            split_ratio = difflib.SequenceMatcher(None, source_tok, joined_dst).ratio()
            best_idx, best_ratio = max(
                (
                    (idx, difflib.SequenceMatcher(None, source_tok, tok).ratio())
                    for idx, tok in enumerate(dst_slice)
                ),
                key=lambda pair: pair[1],
            )
            # Genuine word-boundary split (e.g., "అతడువచ్చాడు" -> "అతడు వచ్చాడు"):
            if len(dst_slice) <= 3 and split_ratio >= 0.72 and split_ratio > best_ratio + 0.08:
                _emit_pair(source_tok, " ".join(dst_slice), i1, i2, single_token=False)
            elif best_ratio >= 0.55:
                _emit_pair(source_tok, dst_slice[best_idx], i1, i2, single_token=True)
            elif len(dst_slice) <= 3:
                _emit_pair(source_tok, " ".join(dst_slice), i1, i2, single_token=False)
            continue

        # Case 5: Unequal multi-token slices -> align individual words monotonically instead of storing a sentence.
        aligned = _align_unequal_word_slices(src_slice, dst_slice)
        if aligned:
            for si, dj in aligned:
                _emit_pair(src_slice[si], dst_slice[dj], i1 + si, i1 + si + 1, single_token=True)
        elif len(src_slice) <= 2 and len(dst_slice) <= 3:
            _emit_pair(" ".join(src_slice), " ".join(dst_slice), i1, i2, single_token=False)

    # Only fall back to minimal span extraction for compact (<= 3 token) edits, never full sentences.
    if not results:
        inc, cor, left_ctx, right_ctx = extract_span_and_context(previous_text, edited_text, context_window)
        if inc and cor and inc != cor and len(inc.split()) <= 2 and len(cor.split()) <= 3:
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
    """Compute contextual match ('strong' | 'medium' | 'weak') and sort rank.

    Supports both full-window context matches and immediate-neighbor (1-word) context matches
    so surrounding sentence words disambiguate conflicting word corrections reliably.
    """
    q_left_tokens = [
        normalize_lookup_form(t) for t in normalize_nfc(query_left or "").split() if normalize_lookup_form(t)
    ]
    q_right_tokens = [
        normalize_lookup_form(t) for t in normalize_nfc(query_right or "").split() if normalize_lookup_form(t)
    ]
    e_left_tokens = [
        normalize_lookup_form(t)
        for t in normalize_nfc(entry.left_context or "").split()
        if normalize_lookup_form(t)
    ]
    e_right_tokens = [
        normalize_lookup_form(t)
        for t in normalize_nfc(entry.right_context or "").split()
        if normalize_lookup_form(t)
    ]

    exact_left = bool(
        e_left_tokens and q_left_tokens and q_left_tokens[-len(e_left_tokens) :] == e_left_tokens
    )
    near_left = bool(e_left_tokens and q_left_tokens and q_left_tokens[-1] == e_left_tokens[-1])
    exact_right = bool(
        e_right_tokens and q_right_tokens and q_right_tokens[: len(e_right_tokens)] == e_right_tokens
    )
    near_right = bool(e_right_tokens and q_right_tokens and q_right_tokens[0] == e_right_tokens[0])

    left_match = exact_left or near_left
    right_match = exact_right or near_right
    same_book = bool(query_book_id is not None and entry.book_id == query_book_id)

    if left_match and right_match:
        return "strong", 4
    if (exact_left and not e_right_tokens) or (exact_right and not e_left_tokens):
        return "strong", 3
    if (near_left and not e_right_tokens) or (near_right and not e_left_tokens):
        return "strong", 3
    if left_match or right_match:
        return "medium", 2
    if entry.scope == "book_only" and same_book:
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
    unit_type: str | None = None,
    scope: str = "global_suggestion",
    book_id: uuid.UUID | None = None,
    source_ocr_block_id: uuid.UUID | None = None,
    source_page_number: int | None = None,
    language_code: str = "te",
) -> CorrectionMemory:
    """Create or reinforce a word-level contextual correction memory record."""
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

    norm_inc = normalize_lookup_form(inc)
    eff_unit_type = classify_unit_type(inc, cor, unit_type)
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
            candidate.normalized_incorrect = norm_inc
            candidate.unit_type = eff_unit_type
            candidate.last_used_at = _utcnow()
            if norm_type and not candidate.correction_type:
                candidate.correction_type = norm_type
            if source_page_number is not None and candidate.source_page_number is None:
                candidate.source_page_number = source_page_number
            db.flush()
            return candidate

    entry = CorrectionMemory(
        language_code=language_code,
        incorrect_text=inc,
        normalized_incorrect=norm_inc,
        corrected_text=cor,
        left_context=norm_left,
        right_context=norm_right,
        correction_type=norm_type,
        unit_type=eff_unit_type,
        scope=scope,
        book_id=book_id,
        source_ocr_block_id=source_ocr_block_id,
        source_page_number=source_page_number,
        status="active",
        approved_count=1,
        rejected_count=0,
        last_used_at=_utcnow(),
    )
    db.add(entry)
    db.flush()
    log_event(
        LOGGER,
        logging.INFO,
        "Created correction memory candidate",
        correction_id=str(entry.id),
        scope=scope,
        unit_type=eff_unit_type,
        book_id=str(book_id) if book_id else None,
        source_page_number=source_page_number,
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
    """Search active correction memory candidates respecting scope precedence and contextual matching."""
    target_nfc = normalize_nfc(incorrect_text).strip()
    if not target_nfc:
        return []

    raw_trimmed = incorrect_text.strip()
    norm_target = normalize_lookup_form(target_nfc)
    lookup_forms = list({target_nfc, raw_trimmed, norm_target})
    stmt = select(CorrectionMemory).where(
        CorrectionMemory.language_code == language_code,
        CorrectionMemory.status == "active",
        or_(
            CorrectionMemory.incorrect_text.in_(lookup_forms),
            CorrectionMemory.normalized_incorrect == norm_target,
        ),
    )
    rows = list(db.scalars(stmt).all())

    matched: list[CorrectionMemory] = []
    for row in rows:
        if row.scope == "book_only":
            if book_id is None or row.book_id != book_id:
                continue
        row_nfc = normalize_nfc(row.incorrect_text).strip()
        row_norm = row.normalized_incorrect or normalize_lookup_form(row_nfc)
        if row_nfc == target_nfc or (norm_target and row_norm == norm_target):
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

    scored: list[tuple[tuple[int, int, int, int, int], dict[str, Any]]] = []
    for row in matched:
        ctx_label, ctx_rank = _context_score(row, left_context, right_context, book_id)
        is_book_specific = 1 if (row.scope == "book_only" and book_id is not None and row.book_id == book_id) else 0
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
            "unit_type": row.unit_type or "word",
            "scope": row.scope,
            "status": row.status,
            "book_id": row.book_id,
            "approved_count": row.approved_count,
            "rejected_count": row.rejected_count,
            "reliability_score": compute_reliability_score(
                row.approved_count, row.rejected_count, has_conflict=has_conflict
            ),
            "context_match": ctx_label,
            "source_book_count": src_books,
            "has_conflict": has_conflict,
            "created_at": row.created_at,
        }
        scored.append(((ctx_rank, is_book_specific, same_book, net_evidence, row.approved_count), item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [pair[1] for pair in scored]


def build_suggestion_index(
    active_entries: list[CorrectionMemory],
    book_id: uuid.UUID,
) -> tuple[dict[str, list[CorrectionMemory]], dict[tuple[str, str], set[uuid.UUID]]]:
    """Pre-index active correction memory entries once per page review/OCR request."""
    by_incorrect: dict[str, list[CorrectionMemory]] = {}
    books_by_pair: dict[tuple[str, str], set[uuid.UUID]] = {}
    seen_per_key: dict[str, set[uuid.UUID]] = {}
    for entry in active_entries:
        if not (
            entry.scope == "global_suggestion"
            or (entry.scope == "book_only" and entry.book_id == book_id)
        ):
            continue
        inc_key = normalize_nfc(entry.incorrect_text).strip()
        norm_key = getattr(entry, "normalized_incorrect", None) or normalize_lookup_form(inc_key)
        cor_key = normalize_nfc(entry.corrected_text).strip()

        for key in (inc_key, norm_key):
            if not key:
                continue
            bucket_seen = seen_per_key.setdefault(key, set())
            if entry.id not in bucket_seen:
                bucket_seen.add(entry.id)
                by_incorrect.setdefault(key, []).append(entry)
            if entry.book_id is not None:
                books_by_pair.setdefault((key, cor_key), set()).add(entry.book_id)
    return by_incorrect, books_by_pair


def find_block_suggestions_from_index(
    *,
    by_incorrect: dict[str, list[CorrectionMemory]],
    books_by_pair: dict[tuple[str, str], set[uuid.UUID]],
    block_text: str,
    book_id: uuid.UUID,
    max_ngram: int = 3,
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
                is_book_specific = 1 if (entry.scope == "book_only" and entry.book_id == book_id) else 0
                replacement_span = f"{lead_punct}{entry.corrected_text}{trail_punct}"
                proposed_block_text = f"{prefix_ws_preserved}{replacement_span}{suffix_ws_preserved}"
                cor_key = normalize_nfc(entry.corrected_text).strip()
                suggestions.append(
                    {
                        "_rank": (
                            ctx_rank,
                            is_book_specific,
                            1 if entry.book_id == book_id else 0,
                            entry.approved_count - entry.rejected_count,
                        ),
                        "correction_id": entry.id,
                        "incorrect_text": entry.incorrect_text,
                        "corrected_text": entry.corrected_text,
                        "left_context": entry.left_context,
                        "right_context": entry.right_context,
                        "correction_type": entry.correction_type,
                        "unit_type": getattr(entry, "unit_type", None) or "word",
                        "scope": entry.scope,
                        "status": entry.status,
                        "approved_count": entry.approved_count,
                        "rejected_count": entry.rejected_count,
                        "reliability_score": compute_reliability_score(
                            entry.approved_count,
                            entry.rejected_count,
                            has_conflict=has_conflict,
                        ),
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
    max_ngram: int = 3,
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
    entry.last_used_at = _utcnow()
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
    if disable or (entry.rejected_count >= 2 and entry.rejected_count >= entry.approved_count):
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


def update_correction_entry(
    db: Session,
    correction_id: uuid.UUID,
    *,
    corrected_text: str | None = None,
    left_context: str | None = None,
    right_context: str | None = None,
    correction_type: str | None = None,
    unit_type: str | None = None,
    scope: str | None = None,
    status: str | None = None,
    clear_context: bool = False,
) -> CorrectionMemory:
    """Edit an existing correction memory entry cleanly while preserving evidence history."""
    entry = db.get(CorrectionMemory, correction_id)
    if entry is None:
        raise AppError("CORRECTION_NOT_FOUND", f"Correction {correction_id} not found.", status_code=404)
    if status is not None:
        if status not in ALLOWED_STATUSES:
            raise AppError(
                "INVALID_CORRECTION_STATUS",
                f"Unsupported status {status!r}. Allowed: {sorted(ALLOWED_STATUSES)}.",
                status_code=400,
            )
        entry.status = status
    if scope is not None:
        if scope not in ALLOWED_SCOPES:
            raise AppError(
                "INVALID_CORRECTION_SCOPE",
                f"Unsupported scope {scope!r}. Allowed: {sorted(ALLOWED_SCOPES)}.",
                status_code=400,
            )
        if scope == "book_only" and entry.book_id is None:
            raise AppError(
                "BOOK_ID_REQUIRED",
                "Cannot set scope='book_only' on a correction record without a source book_id.",
                status_code=400,
            )
        entry.scope = scope
    if corrected_text is not None:
        cor = normalize_nfc(corrected_text).strip()
        if not cor:
            raise AppError("INVALID_CORRECTION_TEXT", "corrected_text must be non-empty.", status_code=400)
        entry.corrected_text = cor
    if clear_context:
        entry.left_context = None
        entry.right_context = None
    else:
        if left_context is not None:
            entry.left_context = normalize_nfc(left_context).strip() or None
        if right_context is not None:
            entry.right_context = normalize_nfc(right_context).strip() or None
    if correction_type is not None:
        entry.correction_type = correction_type.strip() or None
    if unit_type is not None:
        if unit_type not in ALLOWED_UNIT_TYPES:
            raise AppError(
                "INVALID_UNIT_TYPE",
                f"Unsupported unit_type {unit_type!r}. Allowed: {sorted(ALLOWED_UNIT_TYPES)}.",
                status_code=400,
            )
        entry.unit_type = unit_type
    else:
        entry.unit_type = classify_unit_type(entry.incorrect_text, entry.corrected_text)
    entry.normalized_incorrect = normalize_lookup_form(entry.incorrect_text)
    db.commit()
    bump_sentence_context_epoch()
    db.refresh(entry)
    return entry


def delete_correction_entry(db: Session, correction_id: uuid.UUID) -> None:
    """Permanently delete a correction memory entry."""
    entry = db.get(CorrectionMemory, correction_id)
    if entry is None:
        raise AppError("CORRECTION_NOT_FOUND", f"Correction {correction_id} not found.", status_code=404)
    db.delete(entry)
    db.commit()
    bump_sentence_context_epoch()


def normalize_legacy_phrase_rules(
    db: Session,
    *,
    language_code: str = "te",
    book_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Split legacy multi-word phrase rules into reusable word-level rules and strip shared edge punctuation.

    Preserves genuine compact word-boundary merges/splits (e.g. 'పుస్త కం -> పుస్తకం') while
    decomposing multi-word edits (e.g. 'పబ్లీషన్ హ్రౌదరాబాదు -> పబ్లికేషన్స్ హైదరాబాదు')
    into independent word-level entries inheriting evidence, scope, and provenance.
    """
    stmt = select(CorrectionMemory).where(CorrectionMemory.language_code == language_code)
    if book_id is not None:
        stmt = stmt.where(CorrectionMemory.book_id == book_id)
    rows = list(db.scalars(stmt.order_by(CorrectionMemory.created_at.asc(), CorrectionMemory.id.asc())).all())

    inspected = 0
    split_legacy_rows = 0
    cleaned_punct_rows = 0
    created_word_rules = 0
    merged_duplicates = 0

    for row in rows:
        inspected += 1
        inc = normalize_nfc(row.incorrect_text).strip()
        cor = normalize_nfc(row.corrected_text).strip()
        if not inc or not cor:
            continue

        inc_tokens = inc.split()
        cor_tokens = cor.split()

        # Case A: Single-token rule with shared edge punctuation (e.g. '(పగమబాగం- -> ప్రథమభాగం-').
        if len(inc_tokens) == 1 and len(cor_tokens) == 1:
            cleaned_inc, cleaned_cor = _strip_shared_edge_punct(inc, cor)
            if cleaned_inc != inc or cleaned_cor != cor or row.unit_type != classify_unit_type(cleaned_inc, cleaned_cor):
                # Check if an equivalent rule already exists to merge cleanly.
                dup_stmt = select(CorrectionMemory).where(
                    CorrectionMemory.id != row.id,
                    CorrectionMemory.language_code == row.language_code,
                    CorrectionMemory.incorrect_text == cleaned_inc,
                    CorrectionMemory.corrected_text == cleaned_cor,
                    CorrectionMemory.scope == row.scope,
                )
                if row.scope == "book_only":
                    dup_stmt = dup_stmt.where(CorrectionMemory.book_id == row.book_id)
                existing_dup = None
                for cand in db.scalars(dup_stmt).all():
                    if cand.left_context == row.left_context and cand.right_context == row.right_context:
                        existing_dup = cand
                        break
                if existing_dup is not None:
                    existing_dup.approved_count += row.approved_count
                    existing_dup.rejected_count += row.rejected_count
                    db.delete(row)
                    merged_duplicates += 1
                else:
                    row.incorrect_text = cleaned_inc
                    row.corrected_text = cleaned_cor
                    row.normalized_incorrect = normalize_lookup_form(cleaned_inc)
                    row.unit_type = classify_unit_type(cleaned_inc, cleaned_cor)
                    cleaned_punct_rows += 1
            continue

        # Case B: Multi-word rule -> try splitting into independent word-level corrections.
        extracted = extract_word_level_corrections(inc, cor)
        if not extracted:
            continue
        # Only replace the legacy phrase row if it splits into >= 2 smaller units OR shrinks to a single clean word.
        is_decomposed = len(extracted) > 1 or (
            len(extracted) == 1
            and len(extracted[0][0].split()) == 1
            and len(extracted[0][1].split()) == 1
            and (extracted[0][0] != inc or extracted[0][1] != cor)
        )
        if not is_decomposed:
            continue

        emitted_any = False
        for idx, (sub_inc, sub_cor, sub_left, sub_right) in enumerate(extracted):
            safe, _ = is_safe_auto_memory_rule(sub_inc, sub_cor)
            if not safe:
                continue
            # Combine inherited outer context with local sub-token context when helpful.
            eff_left = sub_left if sub_left else (row.left_context if idx == 0 else None)
            eff_right = sub_right if sub_right else (row.right_context if idx == len(extracted) - 1 else None)
            new_entry = create_correction_memory_entry(
                db=db,
                incorrect_text=sub_inc,
                corrected_text=sub_cor,
                left_context=eff_left,
                right_context=eff_right,
                correction_type=row.correction_type,
                scope=row.scope,
                book_id=row.book_id,
                source_ocr_block_id=row.source_ocr_block_id,
                source_page_number=row.source_page_number,
                language_code=row.language_code,
            )
            # Preserve prior evidence counts beyond the initial +1 created above.
            if row.approved_count > 1:
                new_entry.approved_count += row.approved_count - 1
            if row.rejected_count > 0:
                new_entry.rejected_count += row.rejected_count
            if row.status != "active":
                new_entry.status = row.status
            created_word_rules += 1
            emitted_any = True

        if emitted_any:
            db.delete(row)
            split_legacy_rows += 1

    db.commit()
    bump_sentence_context_epoch()
    log_event(
        LOGGER,
        logging.INFO,
        "Normalized legacy correction memory rules",
        inspected=inspected,
        split_legacy_rows=split_legacy_rows,
        cleaned_punct_rows=cleaned_punct_rows,
        created_word_rules=created_word_rules,
        merged_duplicates=merged_duplicates,
    )
    return {
        "inspected_count": inspected,
        "split_legacy_rows": split_legacy_rows,
        "cleaned_punct_rows": cleaned_punct_rows,
        "created_word_rules": created_word_rules,
        "merged_duplicates": merged_duplicates,
    }


def _compute_active_conflicts(
    db: Session,
    language_code: str = "te",
) -> dict[str, set[str]]:
    """Map normalized_incorrect -> set of distinct active corrected_text targets."""
    rows = db.execute(
        select(
            CorrectionMemory.incorrect_text,
            CorrectionMemory.normalized_incorrect,
            CorrectionMemory.corrected_text,
        ).where(
            CorrectionMemory.language_code == language_code,
            CorrectionMemory.status == "active",
        )
    ).all()
    targets_by_norm: dict[str, set[str]] = {}
    for inc, norm_inc, cor in rows:
        key = norm_inc or normalize_lookup_form(inc)
        if not key:
            continue
        targets_by_norm.setdefault(key, set()).add(normalize_nfc(cor).strip())
    return targets_by_norm


def serialize_correction_record_dict(
    row: CorrectionMemory,
    *,
    targets_by_norm: dict[str, set[str]] | None = None,
    book_titles: dict[uuid.UUID, str] | None = None,
) -> dict[str, Any]:
    """Serialize a CorrectionMemory ORM row with computed conflict, reliability, and book metadata."""
    norm_key = row.normalized_incorrect or normalize_lookup_form(row.incorrect_text)
    distinct_targets = targets_by_norm.get(norm_key, set()) if targets_by_norm else set()
    conflict_count = len(distinct_targets) if (row.status == "active" and len(distinct_targets) > 1) else 0
    has_conflict = conflict_count > 1
    return {
        "correction_id": row.id,
        "language_code": row.language_code,
        "incorrect_text": row.incorrect_text,
        "normalized_incorrect": norm_key,
        "corrected_text": row.corrected_text,
        "left_context": row.left_context,
        "right_context": row.right_context,
        "correction_type": row.correction_type,
        "unit_type": row.unit_type or classify_unit_type(row.incorrect_text, row.corrected_text),
        "scope": row.scope,
        "book_id": row.book_id,
        "source_book_title": book_titles.get(row.book_id) if (book_titles and row.book_id) else None,
        "source_ocr_block_id": row.source_ocr_block_id,
        "source_page_number": row.source_page_number,
        "status": row.status,
        "approved_count": row.approved_count,
        "rejected_count": row.rejected_count,
        "reliability_score": compute_reliability_score(
            row.approved_count, row.rejected_count, has_conflict=has_conflict
        ),
        "has_conflict": has_conflict,
        "conflict_count": conflict_count,
        "last_used_at": row.last_used_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def list_corrections(
    *,
    db: Session,
    book_id: uuid.UUID | None = None,
    status: str | None = None,
    scope: str | None = None,
    unit_type: str | None = None,
    conflict_only: bool = False,
    query: str | None = None,
    language_code: str = "te",
    limit: int = 200,
    offset: int = 0,
) -> list[CorrectionMemory]:
    """List correction memory records with SQL filtering and bounded pagination."""
    rows, _total, _meta = list_corrections_enriched(
        db=db,
        book_id=book_id,
        status=status,
        scope=scope,
        unit_type=unit_type,
        conflict_only=conflict_only,
        query=query,
        language_code=language_code,
        limit=limit,
        offset=offset,
    )
    return rows


def list_corrections_enriched(
    *,
    db: Session,
    book_id: uuid.UUID | None = None,
    status: str | None = None,
    scope: str | None = None,
    unit_type: str | None = None,
    conflict_only: bool = False,
    query: str | None = None,
    language_code: str = "te",
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[CorrectionMemory], int, dict[str, Any]]:
    """List correction memory records with total counts, conflict metadata, and book titles."""
    targets_by_norm = _compute_active_conflicts(db, language_code=language_code)
    conflicting_norms = {k for k, v in targets_by_norm.items() if len(v) > 1}

    stmt = select(CorrectionMemory).where(CorrectionMemory.language_code == language_code)
    if book_id is not None:
        stmt = stmt.where(CorrectionMemory.book_id == book_id)
    if status is not None:
        if status not in ALLOWED_STATUSES:
            raise AppError("INVALID_CORRECTION_STATUS", f"Unsupported status {status!r}.", status_code=400)
        stmt = stmt.where(CorrectionMemory.status == status)
    if scope is not None:
        if scope not in ALLOWED_SCOPES:
            raise AppError("INVALID_CORRECTION_SCOPE", f"Unsupported scope {scope!r}.", status_code=400)
        stmt = stmt.where(CorrectionMemory.scope == scope)
    if unit_type is not None:
        if unit_type not in ALLOWED_UNIT_TYPES:
            raise AppError("INVALID_UNIT_TYPE", f"Unsupported unit_type {unit_type!r}.", status_code=400)
        stmt = stmt.where(CorrectionMemory.unit_type == unit_type)
    if conflict_only:
        if not conflicting_norms:
            return [], 0, {
                "targets_by_norm": targets_by_norm,
                "book_titles": {},
                "global_count": 0,
                "book_specific_count": 0,
                "conflicts_count": 0,
            }
        stmt = stmt.where(
            CorrectionMemory.status == "active",
            CorrectionMemory.normalized_incorrect.in_(list(conflicting_norms)),
        )
    if query and query.strip():
        q_nfc = normalize_nfc(query).strip()
        pat = f"%{q_nfc}%"
        stmt = stmt.where(
            or_(
                CorrectionMemory.incorrect_text.ilike(pat),
                CorrectionMemory.normalized_incorrect.ilike(pat),
                CorrectionMemory.corrected_text.ilike(pat),
                CorrectionMemory.left_context.ilike(pat),
                CorrectionMemory.right_context.ilike(pat),
            )
        )

    total_count = int(
        db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    )

    safe_limit = max(1, min(int(limit), 500))
    safe_offset = max(0, int(offset))
    rows = list(
        db.scalars(
            stmt.order_by(CorrectionMemory.created_at.desc(), CorrectionMemory.id.desc())
            .limit(safe_limit)
            .offset(safe_offset)
        ).all()
    )

    # Fetch summary counts for header badges (within current book filter if set).
    base_scope_stmt = select(CorrectionMemory.scope, func.count(CorrectionMemory.id)).where(
        CorrectionMemory.language_code == language_code
    )
    if book_id is not None:
        base_scope_stmt = base_scope_stmt.where(CorrectionMemory.book_id == book_id)
    scope_counts = {
        str(sc): int(cnt)
        for sc, cnt in db.execute(base_scope_stmt.group_by(CorrectionMemory.scope)).all()
    }

    book_ids = list({r.book_id for r in rows if r.book_id is not None})
    book_titles: dict[uuid.UUID, str] = {}
    if book_ids:
        for bid, btitle in db.execute(select(Book.id, Book.title).where(Book.id.in_(book_ids))).all():
            book_titles[bid] = str(btitle)

    return rows, total_count, {
        "targets_by_norm": targets_by_norm,
        "book_titles": book_titles,
        "global_count": scope_counts.get("global_suggestion", 0),
        "book_specific_count": scope_counts.get("book_only", 0),
        "conflicts_count": len(conflicting_norms),
    }
