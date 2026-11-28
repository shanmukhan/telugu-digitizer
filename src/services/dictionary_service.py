"""Standalone Telugu Dictionary service backed by local SQLite + FTS5 and PostgreSQL custom words."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.db.models import CustomDictionaryWord
from src.evaluation.metrics import normalize_nfc
from src.services.lexicon_service import (
    SentenceContextModel,
    TeluguLexicon,
    _strip_edge_punct,
    get_telugu_lexicon,
    is_telugu_word,
    telugu_ocr_edit_distance,
)

LOGGER = logging.getLogger("telugu_digitizer.services.dictionary")

_DEFAULT_DICT_DB_PATH = Path(__file__).resolve().parents[2] / "models" / "lexicon" / "telugu_dictionary.sqlite"
_TELUGU_CHAR_RE = re.compile(r"[\u0C00-\u0C7F]")
_FTS_TOKEN_RE = re.compile(r"[A-Za-z0-9\u0C00-\u0C7F]+")

SOURCE_LABELS = {
    "cp_brown": "C.P. Brown (Classical)",
    "wiktionary_te": "Telugu Wiktionary",
    "janapada": "Janapada",
    "custom": "Custom Dictionary",
    "L": "LibreOffice te_IN",
    "B": "C.P. Brown",
    "J": "Janapada",
    "W": "Wiktionary",
    "F": "Frequency Corpus",
    "M": "Common Words",
}


def _open_readonly_sqlite(db_path: Path | None) -> sqlite3.Connection | None:
    target = (db_path or _DEFAULT_DICT_DB_PATH).resolve()
    if not target.is_file():
        return None
    conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_source_flags(flag_str: str) -> list[str]:
    labels: list[str] = []
    for ch in flag_str or "":
        lbl = SOURCE_LABELS.get(ch)
        if lbl and lbl not in labels:
            labels.append(lbl)
    return labels


def _custom_word_definitions(row: CustomDictionaryWord) -> list[dict[str, str]]:
    defs: list[dict[str, str]] = []
    if row.meaning_en and row.meaning_en.strip():
        defs.append({"source": "custom", "lang": "en", "definition": row.meaning_en.strip()})
    if row.meaning_te and row.meaning_te.strip():
        defs.append({"source": "custom", "lang": "te", "definition": row.meaning_te.strip()})
    if row.notes and row.notes.strip() and not defs:
        defs.append({"source": "custom", "lang": "te", "definition": row.notes.strip()})
    return defs


def _load_custom_context(db: Session, language_code: str = "te") -> SentenceContextModel:
    ctx = SentenceContextModel()
    for w in db.scalars(
        select(CustomDictionaryWord.word).where(CustomDictionaryWord.language_code == language_code)
    ).all():
        if w:
            ctx.add_sentence(w, same_book=True, weight=5)
    return ctx


def _suggest_alternatives(
    word: str,
    lexicon: TeluguLexicon,
    custom_ctx: SentenceContextModel | None = None,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Return ranked 'did you mean?' Telugu spelling suggestions for an unknown Telugu word."""
    clean = normalize_nfc(word).strip()
    if not clean or not is_telugu_word(clean) or len(clean) < 2:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    best = lexicon.suggest_word(clean, context=custom_ctx, min_confidence=0.68)
    if best is not None:
        seen.add(best["replacement"])
        out.append(
            {
                "word": best["replacement"],
                "confidence": best["confidence"],
                "reason": best["reason"],
            }
        )

    cands = lexicon._raw_candidates_for_unit(clean, custom_ctx)
    ranked: list[tuple[float, str]] = []
    for c in cands:
        if c in seen:
            continue
        dist = telugu_ocr_edit_distance(clean, c)
        if dist <= 1.8:
            weight = lexicon.words.get(c, 50)
            score = -dist * 2.0 + (0.25 if weight >= 500 else 0.0) + min(weight, 5000) / 10000.0
            ranked.append((score, c))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    for _, cand in ranked[: max(0, max_items - len(out))]:
        dist = telugu_ocr_edit_distance(clean, cand)
        conf = round(max(0.5, min(0.95, 1.0 - dist / max(2.2, len(clean) * 0.45))), 3)
        out.append({"word": cand, "confidence": conf, "reason": "Telugu spelling / OCR similarity"})
    return out


