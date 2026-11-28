"""Telugu lexicon, visual OCR confusion scorer, and sentence/bigram context auto-corrector.

This module implements strictly opt-in, non-destructive OCR auto-correction proposals:
  1. Active database correction_memory rules (contextual, highest priority).
  2. Local NFC-normalized Telugu dictionary (LibreOffice + C.P. Brown + Janapada + frequency lists)
     with Telugu morphological suffix & compound awareness and visual OCR confusion weighting.
  3. Sentence/bigram context disambiguation harvested from verified database blocks & corrections.

Raw OCR text is never overwritten; all proposals are returned for human review.
"""

from __future__ import annotations

import gzip
import logging
import math
import re
import threading
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.cache_state import current_sentence_context_epoch
from src.db.models import (
    Book,
    BookPage,
    CorrectionMemory,
    CustomDictionaryWord,
    DocumentTextBlock,
    DocumentTextVersion,
    OCRBlock,
)
from src.evaluation.metrics import normalize_nfc
from src.services.correction_service import build_suggestion_index, find_block_suggestions_from_index
from src.services.review_service import get_page_review_payload

LOGGER = logging.getLogger("telugu_digitizer.services.lexicon")

_DEFAULT_LEXICON_PATH = Path(__file__).resolve().parents[2] / "models" / "lexicon" / "telugu_lexicon.tsv.gz"

_EDGE_PUNCT = ".,!?;:\"'()[]{}—–-।॥“”‘’/\\|•*"
_TELUGU_WORD_RE = re.compile(r"^[\u0C00-\u0C63\u0C78-\u0C7F\u200C\u200D]+$")
_TELUGU_LETTER_RE = re.compile(r"[\u0C05-\u0C39\u0C58-\u0C61]")
_TELUGU_CONSONANT_RE = re.compile(r"[\u0C15-\u0C39]")
_TELUGU_VATTU_RE = re.compile(r"\u0C4D[\u0C15-\u0C39]")
_SPLIT_KEEP_WS_RE = re.compile(r"(\s+)")
_COMMON_VATTU_CONSONANTS = frozenset(("ర", "య", "వ", "త", "న", "మ", "ల", "క", "ప", "ట", "ద", "స"))


def strip_telugu_joiners(token: str) -> str:
    """Remove ZWNJ/ZWJ joiners cleanly for base lexicon matching."""
    return token.replace("\u200c", "").replace("\u200d", "")


def _is_valid_word_final_pollu(token: str) -> bool:
    """Return True when joiners appear strictly as classical word-final nakara-pollu (న్‍ / న్‌)."""
    return (
        len(token) >= 3
        and token.endswith(("న్\u200d", "న్\u200c"))
        and "\u200c" not in token[:-1]
        and "\u200d" not in token[:-1]
    )
_TELUGU_MATRAS = ("ా", "ి", "ీ", "ు", "ూ", "ృ", "ె", "ే", "ై", "ొ", "ో", "ౌ", "ం", "్", "ః")

# Common Telugu case markers, plural suffixes, and postpositions so valid inflections are not mis-flagged.
_TELUGU_SUFFIXES = (
    "యొక్క",
    "గురించి",
    "గూర్చి",
    "కొరకు",
    "నుండి",
    "నుంచి",
    "లోపల",
    "లోనిది",
    "లాంటి",
    "వరకు",
    "కోసం",
    "క్రింద",
    "మీద",
    "పైన",
    "తోటి",
    "వల్ల",
    "కూడా",
    "లోని",
    "లతో",
    "లలో",
    "లను",
    "లకు",
    "లచే",
    "చేత",
    "ైన",
    "లు",
    "ను",
    "ని",
    "కి",
    "కు",
    "లో",
    "తో",
    "చే",
    "పై",
    "గా",
    "అని",
)

# Visually confusable Telugu OCR character groups.
_CONFUSION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("ధ", "ణ", "భ", "ద", "బ"),
    ("స", "న", "త", "థ", "ష", "శ"),
    ("ప", "వ", "ఫ"),
    ("ట", "ఠ", "ల", "ళ"),
    ("క", "ర", "గ", "ఘ", "ఖ", "థ", "ఱ"),
    ("మ", "య"),
    ("చ", "ఛ", "ద", "డ", "ఢ", "జ"),
    ("బ", "భ", "ఓ", "ఒ"),
    ("ె", "ే", "ై"),
    ("ొ", "ో", "ా", "ౌ"),
    ("ి", "ీ"),
    ("ు", "ూ", "ృ"),
)

