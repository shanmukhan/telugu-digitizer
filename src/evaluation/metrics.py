"""Unicode NFC, Telugu extended-grapheme-cluster, CER, WER, and exact-line metrics."""

from __future__ import annotations

import statistics
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any, Sequence

import regex
from rapidfuzz.distance import Levenshtein


def normalize_line_endings(text: str) -> str:
    """Normalize CRLF/CR to LF without altering Unicode normalization or Telugu marks."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def normalize_nfc(text: str) -> str:
    """Return a Unicode NFC-normalized copy for metric comparison."""
    return unicodedata.normalize("NFC", normalize_line_endings(text))


def normalize_whitespace(text: str) -> str:
    """Collapse arbitrary whitespace runs into single spaces."""
    return " ".join(text.split())


def grapheme_clusters(text: str) -> list[str]:
    """Segment text into Unicode extended grapheme clusters (Telugu akshara proxy)."""
    return regex.findall(r"\X", text)


@dataclass(frozen=True)
class EditStats:
    """Edit distance breakdown against a reference sequence."""

    substitutions: int
    deletions: int
    insertions: int
    edits: int
    ref_length: int

    @property
    def error_rate(self) -> float | None:
        if self.ref_length == 0:
            return 0.0 if self.edits == 0 else None
        return self.edits / self.ref_length


def sequence_edit_stats(reference: Sequence[Any], hypothesis: Sequence[Any]) -> EditStats:
    """Compute exact substitutions, deletions, insertions, and total edit distance."""
    subs = 0
    dels = 0
    ins = 0
    for tag, i1, i2, j1, j2 in Levenshtein.opcodes(reference, hypothesis):
        if tag == "replace":
            span = max(i2 - i1, j2 - j1)
            common = min(i2 - i1, j2 - j1)
            subs += common
            if (i2 - i1) > (j2 - j1):
                dels += (i2 - i1) - (j2 - j1)
            elif (j2 - j1) > (i2 - i1):
                ins += (j2 - j1) - (i2 - i1)
            _ = span
        elif tag == "delete":
            dels += i2 - i1
        elif tag == "insert":
            ins += j2 - j1
    edits = subs + dels + ins
    return EditStats(
        substitutions=subs,
        deletions=dels,
        insertions=ins,
        edits=edits,
        ref_length=len(reference),
    )


def _lcs_length(seq_a: Sequence[str], seq_b: Sequence[str]) -> int:
    """Compute length of longest common subsequence for order-preserving line matches."""
    if not seq_a or not seq_b:
        return 0
    prev = [0] * (len(seq_b) + 1)
    for item_a in seq_a:
        curr = [0] * (len(seq_b) + 1)
        for j, item_b in enumerate(seq_b, start=1):
            if item_a == item_b:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = prev[j] if prev[j] >= curr[j - 1] else curr[j - 1]
        prev = curr
    return prev[-1]


def split_scored_lines(text_nfc: str) -> list[str]:
    """Split normalized text into stripped non-empty lines per exact-line scoring policy."""
    return [line.strip() for line in text_nfc.split("\n") if line.strip()]


@dataclass(frozen=True)
class PageMetrics:
    """Complete Phase 1 recognition metrics for a single page."""

    raw_cer: float | None
    raw_edits: int
    raw_ref_chars: int
    raw_subs: int
    raw_dels: int
    raw_ins: int

    nfc_cer: float | None
    nfc_edits: int
    nfc_ref_chars: int
    nfc_subs: int
    nfc_dels: int
    nfc_ins: int

    ws_normalized_nfc_cer: float | None
    ws_nfc_edits: int
    ws_nfc_ref_chars: int

    wer: float | None
    word_edits: int
    ref_words: int
    word_subs: int
    word_dels: int
    word_ins: int

    grapheme_er: float | None
    grapheme_edits: int
    ref_graphemes: int
    grapheme_subs: int
    grapheme_dels: int
    grapheme_ins: int

    exact_line_accuracy: float | None
    exact_line_matches: int
    ref_lines: int
    hyp_lines: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_page_text(reference_raw: str, hypothesis_raw: str) -> PageMetrics:
    """Calculate all Phase 1 metrics on one reference/hypothesis pair without mutating inputs."""
    ref_raw = normalize_line_endings(reference_raw)
    hyp_raw = normalize_line_endings(hypothesis_raw)
    raw_stats = sequence_edit_stats(ref_raw, hyp_raw)

    ref_nfc = normalize_nfc(reference_raw)
    hyp_nfc = normalize_nfc(hypothesis_raw)
    nfc_stats = sequence_edit_stats(ref_nfc, hyp_nfc)

    ref_ws = normalize_whitespace(ref_nfc)
    hyp_ws = normalize_whitespace(hyp_nfc)
    ws_stats = sequence_edit_stats(ref_ws, hyp_ws)

    ref_words = ref_nfc.split()
    hyp_words = hyp_nfc.split()
    word_stats = sequence_edit_stats(ref_words, hyp_words)

    ref_graphs = grapheme_clusters(ref_nfc)
    hyp_graphs = grapheme_clusters(hyp_nfc)
    graph_stats = sequence_edit_stats(ref_graphs, hyp_graphs)

    ref_lines = split_scored_lines(ref_nfc)
    hyp_lines = split_scored_lines(hyp_nfc)
    line_matches = _lcs_length(ref_lines, hyp_lines)
    if not ref_lines:
        line_acc: float | None = 1.0 if not hyp_lines else None
    else:
        line_acc = line_matches / len(ref_lines)

    return PageMetrics(
        raw_cer=raw_stats.error_rate,
        raw_edits=raw_stats.edits,
        raw_ref_chars=raw_stats.ref_length,
        raw_subs=raw_stats.substitutions,
        raw_dels=raw_stats.deletions,
        raw_ins=raw_stats.insertions,
        nfc_cer=nfc_stats.error_rate,
        nfc_edits=nfc_stats.edits,
        nfc_ref_chars=nfc_stats.ref_length,
        nfc_subs=nfc_stats.substitutions,
        nfc_dels=nfc_stats.deletions,
        nfc_ins=nfc_stats.insertions,
        ws_normalized_nfc_cer=ws_stats.error_rate,
        ws_nfc_edits=ws_stats.edits,
        ws_nfc_ref_chars=ws_stats.ref_length,
        wer=word_stats.error_rate,
        word_edits=word_stats.edits,
        ref_words=word_stats.ref_length,
        word_subs=word_stats.substitutions,
        word_dels=word_stats.deletions,
        word_ins=word_stats.insertions,
        grapheme_er=graph_stats.error_rate,
        grapheme_edits=graph_stats.edits,
        ref_graphemes=graph_stats.ref_length,
        grapheme_subs=graph_stats.substitutions,
        grapheme_dels=graph_stats.deletions,
        grapheme_ins=graph_stats.insertions,
        exact_line_accuracy=line_acc,
        exact_line_matches=line_matches,
        ref_lines=len(ref_lines),
        hyp_lines=len(hyp_lines),
    )


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def aggregate_metrics(
    page_rows: list[dict[str, Any]],
    warm_elapsed_ms: list[float] | None = None,
) -> dict[str, Any]:
    """Compute micro-averaged corpus error rates and median/mean throughput."""
    scored = [r for r in page_rows if r.get("scored", False)]
    total_raw_edits = sum(int(r["raw_edits"]) for r in scored)
    total_raw_ref = sum(int(r["raw_ref_chars"]) for r in scored)
    total_nfc_edits = sum(int(r["nfc_edits"]) for r in scored)
    total_nfc_ref = sum(int(r["nfc_ref_chars"]) for r in scored)
    total_ws_edits = sum(int(r["ws_nfc_edits"]) for r in scored)
    total_ws_ref = sum(int(r["ws_nfc_ref_chars"]) for r in scored)
    total_word_edits = sum(int(r["word_edits"]) for r in scored)
    total_ref_words = sum(int(r["ref_words"]) for r in scored)
    total_graph_edits = sum(int(r["grapheme_edits"]) for r in scored)
    total_ref_graphs = sum(int(r["ref_graphemes"]) for r in scored)
    total_line_matches = sum(int(r["exact_line_matches"]) for r in scored)
    total_ref_lines = sum(int(r["ref_lines"]) for r in scored)

    if warm_elapsed_ms is None:
        sec_values = [
            float(r["elapsed_ms"]) / 1000.0
            for r in page_rows
            if r.get("status") == "completed" and r.get("elapsed_ms") is not None
        ]
    else:
        sec_values = [ms / 1000.0 for ms in warm_elapsed_ms]

    median_sec = statistics.median(sec_values) if sec_values else None
    mean_sec = statistics.mean(sec_values) if sec_values else None
    pages_per_min = (60.0 / median_sec) if (median_sec is not None and median_sec > 0) else None

    return {
        "pages_total": len(page_rows),
        "pages_scored": len(scored),
        "pages_completed": sum(1 for r in page_rows if r.get("status") == "completed"),
        "pages_failed": sum(1 for r in page_rows if r.get("status") == "failed"),
        "cer": _safe_ratio(total_raw_edits, total_raw_ref),
        "nfc_cer": _safe_ratio(total_nfc_edits, total_nfc_ref),
        "ws_normalized_nfc_cer": _safe_ratio(total_ws_edits, total_ws_ref),
        "wer": _safe_ratio(total_word_edits, total_ref_words),
        "grapheme_er": _safe_ratio(total_graph_edits, total_ref_graphs),
        "exact_line_accuracy": _safe_ratio(total_line_matches, total_ref_lines),
        "median_sec_per_page": round(median_sec, 4) if median_sec is not None else None,
        "mean_sec_per_page": round(mean_sec, 4) if mean_sec is not None else None,
        "pages_per_minute": round(pages_per_min, 2) if pages_per_min is not None else None,
        "totals": {
            "raw_edits": total_raw_edits,
            "raw_ref_chars": total_raw_ref,
            "nfc_edits": total_nfc_edits,
            "nfc_ref_chars": total_nfc_ref,
            "word_edits": total_word_edits,
            "ref_words": total_ref_words,
            "grapheme_edits": total_graph_edits,
            "ref_graphemes": total_ref_graphs,
            "exact_line_matches": total_line_matches,
            "ref_lines": total_ref_lines,
        },
    }