def get_dictionary_stats(
    *,
    db: Session,
    dictionary_db_path: Path | None = None,
    lexicon_path: Path | None = None,
) -> dict[str, Any]:
    """Return dictionary corpus statistics (SQLite definitions DB + PostgreSQL custom words)."""
    custom_count = int(
        db.scalar(
            select(func.count(CustomDictionaryWord.id)).where(CustomDictionaryWord.language_code == "te")
        )
        or 0
    )
    conn = _open_readonly_sqlite(dictionary_db_path)
    if conn is not None:
        try:
            meta_rows = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
            src_counts = {}
            if "source_definition_counts" in meta_rows:
                try:
                    src_counts = json.loads(meta_rows["source_definition_counts"])
                except ValueError:
                    src_counts = {}
            return {
                "available": True,
                "has_definitions_db": True,
                "total_words": int(meta_rows.get("total_words", "0")),
                "words_with_definitions": int(meta_rows.get("words_with_definitions", "0")),
                "total_definitions": int(meta_rows.get("total_definitions", "0")),
                "custom_words_count": custom_count,
                "source_definition_counts": src_counts,
                "built_at": meta_rows.get("built_at"),
            }
        finally:
            conn.close()

    lex = get_telugu_lexicon(lexicon_path)
    return {
        "available": len(lex.words) > 0 or custom_count > 0,
        "has_definitions_db": False,
        "total_words": len(lex.words),
        "words_with_definitions": 0,
        "total_definitions": 0,
        "custom_words_count": custom_count,
        "source_definition_counts": {},
        "built_at": None,
    }


def _fetch_definitions_for_word_ids(
    conn: sqlite3.Connection,
    word_ids: list[int],
    max_per_word: int = 4,
) -> dict[int, list[dict[str, str]]]:
    if not word_ids:
        return {}
    placeholders = ",".join("?" for _ in word_ids)
    sql = (
        f"SELECT word_id, source, lang, definition FROM definitions "
        f"WHERE word_id IN ({placeholders}) "
        f"ORDER BY CASE source WHEN 'cp_brown' THEN 1 WHEN 'wiktionary_te' THEN 2 ELSE 3 END, id ASC"
    )
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in conn.execute(sql, word_ids):
        wid = int(row["word_id"])
        bucket = grouped.setdefault(wid, [])
        if len(bucket) < max_per_word:
            bucket.append(
                {
                    "source": str(row["source"]),
                    "lang": str(row["lang"]),
                    "definition": str(row["definition"]),
                }
            )
    return grouped


