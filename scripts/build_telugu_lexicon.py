#!/usr/bin/env python3
"""Build a local NFC-normalized Telugu dictionary/lexicon from open-licensed corpora.

Sources combined by default:
  1. LibreOffice te_IN Hunspell dictionary (curated modern Telugu words & inflections)
  2. C.P. Brown Telugu-English StarDict headwords (classical/literary Telugu)
  3. Telugu Janapada StarDict headwords (folk/regional/literary Telugu)
  4. hermitdave/FrequencyWords Telugu corpus frequencies
  5. frekwencja/most-common-words-multilingual Telugu high-frequency words
  6. (Optional --include-wiktionary) indic-dict Telugu Wiktionary headwords (~94 MB download)

Output:
  models/lexicon/telugu_lexicon.tsv.gz   (UTF-8 gzipped TSV: word<TAB>weight<TAB>sources)
  models/lexicon/manifest.json           (metadata, counts, SHA-256)
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    "libreoffice_te_in": {
        "flag": "L",
        "curated": True,
        "base_weight": 60,
        "url": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/te_IN/te_IN.dic",
    },
    "cp_brown_classical": {
        "flag": "B",
        "curated": True,
        "base_weight": 55,
        "url": "https://raw.githubusercontent.com/indic-dict/stardict-telugu/master/te-head/en-entries/brown/brown.babylon",
    },
    "janapada_literary": {
        "flag": "J",
        "curated": True,
        "base_weight": 35,
        "url": "https://raw.githubusercontent.com/indic-dict/stardict-telugu/master/te-head/en-entries/janapada/janapada.babylon",
    },
    "frequency_words_te": {
        "flag": "F",
        "curated": False,
        "base_weight": 0,
        "url": "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/te/te_full.txt",
    },
    "most_common_te": {
        "flag": "M",
        "curated": False,
        "base_weight": 0,
        "url": "https://raw.githubusercontent.com/frekwencja/most-common-words-multilingual/main/data/wordfrequency.info/te.txt",
    },
    "wiktionary_telugu": {
        "flag": "W",
        "curated": True,
        "base_weight": 45,
        "url": "https://raw.githubusercontent.com/indic-dict/stardict-telugu/master/te-head/te-entries/wiktionary_telugu/wiktionary_telugu.babylon",
    },
}

# Valid Telugu letters, vowel signs, anusvara/visarga/virama (excluding Telugu digits 0C66-0C6F).
_TELUGU_TOKEN_RE = re.compile(r"[\u0C01-\u0C63\u0C78-\u0C7F]+")
_TELUGU_LETTER_RE = re.compile(r"[\u0C05-\u0C39\u0C58-\u0C61]")
_VALID_SINGLE_CHAR_WORDS = {"ఆ", "ఈ", "ఏ", "ఓ", "ఒ", "ఉ", "ఊ"}
# Combining marks that cannot validly start a standalone Telugu word.
_COMBINING_START_RE = re.compile(r"^[\u0C00-\u0C04\u0C3E-\u0C56\u0C62-\u0C63]")


def normalize_telugu_token(raw: str) -> str | None:
    """Clean and NFC-normalize a candidate Telugu word; return None if invalid."""
    text = unicodedata.normalize("NFC", raw).strip()
    text = text.replace("\u200c", "").replace("\u200d", "").replace("\ufeff", "")
    if not text:
        return None
    if not _TELUGU_TOKEN_RE.fullmatch(text):
        return None
    if _COMBINING_START_RE.match(text):
        return None
    if not _TELUGU_LETTER_RE.search(text):
        return None
    if len(text) == 1 and text not in _VALID_SINGLE_CHAR_WORDS:
        return None
    if len(text) > 45:
        return None
    return text


def extract_telugu_tokens(text: str) -> list[str]:
    """Extract all valid Telugu tokens from a line or phrase."""
    nfc = unicodedata.normalize("NFC", text).replace("\u200c", "").replace("\u200d", "")
    out: list[str] = []
    for match in _TELUGU_TOKEN_RE.findall(nfc):
        tok = normalize_telugu_token(match)
        if tok:
            out.append(tok)
    return out


def fetch_url_text(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "telugu-digitizer-lexicon-builder/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def parse_hunspell_dic(content: str) -> dict[str, int]:
    words: dict[str, int] = {}
    lines = content.splitlines()
    for idx, line in enumerate(lines):
        if idx == 0 and line.strip().isdigit():
            continue
        head = line.split("/", 1)[0].split("\t", 1)[0].strip()
        tok = normalize_telugu_token(head)
        if tok:
            words[tok] = words.get(tok, 0) + 1
    return words


def parse_babylon_headwords(content: str) -> dict[str, int]:
    """Parse Babylon glossary format: entries separated by blank lines; line 1 has headwords separated by '|'."""
    words: dict[str, int] = {}
    expect_headword = True
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            expect_headword = True
            continue
        if stripped.startswith("#"):
            continue
        if expect_headword:
            expect_headword = False
            for part in stripped.split("|"):
                # Try full cleaned headword first, plus individual Telugu tokens inside multi-word phrases.
                exact = normalize_telugu_token(part)
                if exact:
                    words[exact] = words.get(exact, 0) + 2
                else:
                    for tok in extract_telugu_tokens(part):
                        words[tok] = words.get(tok, 0) + 1
    return words


def parse_frequency_words(content: str) -> dict[str, int]:
    words: dict[str, int] = {}
    for line in content.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        tok = normalize_telugu_token(parts[0])
        if not tok:
            continue
        try:
            freq = int(parts[1])
        except ValueError:
            continue
        if freq > 0:
            words[tok] = max(words.get(tok, 0), freq)
    return words


def parse_ranked_wordlist(content: str) -> dict[str, int]:
    words: dict[str, int] = {}
    rank = 0
    for line in content.splitlines():
        raw = line.strip().split()[0] if line.strip() else ""
        tok = normalize_telugu_token(raw)
        if not tok:
            continue
        rank += 1
        # Assign smooth rank-based weight (top words get high prior, tail gets modest boost)
        weight = max(12, int(20000 / (1 + rank * 0.04)))
        words[tok] = max(words.get(tok, 0), weight)
    return words


def build_lexicon(
    *,
    output_dir: Path,
    include_wiktionary: bool = False,
    min_unverified_freq: int = 4,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    weights: dict[str, int] = defaultdict(int)
    flags: dict[str, set[str]] = defaultdict(set)
    curated_words: set[str] = set()
    source_stats: dict[str, dict] = {}

    active_sources = [
        "libreoffice_te_in",
        "cp_brown_classical",
        "janapada_literary",
        "frequency_words_te",
        "most_common_te",
    ]
    if include_wiktionary:
        active_sources.append("wiktionary_telugu")

    for name in active_sources:
        meta = SOURCES[name]
        print(f"[lexicon] Fetching {name} from {meta['url']} ...", flush=True)
        text = fetch_url_text(meta["url"])
        if name == "libreoffice_te_in":
            parsed = parse_hunspell_dic(text)
        elif name in ("cp_brown_classical", "janapada_literary", "wiktionary_telugu"):
            parsed = parse_babylon_headwords(text)
        elif name == "frequency_words_te":
            parsed = parse_frequency_words(text)
        else:
            parsed = parse_ranked_wordlist(text)

        flag = meta["flag"]
        base_weight = int(meta["base_weight"])
        is_curated = bool(meta["curated"])

        for word, count in parsed.items():
            flags[word].add(flag)
            if is_curated:
                curated_words.add(word)
                weights[word] += base_weight + min(count * 5, 30)
            else:
                weights[word] += count

        source_stats[name] = {
            "url": meta["url"],
            "flag": flag,
            "curated": is_curated,
            "parsed_unique_words": len(parsed),
        }
        print(f"[lexicon]   -> {len(parsed):,} unique Telugu tokens", flush=True)

    # Filter out low-frequency uncurated tokens (prevents rare web-crawl typos from entering lexicon).
    final_entries: list[tuple[str, int, str]] = []
    dropped_unverified = 0
    for word, weight in weights.items():
        if word not in curated_words and weight < min_unverified_freq:
            dropped_unverified += 1
            continue
        flag_str = "".join(sorted(flags[word]))
        final_entries.append((word, weight, flag_str))

    # Sort descending by weight, then lexicographically for deterministic builds.
    final_entries.sort(key=lambda item: (-item[1], item[0]))

    lexicon_path = output_dir / "telugu_lexicon.tsv.gz"
    tsv_lines = [f"{w}\t{wt}\t{fl}\n" for w, wt, fl in final_entries]
    raw_tsv_bytes = "".join(tsv_lines).encode("utf-8")
    with gzip.open(lexicon_path, "wb", compresslevel=9) as gz:
        gz.write(raw_tsv_bytes)

    gz_bytes = lexicon_path.read_bytes()
    manifest = {
        "schema_version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "total_words": len(final_entries),
        "curated_words": len(curated_words),
        "dropped_low_freq_uncurated": dropped_unverified,
        "min_unverified_freq": min_unverified_freq,
        "include_wiktionary": include_wiktionary,
        "lexicon_file": lexicon_path.name,
        "compressed_bytes": len(gz_bytes),
        "uncompressed_bytes": len(raw_tsv_bytes),
        "sha256_gz": hashlib.sha256(gz_bytes).hexdigest(),
        "sources": source_stats,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"[lexicon] Wrote {len(final_entries):,} NFC Telugu words to {lexicon_path} "
        f"({len(gz_bytes) / 1024 / 1024:.2f} MB gz).",
        flush=True,
    )
    return manifest


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build local Telugu lexicon for OCR auto-correction.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "models" / "lexicon",
        help="Destination directory for telugu_lexicon.tsv.gz and manifest.json",
    )
    parser.add_argument(
        "--include-wiktionary",
        action="store_true",
        help="Also fetch 94 MB Telugu Wiktionary Babylon headwords.",
    )
    parser.add_argument(
        "--min-unverified-freq",
        type=int,
        default=4,
        help="Minimum corpus frequency required for tokens not in a curated dictionary.",
    )
    args = parser.parse_args()
    build_lexicon(
        output_dir=args.output_dir,
        include_wiktionary=args.include_wiktionary,
        min_unverified_freq=args.min_unverified_freq,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
