#!/usr/bin/env python3
"""Build a compact, indexed SQLite + FTS5 Telugu Dictionary database with definitions.

Combines:
  - models/lexicon/telugu_lexicon.tsv.gz (186k+ NFC Telugu words + frequency weights + source flags)
  - C.P. Brown Classical Telugu-English definitions (brown.babylon)
  - Janapada Telugu-English definitions (janapada.babylon)
  - Telugu Wiktionary Telugu/English definitions (wiktionary_telugu.babylon)

Output:
  models/lexicon/telugu_dictionary.sqlite
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sqlite3
import sys
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DICTIONARY_SOURCES = (
    (
        "cp_brown",
        "en",
        "B",
        "https://raw.githubusercontent.com/indic-dict/stardict-telugu/master/te-head/en-entries/brown/brown.babylon",
    ),
    (
        "janapada",
        "en",
        "J",
        "https://raw.githubusercontent.com/indic-dict/stardict-telugu/master/te-head/en-entries/janapada/janapada.babylon",
    ),
    (
        "wiktionary_te",
        "te",
        "W",
        "https://raw.githubusercontent.com/indic-dict/stardict-telugu/master/te-head/te-entries/wiktionary_telugu/wiktionary_telugu.babylon",
    ),
)

_TELUGU_CHAR_RE = re.compile(r"[\u0C05-\u0C39\u0C58-\u0C61]")
_ASCII_TRANSLIT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 '\-]{0,48}$")
_BR_RE = re.compile(r"(?i)<br\s*/?>")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_RULE_LINE_RE = re.compile(r"^[\u2500-\u257F\u2014\u2013=\-_*~]{3,}$")
_BOILERPLATE_LINE_RE = re.compile(
    r"^(?:│♫\s*ఉచ్చారణము│|తెలుగు\s*పద(?:ం|ము)\s*:|దేవనాగరి\s*:|देवनागरि\s*:|ఉచ్ఛారణ\s*:|ఇతర\s*భాషల\s*పదములు)\s*"
)
_SECTION_DECOR_RE = re.compile(r"[│☘⚪♫•]+")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def _fetch_text(url: str, timeout: int = 120) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "telugu-digitizer-dictionary-builder/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def _clean_headword(raw: str) -> str | None:
    text = unicodedata.normalize("NFC", raw).strip()
    text = text.replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    text = text.strip(".,;:!?\"'()[]{}—–-।॥ ")
    if not text or len(text) > 64:
        return None
    if not _TELUGU_CHAR_RE.search(text):
        return None
    return text


def _clean_definition(raw_body: str, source: str) -> str:
    text = html.unescape(raw_body)
    text = _BR_RE.sub("\n", text)
    text = _HTML_TAG_RE.sub("", text)
    text = unicodedata.normalize("NFC", text)
    lines: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if _RULE_LINE_RE.match(s):
            continue
        if source in ("janapada", "wiktionary_te") and _BOILERPLATE_LINE_RE.match(s):
            continue
        s = _SECTION_DECOR_RE.sub(" ", s)
        s = _MULTI_SPACE_RE.sub(" ", s).strip()
        if s:
            lines.append(s)
    cleaned = "\n".join(lines).strip()
    cleaned = _MULTI_NEWLINE_RE.sub("\n\n", cleaned)
    if len(cleaned) > 2500:
        cleaned = cleaned[:2497].rstrip() + "..."
    return cleaned


def parse_babylon_entries(content: str, source: str) -> tuple[dict[str, list[str]], dict[str, set[str]]]:
    """Return (definitions_by_word, transliterations_by_word) from a Babylon file."""
    defs_by_word: dict[str, list[str]] = defaultdict(list)
    seen_sigs: dict[str, set[str]] = defaultdict(set)
    translit_by_word: dict[str, set[str]] = defaultdict(set)

    expect_headword = True
    current_heads: list[str] = []
    current_translits: list[str] = []
    body_lines: list[str] = []

    def _flush() -> None:
        if not current_heads or not body_lines:
            return
        cleaned_def = _clean_definition("\n".join(body_lines), source)
        if not cleaned_def or len(cleaned_def) < 2:
            return
        sig = re.sub(r"\s+", " ", cleaned_def[:180]).lower()
        for hw in current_heads:
            if sig not in seen_sigs[hw] and len(defs_by_word[hw]) < 12:
                seen_sigs[hw].add(sig)
                defs_by_word[hw].append(cleaned_def)
            for tr in current_translits:
                if len(translit_by_word[hw]) < 6:
                    translit_by_word[hw].add(tr)

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            _flush()
            expect_headword = True
            current_heads = []
            current_translits = []
            body_lines = []
            continue
        if stripped.startswith("#"):
            continue
        if expect_headword:
            expect_headword = False
            for part in stripped.split("|"):
                p = part.strip()
                if not p:
                    continue
                hw = _clean_headword(p)
                if hw:
                    if hw not in current_heads:
                        current_heads.append(hw)
                elif _ASCII_TRANSLIT_RE.match(p):
                    tr = p.lower()
                    if tr not in current_translits and len(tr) >= 2:
                        current_translits.append(tr)
        else:
            body_lines.append(stripped)
    _flush()
    return defs_by_word, translit_by_word


def build_dictionary_db(*, lexicon_path: Path, output_db: Path) -> dict:
    output_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = output_db.with_suffix(".sqlite.tmp")
    if tmp_db.exists():
        tmp_db.unlink()

    # 1. Seed base vocabulary from telugu_lexicon.tsv.gz if present.
    word_weights: dict[str, int] = {}
    word_flags: dict[str, set[str]] = defaultdict(set)
    if lexicon_path.is_file():
        print(f"[dict-db] Reading base lexicon {lexicon_path} ...", flush=True)
        with gzip.open(lexicon_path, "rt", encoding="utf-8") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if not parts or not parts[0]:
                    continue
                w = unicodedata.normalize("NFC", parts[0]).strip()
                wt = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
                fl = parts[2] if len(parts) > 2 else "L"
                word_weights[w] = wt
                word_flags[w].update(fl)
        print(f"[dict-db]   -> {len(word_weights):,} base lexicon words", flush=True)

    # 2. Fetch and parse definitions from C.P. Brown, Janapada, and Telugu Wiktionary.
    all_defs: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    global_seen_def: dict[str, set[str]] = defaultdict(set)
    all_translits: dict[str, set[str]] = defaultdict(set)
    source_def_counts: dict[str, int] = {}

    for src_name, lang, flag, url in DICTIONARY_SOURCES:
        print(f"[dict-db] Fetching {src_name} from {url} ...", flush=True)
        raw = _fetch_text(url)
        defs_map, translits_map = parse_babylon_entries(raw, src_name)
        added_defs = 0
        for hw, def_list in defs_map.items():
            if hw not in word_weights:
                word_weights[hw] = 45
            word_flags[hw].add(flag)
            for dtext in def_list:
                # Avoid cross-source duplicates (Janapada repeats many C.P. Brown entries).
                sig = re.sub(r"[\W_]+", "", dtext[:120].lower())
                if sig and sig in global_seen_def[hw]:
                    continue
                if sig:
                    global_seen_def[hw].add(sig)
                all_defs[hw].append((src_name, lang, dtext))
                added_defs += 1
        for hw, tr_set in translits_map.items():
            all_translits[hw].update(tr_set)
        source_def_counts[src_name] = added_defs
        print(f"[dict-db]   -> {len(defs_map):,} headwords, {added_defs:,} unique definitions", flush=True)

    # 3. Write compact indexed SQLite + FTS5 database.
    print(f"[dict-db] Writing SQLite database to {output_db} ...", flush=True)
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("PRAGMA journal_mode = OFF;")
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA temp_store = MEMORY;")

    conn.executescript(
        """
        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            weight INTEGER NOT NULL DEFAULT 10,
            sources TEXT NOT NULL DEFAULT '',
            translit TEXT NOT NULL DEFAULT '',
            has_definition INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word_id INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            lang TEXT NOT NULL,
            definition TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE dictionary_fts USING fts5(
            word,
            translit,
            definition,
            source UNINDEXED,
            word_id UNINDEXED,
            tokenize = 'unicode61 remove_diacritics 2'
        );
        """
    )

    sorted_words = sorted(word_weights.items(), key=lambda item: (-item[1], item[0]))
    word_id_map: dict[str, int] = {}
    words_batch: list[tuple[str, int, str, str, int]] = []
    for w, wt in sorted_words:
        fl_str = "".join(sorted(word_flags.get(w, set())))
        tr_str = " ".join(sorted(all_translits.get(w, set()))[:5])
        has_def = 1 if w in all_defs else 0
        words_batch.append((w, wt, fl_str, tr_str, has_def))

    conn.executemany(
        "INSERT INTO words (word, weight, sources, translit, has_definition) VALUES (?, ?, ?, ?, ?)",
        words_batch,
    )
    for wid, w in conn.execute("SELECT id, word FROM words"):
        word_id_map[w] = wid

    def_rows: list[tuple[int, str, str, str]] = []
    fts_rows: list[tuple[str, str, str, str, int]] = []
    for w, def_tuples in all_defs.items():
        wid = word_id_map[w]
        tr_str = " ".join(sorted(all_translits.get(w, set()))[:5])
        for src_name, lang, dtext in def_tuples:
            def_rows.append((wid, src_name, lang, dtext))
            fts_rows.append((w, tr_str, dtext, src_name, wid))

    conn.executemany(
        "INSERT INTO definitions (word_id, source, lang, definition) VALUES (?, ?, ?, ?)",
        def_rows,
    )
    conn.executemany(
        "INSERT INTO dictionary_fts (word, translit, definition, source, word_id) VALUES (?, ?, ?, ?, ?)",
        fts_rows,
    )

    conn.executescript(
        """
        CREATE INDEX idx_words_prefix ON words(word COLLATE BINARY);
        CREATE INDEX idx_words_weight ON words(has_definition DESC, weight DESC);
        CREATE INDEX idx_definitions_word_id ON definitions(word_id);
        INSERT INTO dictionary_fts(dictionary_fts) VALUES('optimize');
        """
    )

    stats = {
        "schema_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "total_words": len(sorted_words),
        "words_with_definitions": len(all_defs),
        "total_definitions": len(def_rows),
        "source_definition_counts": source_def_counts,
    }
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [(k, json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)) for k, v in stats.items()],
    )
    conn.commit()
    conn.execute("VACUUM;")
    conn.close()

    tmp_db.replace(output_db)
    size_mb = output_db.stat().st_size / (1024 * 1024)
    stats["sqlite_bytes"] = output_db.stat().st_size
    print(
        f"[dict-db] Built {output_db} ({size_mb:.2f} MB): "
        f"{stats['total_words']:,} words, {stats['words_with_definitions']:,} with definitions "
        f"({stats['total_definitions']:,} total definitions).",
        flush=True,
    )
    return stats


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build SQLite + FTS5 Telugu dictionary database.")
    parser.add_argument(
        "--lexicon-path",
        type=Path,
        default=repo_root / "models" / "lexicon" / "telugu_lexicon.tsv.gz",
    )
    parser.add_argument(
        "--output-db",
        type=Path,
        default=repo_root / "models" / "lexicon" / "telugu_dictionary.sqlite",
    )
    args = parser.parse_args()
    build_dictionary_db(lexicon_path=args.lexicon_path, output_db=args.output_db)
    return 0


if __name__ == "__main__":
    sys.exit(main())