def search_dictionary(
    *,
    db: Session,
    query: str,
    mode: str = "auto",
    limit: int = 25,
    dictionary_db_path: Path | None = None,
    lexicon_path: Path | None = None,
) -> dict[str, Any]:
    """Search Telugu dictionary by Telugu headword/prefix, English meaning, or Latin transliteration."""
    q_clean = normalize_nfc(query).strip()
    safe_limit = max(1, min(limit, 50))
    if not q_clean:
        return {
            "query": "",
            "detected_mode": "telugu",
            "exact_match": False,
            "items": [],
            "did_you_mean": [],
        }

    is_te_query = bool(_TELUGU_CHAR_RE.search(q_clean))
    effective_mode = ("telugu" if is_te_query else "english") if mode == "auto" else mode
    if effective_mode not in ("telugu", "english"):
        raise AppError("INVALID_SEARCH_MODE", f"Unsupported search mode {mode!r}.", status_code=400)

    items: list[dict[str, Any]] = []
    seen_words: set[str] = set()
    exact_match = False

    # 1. Search PostgreSQL custom words first.
    q_lower = q_clean.lower()
    custom_rows = list(
        db.scalars(
            select(CustomDictionaryWord)
            .where(CustomDictionaryWord.language_code == "te")
            .order_by(CustomDictionaryWord.created_at.desc())
        ).all()
    )
    for row in custom_rows:
        w_nfc = normalize_nfc(row.word).strip()
        matched_custom = False
        if effective_mode == "telugu":
            matched_custom = w_nfc == q_clean or w_nfc.startswith(q_clean)
        else:
            haystack = " ".join(
                filter(None, [row.translit, row.meaning_en, row.meaning_te, row.notes])
            ).lower()
            matched_custom = q_lower in haystack
        if matched_custom:
            if w_nfc == q_clean:
                exact_match = True
            seen_words.add(w_nfc)
            items.append(
                {
                    "word": w_nfc,
                    "weight": 10000,
                    "sources": ["Custom Dictionary"],
                    "translit": row.translit or "",
                    "has_definition": bool(_custom_word_definitions(row)),
                    "is_custom": True,
                    "custom_word_id": row.id,
                    "definitions": _custom_word_definitions(row),
                }
            )

    # 2. Search SQLite reference dictionary.
    conn = _open_readonly_sqlite(dictionary_db_path)
    if conn is not None:
        try:
            if effective_mode == "telugu":
                exact_row = conn.execute(
                    "SELECT id, word, weight, sources, translit, has_definition FROM words WHERE word = ?",
                    (q_clean,),
                ).fetchone()
                matched_rows: list[sqlite3.Row] = []
                if exact_row is not None:
                    exact_match = True
                    matched_rows.append(exact_row)

                prefix_end = q_clean + "\uffff"
                prefix_rows = conn.execute(
                    """
                    SELECT id, word, weight, sources, translit, has_definition
                    FROM words
                    WHERE word >= ? AND word < ?
                    ORDER BY has_definition DESC, weight DESC, length(word) ASC
                    LIMIT ?
                    """,
                    (q_clean, prefix_end, safe_limit + 5),
                ).fetchall()
                for pr in prefix_rows:
                    if exact_row is not None and pr["id"] == exact_row["id"]:
                        continue
                    matched_rows.append(pr)
                    if len(matched_rows) >= safe_limit:
                        break

                defs_by_id = _fetch_definitions_for_word_ids(conn, [int(r["id"]) for r in matched_rows])
                for r in matched_rows:
                    w = str(r["word"])
                    if w in seen_words:
                        # Merge SQLite definitions into existing custom entry.
                        for existing in items:
                            if existing["word"] == w:
                                existing["sources"] = list(
                                    dict.fromkeys(existing["sources"] + _parse_source_flags(str(r["sources"])))
                                )
                                existing["definitions"].extend(defs_by_id.get(int(r["id"]), []))
                                existing["has_definition"] = bool(existing["definitions"])
                        continue
                    seen_words.add(w)
                    defs = defs_by_id.get(int(r["id"]), [])
                    items.append(
                        {
                            "word": w,
                            "weight": int(r["weight"]),
                            "sources": _parse_source_flags(str(r["sources"])),
                            "translit": str(r["translit"] or ""),
                            "has_definition": bool(defs),
                            "is_custom": False,
                            "custom_word_id": None,
                            "definitions": defs,
                        }
                    )
                    if len(items) >= safe_limit:
                        break
            else:
                # English meaning or Latin transliteration search via FTS5.
                tokens = _FTS_TOKEN_RE.findall(q_lower)
                if tokens:
                    if len(tokens) == 1:
                        fts_query = f'"{tokens[0]}"*'
                    else:
                        fts_query = " AND ".join(f'"{t}"' for t in tokens[:6])
                    fts_rows = conn.execute(
                        """
                        SELECT DISTINCT w.id, w.word, w.weight, w.sources, w.translit, w.has_definition,
                               bm25(dictionary_fts, 1.0, 2.5, 1.5) AS rank_score
                        FROM dictionary_fts
                        JOIN words w ON w.id = dictionary_fts.word_id
                        WHERE dictionary_fts MATCH ?
                        ORDER BY rank_score ASC, w.weight DESC
                        LIMIT ?
                        """,
                        (fts_query, safe_limit * 2),
                    ).fetchall()
                    unique_rows: list[sqlite3.Row] = []
                    seen_ids: set[int] = set()
                    for r in fts_rows:
                        wid = int(r["id"])
                        if wid in seen_ids:
                            continue
                        seen_ids.add(wid)
                        unique_rows.append(r)
                        if len(unique_rows) >= safe_limit:
                            break
                    defs_by_id = _fetch_definitions_for_word_ids(conn, [int(r["id"]) for r in unique_rows])
                    for r in unique_rows:
                        w = str(r["word"])
                        if w in seen_words:
                            continue
                        seen_words.add(w)
                        defs = defs_by_id.get(int(r["id"]), [])
                        items.append(
                            {
                                "word": w,
                                "weight": int(r["weight"]),
                                "sources": _parse_source_flags(str(r["sources"])),
                                "translit": str(r["translit"] or ""),
                                "has_definition": bool(defs),
                                "is_custom": False,
                                "custom_word_id": None,
                                "definitions": defs,
                            }
                        )
                        if len(items) >= safe_limit:
                            break
        finally:
            conn.close()
    else:
        # Fallback to in-memory lexicon when SQLite definitions DB is absent.
        if effective_mode == "telugu":
            lex = get_telugu_lexicon(lexicon_path)
            if q_clean in lex.words:
                exact_match = True
            matches = [w for w in lex.words if w.startswith(q_clean) and w not in seen_words]
            matches.sort(key=lambda w: (-lex.words.get(w, 0), len(w)))
            for w in matches[:safe_limit]:
                seen_words.add(w)
                items.append(
                    {
                        "word": w,
                        "weight": lex.words.get(w, 10),
                        "sources": ["Telugu Lexicon"],
                        "translit": "",
                        "has_definition": False,
                        "is_custom": False,
                        "custom_word_id": None,
                        "definitions": [],
                    }
                )

    did_you_mean: list[dict[str, Any]] = []
    if effective_mode == "telugu" and not exact_match:
        lex = get_telugu_lexicon(lexicon_path)
        custom_ctx = _load_custom_context(db)
        did_you_mean = _suggest_alternatives(q_clean, lex, custom_ctx)

    return {
        "query": q_clean,
        "detected_mode": effective_mode,
        "exact_match": exact_match,
        "items": items[:safe_limit],
        "did_you_mean": did_you_mean,
    }