# Tight high-frequency OCR substitution pairs (cost 0.30).
_TIGHT_CONFUSION_PAIRS: set[tuple[str, str]] = set()
for _a, _b in (
    ("ధ", "ణ"),
    ("ధ", "భ"),
    ("ధ", "ద"),
    ("బ", "భ"),
    ("థ", "గ"),
    ("థ", "ధ"),
    ("థ", "ఠ"),
    ("త", "థ"),
    ("క", "ఖ"),
    ("గ", "ఘ"),
    ("ప", "ఫ"),
    ("ట", "ఠ"),
    ("డ", "ఢ"),
    ("చ", "ఛ"),
    ("స", "న"),
    ("త", "న"),
    ("స", "ష"),
    ("స", "శ"),
    ("ష", "శ"),
    ("ప", "వ"),
    ("ట", "ల"),
    ("ల", "ళ"),
    ("క", "ర"),
    ("గ", "ర"),
    ("ఖ", "ర"),
    ("ఱ", "ర"),
    ("మ", "య"),
    ("చ", "ద"),
    ("ద", "డ"),
    ("ె", "ే"),
    ("ె", "ై"),
    ("ొ", "ో"),
    ("ా", "ో"),
    ("ి", "ీ"),
    ("ు", "ూ"),
    ("ు", "ృ"),
    ("ో", "ౌ"),
):
    _TIGHT_CONFUSION_PAIRS.add((_a, _b))
    _TIGHT_CONFUSION_PAIRS.add((_b, _a))

_CONFUSION_NEIGHBORS: dict[str, tuple[str, ...]] = {}
for _grp in _CONFUSION_GROUPS:
    for _ch in _grp:
        existing = set(_CONFUSION_NEIGHBORS.get(_ch, ()))
        existing.update(c for c in _grp if c != _ch)
        _CONFUSION_NEIGHBORS[_ch] = tuple(sorted(existing))

# Canonical visual skeleton map (O(1) multi-confusion candidate lookup).
_SKELETON_MAP: dict[str, str] = {
    "ధ": "ణ",
    "భ": "ణ",
    "బ": "ణ",
    "స": "న",
    "త": "న",
    "ష": "న",
    "శ": "న",
    "ప": "వ",
    "ఫ": "వ",
    "ట": "ల",
    "ఠ": "ల",
    "ళ": "ల",
    "క": "ర",
    "గ": "ర",
    "ఘ": "ర",
    "ఖ": "ర",
    "థ": "ర",
    "ఱ": "ర",
    "మ": "య",
    "చ": "ద",
    "ఛ": "ద",
    "డ": "ద",
    "ఢ": "ద",
    "ే": "ె",
    "ై": "ె",
    "ో": "ొ",
    "ా": "ొ",
    "ౌ": "ొ",
    "ీ": "ి",
    "ూ": "ు",
    "ృ": "ు",
}
_SKELETON_TABLE = str.maketrans(_SKELETON_MAP)


def visual_skeleton(word: str) -> str:
    """Collapse common Telugu OCR visual confusions into a canonical lookup key."""
    return word.translate(_SKELETON_TABLE)


def vattu_stripped_skeleton(word: str) -> str:
    """Strip subjoined Telugu conjuncts (్ + consonant) before computing visual skeleton."""
    return _TELUGU_VATTU_RE.sub("", word).translate(_SKELETON_TABLE)


def _strip_edge_punct(token: str) -> tuple[str, str, str]:
    if not token:
        return "", "", ""
    start = 0
    end = len(token)
    while start < end and token[start] in _EDGE_PUNCT:
        start += 1
    while end > start and token[end - 1] in _EDGE_PUNCT:
        end -= 1
    return token[:start], token[start:end], token[end:]


def is_telugu_word(token: str) -> bool:
    return bool(token and _TELUGU_WORD_RE.fullmatch(token) and _TELUGU_LETTER_RE.search(token))