def get_dictionary_word(
    *,
    db: Session,
    word: str,
    dictionary_db_path: Path | None = None,
    lexicon_path: Path | None = None,
) -> dict[str, Any]:
    """Fetch complete details and all definitions for a single Telugu word."""
    w_clean = normalize_nfc(word).strip()
    if not w_clean:
        raise AppError("INVALID_WORD", "Word must not be empty.", status_code=400)

    custom_row = db.scalars(
        select(CustomDictionaryWord).where(
            CustomDictionaryWord.language_code == "te",
            CustomDictionaryWord.word == w_clean,
        )
    ).first()

    definitions: list[dict[str, str]] = []
    sources: list[str] = []
    translit = ""
    weight = 0
    found = False

    if custom_row is not None:
        found = True
        sources.append("Custom Dictionary")
        translit = custom_row.translit or ""
        definitions.extend(_custom_word_definitions(custom_row))

    conn = _open_readonly_sqlite(dictionary_db_path)
    if conn is not None:
        try:
            row = conn.execute(
                "SELECT id, word, weight, sources, translit FROM words WHERE word = ?",
                (w_clean,),
            ).fetchone()
            if row is not None:
                found = True
                weight = int(row["weight"])
                sources = list(dict.fromkeys(sources + _parse_source_flags(str(row["sources"]))))
                if not translit and row["translit"]:
                    translit = str(row["translit"])
                defs_map = _fetch_definitions_for_word_ids(conn, [int(row["id"])], max_per_word=20)
                definitions.extend(defs_map.get(int(row["id"]), []))
        finally:
            conn.close()

    lex = get_telugu_lexicon(lexicon_path)
    custom_ctx = _load_custom_context(db)
    is_valid_inflected = found or lex.is_known_word(w_clean, custom_ctx)
    did_you_mean = [] if is_valid_inflected else _suggest_alternatives(w_clean, lex, custom_ctx)

    return {
        "word": w_clean,
        "found": found,
        "is_valid_word": is_valid_inflected,
        "weight": weight,
        "sources": sources,
        "translit": translit,
        "is_custom": custom_row is not None,
        "custom_word_id": custom_row.id if custom_row is not None else None,
        "definitions": definitions,
        "did_you_mean": did_you_mean,
    }


def check_telugu_text(
    *,
    db: Session,
    text: str,
    lexicon_path: Path | None = None,
) -> dict[str, Any]:
    """Spellcheck a pasted Telugu sentence or paragraph against the lexicon + custom dictionary."""
    normalized = normalize_nfc(text)
    raw_tokens = normalized.split()
    lex = get_telugu_lexicon(lexicon_path)
    custom_ctx = _load_custom_context(db)

    cores = [_strip_edge_punct(tok)[1] for tok in raw_tokens]
    total_telugu = 0
    known_count = 0
    unknown_count = 0
    issues: list[dict[str, Any]] = []

    for idx, raw_tok in enumerate(raw_tokens):
        _, core, _ = _strip_edge_punct(raw_tok)
        if not core or not is_telugu_word(core):
            continue
        total_telugu += 1
        if len(core) < 3 or lex.is_known_word(core, custom_ctx):
            known_count += 1
            continue
        unknown_count += 1
        prev_core = cores[idx - 1] if idx > 0 and is_telugu_word(cores[idx - 1]) else None
        next_core = cores[idx + 1] if idx + 1 < len(cores) and is_telugu_word(cores[idx + 1]) else None
        best = lex.suggest_word(
            core,
            prev_word=prev_core,
            next_word=next_core,
            context=custom_ctx,
            min_confidence=0.72,
        )
        alts = _suggest_alternatives(core, lex, custom_ctx, max_items=5)
        issues.append(
            {
                "token": core,
                "token_index": idx,
                "best_replacement": best["replacement"] if best else (alts[0]["word"] if alts else None),
                "confidence": best["confidence"] if best else (alts[0]["confidence"] if alts else None),
                "reason": best["reason"] if best else ("Spelling suggestion" if alts else "Not found in Telugu dictionary"),
                "suggestions": [a["word"] for a in alts],
            }
        )

    return {
        "total_telugu_words": total_telugu,
        "known_words_count": known_count,
        "unknown_words_count": unknown_count,
        "issues": issues,
    }


def list_custom_words(db: Session, query: str | None = None) -> list[CustomDictionaryWord]:
    stmt = (
        select(CustomDictionaryWord)
        .where(CustomDictionaryWord.language_code == "te")
        .order_by(CustomDictionaryWord.created_at.desc())
    )
    rows = list(db.scalars(stmt).all())
    if query and query.strip():
        q_nfc = normalize_nfc(query).strip().lower()
        rows = [
            r
            for r in rows
            if q_nfc in normalize_nfc(r.word).lower()
            or (r.meaning_en and q_nfc in r.meaning_en.lower())
            or (r.meaning_te and q_nfc in normalize_nfc(r.meaning_te).lower())
            or (r.translit and q_nfc in r.translit.lower())
        ]
    return rows


def create_custom_word(
    *,
    db: Session,
    word: str,
    translit: str | None = None,
    meaning_en: str | None = None,
    meaning_te: str | None = None,
    notes: str | None = None,
) -> CustomDictionaryWord:
    cleaned = normalize_nfc(word).strip()
    if not cleaned or not _TELUGU_CHAR_RE.search(cleaned):
        raise AppError(
            "INVALID_TELUGU_WORD",
            "Custom dictionary word must contain Telugu characters.",
            status_code=400,
        )
    if len(cleaned) > 120:
        raise AppError("WORD_TOO_LONG", "Word must be at most 120 characters.", status_code=400)

    existing = db.scalars(
        select(CustomDictionaryWord).where(
            CustomDictionaryWord.language_code == "te",
            CustomDictionaryWord.word == cleaned,
        )
    ).first()
    if existing is not None:
        if translit is not None:
            existing.translit = translit.strip() or None
        if meaning_en is not None:
            existing.meaning_en = meaning_en.strip() or None
        if meaning_te is not None:
            existing.meaning_te = normalize_nfc(meaning_te).strip() or None
        if notes is not None:
            existing.notes = notes.strip() or None
        db.commit()
        db.refresh(existing)
        return existing

    entry = CustomDictionaryWord(
        language_code="te",
        word=cleaned,
        translit=translit.strip() if translit and translit.strip() else None,
        meaning_en=meaning_en.strip() if meaning_en and meaning_en.strip() else None,
        meaning_te=normalize_nfc(meaning_te).strip() if meaning_te and meaning_te.strip() else None,
        notes=notes.strip() if notes and notes.strip() else None,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    LOGGER.info("Added custom Telugu dictionary word: %s", entry.word)
    return entry


def delete_custom_word(db: Session, word_id: uuid.UUID) -> None:
    row = db.get(CustomDictionaryWord, word_id)
    if row is None:
        raise AppError("CUSTOM_WORD_NOT_FOUND", f"Custom word {word_id} not found.", status_code=404)
    db.delete(row)
    db.commit()