def telugu_ocr_edit_distance(src: str, dst: str) -> float:
    """Weighted Damerau-Levenshtein distance tuned for Telugu OCR visual confusions."""
    if src == dst:
        return 0.0
    m, n = len(src), len(dst)
    if abs(m - n) > 4:
        return float(abs(m - n))

    dp = [[0.0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        ch = src[i - 1]
        dp[i][0] = dp[i - 1][0] + (0.55 if ch in _TELUGU_MATRAS else 1.0)
    for j in range(1, n + 1):
        ch = dst[j - 1]
        dp[0][j] = dp[0][j - 1] + (0.55 if ch in _TELUGU_MATRAS else 1.0)

    for i in range(1, m + 1):
        ca = src[i - 1]
        del_cost = 0.55 if ca in _TELUGU_MATRAS else 1.0
        for j in range(1, n + 1):
            cb = dst[j - 1]
            if ca == cb:
                sub_cost = 0.0
            elif (ca, cb) in _TIGHT_CONFUSION_PAIRS:
                sub_cost = 0.30
            elif cb in _CONFUSION_NEIGHBORS.get(ca, ()):
                sub_cost = 0.45
            else:
                sub_cost = 1.0

            ins_cost = 0.55 if cb in _TELUGU_MATRAS else 1.0
            best = min(
                dp[i - 1][j] + del_cost,
                dp[i][j - 1] + ins_cost,
                dp[i - 1][j - 1] + sub_cost,
            )
            if i > 1 and j > 1 and ca == dst[j - 2] and src[i - 2] == cb:
                best = min(best, dp[i - 2][j - 2] + 0.55)
            # Treat a missing/spurious 2-codepoint Telugu vattu (్ + consonant) as a single visual OCR miss.
            if j > 1 and dst[j - 2] == "\u0c4d" and "\u0c15" <= cb <= "\u0c39":
                vattu_cost = 0.40 if cb in _COMMON_VATTU_CONSONANTS else 0.60
                best = min(best, dp[i][j - 2] + vattu_cost)
            if i > 1 and src[i - 2] == "\u0c4d" and "\u0c15" <= ca <= "\u0c39":
                vattu_cost = 0.40 if ca in _COMMON_VATTU_CONSONANTS else 0.60
                best = min(best, dp[i - 2][j] + vattu_cost)
            dp[i][j] = best
    return dp[m][n]


def _describe_ocr_change(original: str, replacement: str) -> str:
    """Produce a concise human-readable reason for a proposed Telugu replacement."""
    if len(original) == len(replacement):
        diffs = [(a, b) for a, b in zip(original, replacement) if a != b]
        if 1 <= len(diffs) <= 2:
            pairs = ", ".join(f"{a}→{b}" for a, b in diffs)
            return f"Telugu OCR confusion ({pairs})"
    return "Telugu dictionary + OCR similarity match"


@dataclass
class SentenceContextModel:
    """In-memory word & bigram frequency model harvested from PostgreSQL verified text."""

    book_words: Counter[str] = field(default_factory=Counter)
    global_words: Counter[str] = field(default_factory=Counter)
    left_bigrams: Counter[tuple[str, str]] = field(default_factory=Counter)
    right_bigrams: Counter[tuple[str, str]] = field(default_factory=Counter)
    extra_skeleton_index: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    def add_sentence(self, text: str, *, same_book: bool, weight: int = 1) -> None:
        raw_tokens = normalize_nfc(text).split()
        cleaned: list[str] = []
        for raw in raw_tokens:
            _, core, _ = _strip_edge_punct(raw)
            if is_telugu_word(core):
                cleaned.append(core)
        for idx, tok in enumerate(cleaned):
            if same_book:
                self.book_words[tok] += weight
            self.global_words[tok] += weight
            self.extra_skeleton_index[visual_skeleton(tok)].add(tok)
            if idx > 0:
                self.left_bigrams[(cleaned[idx - 1], tok)] += weight
            if idx + 1 < len(cleaned):
                self.right_bigrams[(tok, cleaned[idx + 1])] += weight

    def add_correction_context(
        self,
        corrected_text: str,
        left_context: str | None,
        right_context: str | None,
        *,
        same_book: bool,
        weight: int = 2,
    ) -> None:
        cor_tokens = [_strip_edge_punct(t)[1] for t in normalize_nfc(corrected_text).split()]
        cor_tokens = [t for t in cor_tokens if is_telugu_word(t)]
        if not cor_tokens:
            return
        for tok in cor_tokens:
            if same_book:
                self.book_words[tok] += weight
            self.global_words[tok] += weight
            self.extra_skeleton_index[visual_skeleton(tok)].add(tok)
        if left_context:
            l_toks = [_strip_edge_punct(t)[1] for t in normalize_nfc(left_context).split()]
            l_toks = [t for t in l_toks if is_telugu_word(t)]
            if l_toks:
                self.left_bigrams[(l_toks[-1], cor_tokens[0])] += weight
        if right_context:
            r_toks = [_strip_edge_punct(t)[1] for t in normalize_nfc(right_context).split()]
            r_toks = [t for t in r_toks if is_telugu_word(t)]
            if r_toks:
                self.right_bigrams[(cor_tokens[-1], r_toks[0])] += weight


class TeluguLexicon:
    """Memory-efficient local Telugu dictionary with visual-skeleton & 1-delete indexing."""

    def __init__(self, entries: list[tuple[str, int, str]] | None = None) -> None:
        self.words: dict[str, int] = {}
        self.curated: set[str] = set()
        self.skeleton_index: dict[str, list[str]] = defaultdict(list)
        self.vattu_skeleton_index: dict[str, list[str]] = defaultdict(list)
        self.delete1_index: dict[str, list[str]] = defaultdict(list)
        if entries:
            self._populate(entries)

    def _populate(self, entries: list[tuple[str, int, str]]) -> None:
        # Entries are expected sorted descending by weight.
        for idx, (word, weight, flags) in enumerate(entries):
            w = normalize_nfc(word).strip()
            if not w:
                continue
            self.words[w] = weight
            if any(ch in flags for ch in ("L", "B", "J", "W")):
                self.curated.add(w)

            skel = visual_skeleton(w)
            bucket = self.skeleton_index[skel]
            cap = 48 if w in self.curated else 32
            if len(bucket) < cap:
                bucket.append(w)

            # Secondary vattu-stripped skeleton index catches dropped conjuncts (e.g., ప్ర -> ప in ప్రథమభాగం).
            if "\u0c4d" in w and len(w) >= 5:
                vskel = vattu_stripped_skeleton(w)
                if vskel != skel and len(vskel) >= 3:
                    vbucket = self.vattu_skeleton_index[vskel]
                    if len(vbucket) < 24:
                        vbucket.append(w)

            # Index 1-char deletes for top 100k words (low RAM, catches missing/extra chars in literary Telugu).
            if idx < 100_000 and 4 <= len(w) <= 22:
                for pos in range(len(w)):
                    dkey = w[:pos] + w[pos + 1 :]
                    dbucket = self.delete1_index[dkey]
                    if len(dbucket) < 8:
                        dbucket.append(w)

    @classmethod
    def from_file(cls, path: Path) -> "TeluguLexicon":
        if not path.is_file():
            LOGGER.warning("Telugu lexicon file not found at %s; dictionary auto-correction disabled.", path)
            return cls([])
        entries: list[tuple[str, int, str]] = []
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if not parts or not parts[0]:
                    continue
                word = parts[0]
                weight = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
                flags = parts[2] if len(parts) > 2 else "L"
                entries.append((word, weight, flags))
        LOGGER.info("Loaded Telugu lexicon (%d words) from %s", len(entries), path)
        return cls(entries)

    def has_exact(self, word: str, context: SentenceContextModel | None = None) -> bool:
        if word in self.words:
            return True
        if context is not None and (word in context.book_words or context.global_words.get(word, 0) >= 2):
            return True
        return False

    def is_known_word(self, word: str, context: SentenceContextModel | None = None) -> bool:
        """Check exact lexicon, verified DB vocab, inflected suffix forms, and simple 2-part compounds."""
        if _is_valid_word_final_pollu(word):
            word = strip_telugu_joiners(word)
        if self.has_exact(word, context):
            return True
        # Check common Telugu suffixes.
        for suf in _TELUGU_SUFFIXES:
            if len(word) > len(suf) + 2 and word.endswith(suf):
                stem = word[: -len(suf)]
                if self.has_exact(stem, context):
                    return True
                # Handle sandhi/stem vowel elision (e.g., పుస్తకము -> పుస్తకం + లో)
                if stem.endswith("ం") and self.has_exact(stem[:-1] + "ము", context):
                    return True
                for v in ("ు", "ా", "ి", "ె"):
                    if self.has_exact(stem + v, context):
                        return True
        # Check clean 2-part Telugu compound (e.g., అష్టాదశ + వర్ణనలు).
        if len(word) >= 7:
            for split_at in range(3, len(word) - 2):
                left = word[:split_at]
                right = word[split_at:]
                if self.has_exact(left, context) and self._is_known_or_suffixed(right, context):
                    return True
        return False

    def _is_known_or_suffixed(self, word: str, context: SentenceContextModel | None = None) -> bool:
        if self.has_exact(word, context):
            return True
        for suf in _TELUGU_SUFFIXES:
            if len(word) > len(suf) + 2 and word.endswith(suf):
                stem = word[: -len(suf)]
                if self.has_exact(stem, context):
                    return True
        return False

    def _raw_candidates_for_unit(
        self,
        unit: str,
        context: SentenceContextModel | None = None,
    ) -> set[str]:
        """Generate candidate real Telugu words close to a single word unit."""
        cands: set[str] = set()
        skel = visual_skeleton(unit)
        for cand in self.skeleton_index.get(skel, ()):
            if abs(len(cand) - len(unit)) <= 2:
                cands.add(cand)
        if len(unit) >= 4:
            vskel = vattu_stripped_skeleton(unit)
            for cand in self.vattu_skeleton_index.get(vskel, ()):
                if abs(len(cand) - len(unit)) <= 4:
                    cands.add(cand)
        if context is not None:
            for cand in context.extra_skeleton_index.get(skel, ()):
                if abs(len(cand) - len(unit)) <= 2:
                    cands.add(cand)

        # 1-char visual confusion substitutions.
        for i, ch in enumerate(unit):
            neighbors = _CONFUSION_NEIGHBORS.get(ch)
            if not neighbors:
                continue
            prefix = unit[:i]
            suffix = unit[i + 1 :]
            for nb in neighbors:
                probe = prefix + nb + suffix
                if self.has_exact(probe, context):
                    cands.add(probe)

        # 1-char matra/diacritic insertions (e.g., పస్తకం -> పుస్తకం).
        if 3 <= len(unit) <= 24:
            for i in range(1, len(unit) + 1):
                prefix = unit[:i]
                suffix = unit[i:]
                for matra in _TELUGU_MATRAS:
                    probe = prefix + matra + suffix
                    if self.has_exact(probe, context):
                        cands.add(probe)

        # 1-char deletions & delete1_index lookups (catches extra/dropped/substituted chars).
        if 4 <= len(unit) <= 24:
            for cand in self.delete1_index.get(unit, ()):
                cands.add(cand)
            for i in range(len(unit)):
                deleted = unit[:i] + unit[i + 1 :]
                if self.has_exact(deleted, context):
                    cands.add(deleted)
                for cand in self.delete1_index.get(deleted, ()):
                    cands.add(cand)

        # Adjacent transpositions.
        for i in range(len(unit) - 1):
            if unit[i] != unit[i + 1]:
                swapped = unit[:i] + unit[i + 1] + unit[i] + unit[i + 2 :]
                if self.has_exact(swapped, context):
                    cands.add(swapped)

        cands.discard(unit)
        return cands

    def suggest_word(
        self,
        token: str,
        *,
        prev_word: str | None = None,
        next_word: str | None = None,
        context: SentenceContextModel | None = None,
        use_sentence_context: bool = True,
        min_confidence: float = 0.78,
    ) -> dict[str, Any] | None:
        """Return the highest-confidence Telugu dictionary/context correction for one unknown token."""
        if not self.words and (context is None or not context.global_words):
            return None
        if len(token) < 3 or not is_telugu_word(token):
            return None
        if self.is_known_word(token, context):
            return None

        # Spurious mid-word ZWNJ/ZWJ (common Tesseract conjunct artifact): strip joiners first.
        has_joiner = "\u200c" in token or "\u200d" in token
        work_token = strip_telugu_joiners(token) if has_joiner else token
        if has_joiner and work_token != token and self.is_known_word(work_token, context):
            return {
                "original": token,
                "replacement": work_token,
                "source": "dictionary",
                "confidence": 0.94,
                "reason": "Removed spurious ZWNJ/ZWJ joiner inside Telugu conjunct",
            }
        if len(work_token) < 3:
            return None

        candidates: dict[str, str] = {}  # candidate_word -> kind
        for c in self._raw_candidates_for_unit(work_token, context):
            candidates[c] = "direct"

        # Suffix-preserved stem correction (e.g., వర్ధనలు -> వర్ణన + లు).
        for suf in _TELUGU_SUFFIXES:
            if len(work_token) > len(suf) + 3 and work_token.endswith(suf):
                stem = work_token[: -len(suf)]
                for stem_cand in self._raw_candidates_for_unit(stem, context):
                    full_cand = stem_cand + suf
                    if full_cand != work_token and full_cand not in candidates:
                        candidates[full_cand] = "suffix"

        # Compound-preserved correction (e.g., అష్టాదశ + వర్ధనలు -> అష్టాదశవర్ణనలు).
        if not candidates and len(work_token) >= 8:
            for split_at in range(3, len(work_token) - 3):
                left = work_token[:split_at]
                right = work_token[split_at:]
                if self.has_exact(left, context) and not self._is_known_or_suffixed(right, context):
                    right_cands = self._raw_candidates_for_unit(right, context)
                    for suf in _TELUGU_SUFFIXES:
                        if len(right) > len(suf) + 2 and right.endswith(suf):
                            r_stem = right[: -len(suf)]
                            for sc in self._raw_candidates_for_unit(r_stem, context):
                                right_cands.add(sc + suf)
                    for rc in right_cands:
                        full_cand = left + rc
                        if full_cand != work_token:
                            candidates[full_cand] = "compound"
                elif self._is_known_or_suffixed(right, context) and not self.has_exact(left, context):
                    for lc in self._raw_candidates_for_unit(left, context):
                        full_cand = lc + right
                        if full_cand != work_token:
                            candidates[full_cand] = "compound"

        if not candidates:
            return None

        max_dist = 1.15 if len(work_token) <= 6 else 1.45
        scored: list[tuple[float, float, str, str, bool]] = []
        for cand, kind in candidates.items():
            dist = telugu_ocr_edit_distance(work_token, cand)
            if dist <= 0.0 or dist > max_dist:
                continue

            # Base similarity from OCR distance.
            denom = max(2.2, len(work_token) * (0.48 if len(work_token) >= 7 else 0.42))
            base_conf = max(0.0, 1.0 - (dist / denom))

            # Lexicon prior.
            freq = self.words.get(cand, 0)
            if freq == 0 and kind == "suffix":
                # Estimate from stem weight.
                for suf in _TELUGU_SUFFIXES:
                    if cand.endswith(suf) and cand[: -len(suf)] in self.words:
                        freq = self.words[cand[: -len(suf)]]
                        break
            if freq == 0 and kind == "compound":
                freq = 80
            freq_bonus = min(0.14, math.log10(freq + 1) * 0.032)
            curated_bonus = 0.03 if (cand in self.curated or kind in ("suffix", "compound")) else 0.0

            # Book / DB sentence context bonus ("possible best sentences").
            book_bonus = 0.0
            bigram_bonus = 0.0
            used_context = False
            if use_sentence_context and context is not None:
                if cand in context.book_words:
                    book_bonus = min(0.12, 0.06 + math.log10(context.book_words[cand] + 1) * 0.05)
                    used_context = True
                elif cand in context.global_words:
                    book_bonus = 0.04
                left_hits = context.left_bigrams.get((prev_word, cand), 0) if prev_word else 0
                right_hits = context.right_bigrams.get((cand, next_word), 0) if next_word else 0
                if left_hits > 0 and right_hits > 0:
                    bigram_bonus = 0.22
                    used_context = True
                elif left_hits > 0 or right_hits > 0:
                    bigram_bonus = 0.14
                    used_context = True

            # Penalize pure non-confusion 1.0-cost edits slightly unless supported by strong prior/context.
            score = base_conf + freq_bonus + curated_bonus + book_bonus + bigram_bonus
            conf = min(0.96, round(score, 3))
            scored.append((score, conf, cand, kind, used_context))

        if not scored:
            return None

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_conf, best_cand, best_kind, used_context = scored[0]
        if best_conf < min_confidence:
            return None

        # Ambiguity guard: skip if runner-up is nearly tied with best candidate.
        if len(scored) >= 2:
            second_score = scored[1][0]
            if best_score - second_score < 0.035:
                return None

        source = "sentence_context" if used_context else "dictionary"
        reason = _describe_ocr_change(work_token, best_cand)
        if has_joiner:
            reason += " + cleaned ZWNJ/ZWJ"
        if best_kind == "compound":
            reason += " (compound)"
        if used_context:
            reason += " + sentence/book context"
        return {
            "original": token,
            "replacement": best_cand,
            "source": source,
            "confidence": best_conf,
            "reason": reason,
        }


_LEXICON_LOCK = threading.Lock()
_LEXICON_CACHE: dict[Path, TeluguLexicon] = {}


def get_telugu_lexicon(lexicon_path: Path | None = None) -> TeluguLexicon:
    """Lazily load and cache the local Telugu lexicon in memory."""
    target = (lexicon_path or _DEFAULT_LEXICON_PATH).resolve()
    cached = _LEXICON_CACHE.get(target)
    if cached is not None:
        return cached
    with _LEXICON_LOCK:
        cached = _LEXICON_CACHE.get(target)
        if cached is not None:
            return cached
        lexicon = TeluguLexicon.from_file(target)
        _LEXICON_CACHE[target] = lexicon
        return lexicon


_CONTEXT_LOCK = threading.Lock()
_CONTEXT_CACHE: dict[tuple[str, str], tuple[tuple[Any, ...], SentenceContextModel]] = {}
_MAX_CACHED_BOOK_CONTEXTS = 16


def _sentence_context_signature(
    *,
    db: Session,
    book_id: uuid.UUID,
    language_code: str,
) -> tuple[Any, ...]:
    """Compute a fast sub-millisecond freshness signature for cached bigram context models."""
    block_cnt = db.scalar(
        select(func.count(DocumentTextBlock.id))
        .join(DocumentTextVersion, DocumentTextBlock.version_id == DocumentTextVersion.id)
        .join(Book, DocumentTextVersion.book_id == Book.id)
        .where(Book.language_code == language_code, DocumentTextBlock.block_role != "ignore")
    )
    corr_cnt, corr_sum = db.execute(
        select(
            func.count(CorrectionMemory.id),
            func.coalesce(func.sum(CorrectionMemory.approved_count), 0),
        ).where(
            CorrectionMemory.language_code == language_code,
            CorrectionMemory.status == "active",
            or_(CorrectionMemory.scope == "global_suggestion", CorrectionMemory.book_id == book_id),
        )
    ).one()
    cw_cnt, cw_max_ts = db.execute(
        select(
            func.count(CustomDictionaryWord.id),
            func.max(CustomDictionaryWord.updated_at),
        ).where(CustomDictionaryWord.language_code == language_code)
    ).one()
    return (
        current_sentence_context_epoch(),
        int(block_cnt or 0),
        int(corr_cnt or 0),
        int(corr_sum or 0),
        int(cw_cnt or 0),
        cw_max_ts.isoformat() if cw_max_ts is not None else "",
    )


def build_sentence_context_model(
    *,
    db: Session,
    book_id: uuid.UUID,
    language_code: str = "te",
    max_global_blocks: int = 15_000,
    use_cache: bool = True,
) -> SentenceContextModel:
    """Build or return a cached in-memory Telugu vocabulary & bigram model from PostgreSQL."""
    bind = db.get_bind()
    bind_key = str(getattr(bind, "url", "")) if bind is not None else ""
    cache_key = (f"{bind_key}:{language_code}:{max_global_blocks}", str(book_id))
    signature = _sentence_context_signature(db=db, book_id=book_id, language_code=language_code)

    if use_cache:
        with _CONTEXT_LOCK:
            cached = _CONTEXT_CACHE.get(cache_key)
            if cached is not None and cached[0] == signature:
                return cached[1]

    model = SentenceContextModel()

    # Harvest human-verified DocumentTextBlocks across books (weighting current book higher).
    rows = db.execute(
        select(DocumentTextBlock.final_text, DocumentTextVersion.book_id)
        .join(DocumentTextVersion, DocumentTextBlock.version_id == DocumentTextVersion.id)
        .join(Book, DocumentTextVersion.book_id == Book.id)
        .where(
            Book.language_code == language_code,
            DocumentTextBlock.block_role != "ignore",
        )
        .order_by(DocumentTextBlock.created_at.desc())
        .limit(max_global_blocks)
    ).all()
    for final_text, row_book_id in rows:
        if not final_text:
            continue
        same_book = row_book_id == book_id
        model.add_sentence(final_text, same_book=same_book, weight=3 if same_book else 1)

    # Also harvest verified spans & contexts from active correction_memory relevant to this book.
    corr_rows = db.scalars(
        select(CorrectionMemory).where(
            CorrectionMemory.language_code == language_code,
            CorrectionMemory.status == "active",
            or_(
                CorrectionMemory.scope == "global_suggestion",
                CorrectionMemory.book_id == book_id,
            ),
            CorrectionMemory.approved_count > CorrectionMemory.rejected_count,
        )
    ).all()
    for corr in corr_rows:
        same_book = corr.book_id == book_id
        model.add_correction_context(
            corr.corrected_text,
            corr.left_context,
            corr.right_context,
            same_book=same_book,
            weight=max(2, corr.approved_count),
        )

    # Also include user-added custom Telugu dictionary words so Auto-Correct respects them immediately.
    custom_words = db.scalars(
        select(CustomDictionaryWord.word).where(CustomDictionaryWord.language_code == language_code)
    ).all()
    for cw in custom_words:
        if cw:
            model.add_sentence(cw, same_book=True, weight=5)

    if use_cache:
        with _CONTEXT_LOCK:
            if len(_CONTEXT_CACHE) >= _MAX_CACHED_BOOK_CONTEXTS and cache_key not in _CONTEXT_CACHE:
                oldest_key = next(iter(_CONTEXT_CACHE))
                _CONTEXT_CACHE.pop(oldest_key, None)
            _CONTEXT_CACHE[cache_key] = (signature, model)

    return model


def _autocorrect_single_block(
    *,
    block_text: str,
    book_id: uuid.UUID,
    by_incorrect: dict[str, list[CorrectionMemory]],
    books_by_pair: dict[tuple[str, str], set[uuid.UUID]],
    lexicon: TeluguLexicon,
    context_model: SentenceContextModel | None,
    use_correction_memory: bool,
    use_dictionary: bool,
    use_sentence_context: bool,
    min_confidence: float,
) -> tuple[str, list[dict[str, Any]]]:
    """Compute non-destructive auto-correction proposal for one block."""
    working_text = normalize_nfc(block_text)
    changes: list[dict[str, Any]] = []

    # Layer 1: Apply unambiguous active correction_memory rules first.
    if use_correction_memory and by_incorrect:
        applied_ids: set[uuid.UUID] = set()
        for _ in range(5):  # Guard against loops; at most 5 memory rule passes per block
            suggestions = find_block_suggestions_from_index(
                by_incorrect=by_incorrect,
                books_by_pair=books_by_pair,
                block_text=working_text,
                book_id=book_id,
            )
            chosen = None
            for sug in suggestions:
                if sug["correction_id"] in applied_ids:
                    continue
                if sug["has_conflict"]:
                    continue
                if sug["approved_count"] <= sug["rejected_count"]:
                    continue
                if sug["context_match"] not in ("strong", "medium"):
                    continue
                if not sug.get("proposed_block_text") or sug["proposed_block_text"] == working_text:
                    continue
                chosen = sug
                break
            if chosen is None:
                break
            applied_ids.add(chosen["correction_id"])
            working_text = chosen["proposed_block_text"]
            conf = 0.98 if chosen["context_match"] == "strong" else 0.93
            changes.append(
                {
                    "original": chosen["incorrect_text"],
                    "replacement": chosen["corrected_text"],
                    "source": "correction_memory",
                    "confidence": conf,
                    "reason": f"Correction memory ({chosen['scope']}, {chosen['context_match']} context)",
                }
            )

    # Layer 2 & 3: Telugu dictionary + OCR visual confusion + sentence/bigram context.
    if use_dictionary:
        parts = _SPLIT_KEEP_WS_RE.split(working_text)
        word_slots = [pos for pos, seg in enumerate(parts) if seg and not seg.isspace()]
        if word_slots:
            cores = [_strip_edge_punct(parts[pos])[1] for pos in word_slots]
            for word_idx, part_pos in enumerate(word_slots):
                raw_tok = parts[part_pos]
                lead, core, trail = _strip_edge_punct(raw_tok)
                if not core or not is_telugu_word(core):
                    continue
                prev_core = (
                    strip_telugu_joiners(cores[word_idx - 1])
                    if word_idx > 0 and is_telugu_word(cores[word_idx - 1])
                    else None
                )
                next_core = (
                    strip_telugu_joiners(cores[word_idx + 1])
                    if word_idx + 1 < len(cores) and is_telugu_word(cores[word_idx + 1])
                    else None
                )
                proposal = lexicon.suggest_word(
                    core,
                    prev_word=prev_core,
                    next_word=next_core,
                    context=context_model,
                    use_sentence_context=use_sentence_context,
                    min_confidence=min_confidence,
                )
                # Recover broken leading rakara-vattu misread as unmatched '(' (e.g., '(పగమబాగం-' -> 'ప్రథమభాగం-', '(శీ' -> 'శ్రీ').
                consumed_leading_paren = False
                if (
                    lead.endswith("(")
                    and ")" not in trail
                    and ")" not in working_text
                    and len(core) >= 2
                    and _TELUGU_CONSONANT_RE.fullmatch(core[0])
                    and not core[1:].startswith("\u0c4dర")
                    and not lexicon.is_known_word(core, context_model)
                ):
                    rakara_probe = f"{core[0]}\u0c4dర{core[1:]}"
                    if lexicon.is_known_word(rakara_probe, context_model):
                        rakara_prop: dict[str, Any] | None = {
                            "original": f"({core}",
                            "replacement": rakara_probe,
                            "source": "dictionary",
                            "confidence": 0.96,
                            "reason": "Recovered broken leading rakāra vattu ('(' → ్ర)",
                        }
                    else:
                        rakara_prop = lexicon.suggest_word(
                            rakara_probe,
                            prev_word=prev_core,
                            next_word=next_core,
                            context=context_model,
                            use_sentence_context=use_sentence_context,
                            min_confidence=min_confidence,
                        )
                        if rakara_prop is not None and rakara_prop["replacement"].startswith(
                            f"{core[0]}\u0c4dర"
                        ):
                            rakara_prop = {
                                **rakara_prop,
                                "original": f"({core}",
                                "reason": f"{rakara_prop['reason']} + recovered leading '(' → ్ర",
                            }
                        else:
                            rakara_prop = None
                    if rakara_prop is not None and (
                        proposal is None or (rakara_prop["confidence"] + 0.04) >= proposal["confidence"]
                    ):
                        proposal = rakara_prop
                        consumed_leading_paren = True

                if proposal is not None:
                    eff_lead = lead[:-1] if consumed_leading_paren else lead
                    parts[part_pos] = f"{eff_lead}{proposal['replacement']}{trail}"
                    cores[word_idx] = proposal["replacement"]
                    changes.append(proposal)
            working_text = "".join(parts)

    return working_text, changes


def propose_page_autocorrections(
    *,
    db: Session,
    book_id: uuid.UUID,
    page_number: int,
    primary_run_id: uuid.UUID | None = None,
    use_correction_memory: bool = True,
    use_dictionary: bool = True,
    use_sentence_context: bool = True,
    min_confidence: float = 0.78,
    current_texts: dict[str, str] | None = None,
    lexicon_path: Path | None = None,
    lexicon_override: TeluguLexicon | None = None,
) -> dict[str, Any]:
    """Generate opt-in auto-correction proposals for all non-ignored blocks on a page."""
    review = get_page_review_payload(
        db=db,
        book_id=book_id,
        page_number=page_number,
        primary_run_id=primary_run_id,
    )
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    active_corrections: list[CorrectionMemory] = []
    if use_correction_memory:
        active_corrections = list(
            db.scalars(
                select(CorrectionMemory).where(
                    CorrectionMemory.language_code == book.language_code,
                    CorrectionMemory.status == "active",
                    or_(
                        CorrectionMemory.scope == "global_suggestion",
                        CorrectionMemory.book_id == book.id,
                    ),
                )
            ).all()
        )
    by_incorrect, books_by_pair = build_suggestion_index(active_corrections, book.id)

    lexicon = lexicon_override if lexicon_override is not None else get_telugu_lexicon(lexicon_path)
    context_model = (
        build_sentence_context_model(db=db, book_id=book.id, language_code=book.language_code)
        if use_sentence_context
        else None
    )

    draft_overrides = current_texts or {}
    block_proposals: list[dict[str, Any]] = []
    changed_blocks = 0
    total_changes = 0
    scanned_blocks = 0

    for blk in review["blocks"]:
        if blk.get("latest_action") == "ignored" or blk.get("block_role") == "ignore":
            continue
        scanned_blocks += 1
        blk_id_str = str(blk["block_id"])
        source_text = draft_overrides.get(blk_id_str, blk["current_text"])
        if not source_text or not source_text.strip():
            continue

        proposed_text, changes = _autocorrect_single_block(
            block_text=source_text,
            book_id=book.id,
            by_incorrect=by_incorrect,
            books_by_pair=books_by_pair,
            lexicon=lexicon,
            context_model=context_model,
            use_correction_memory=use_correction_memory,
            use_dictionary=use_dictionary,
            use_sentence_context=use_sentence_context,
            min_confidence=min_confidence,
        )
        if changes and normalize_nfc(proposed_text).strip() != normalize_nfc(source_text).strip():
            changed_blocks += 1
            total_changes += len(changes)
            block_proposals.append(
                {
                    "block_id": blk["block_id"],
                    "original_text": source_text,
                    "proposed_text": proposed_text,
                    "changes": changes,
                }
            )

    return {
        "book_id": book.id,
        "page_number": page_number,
        "primary_run_id": review["primary_run_id"],
        "lexicon_word_count": len(lexicon.words),
        "total_blocks_scanned": scanned_blocks,
        "changed_blocks_count": changed_blocks,
        "total_changes_count": total_changes,
        "blocks": block_proposals,
    }
