"""Grouped benchmark aggregation, heuristic error cues, and CSV/JSON/Markdown reports."""

from __future__ import annotations

import difflib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from src.common.io import atomic_write_json, atomic_write_text
from src.evaluation.metrics import aggregate_metrics, normalize_nfc, split_scored_lines

_TELUGU_VOWEL_SIGNS = set(range(0x0C3E, 0x0C4D)) | {0x0C55, 0x0C56, 0x0C01, 0x0C02, 0x0C03}
_VIRAMA = "\u0c4d"
_ZWNJ_ZWJ = {"\u200c", "\u200d"}
_PUNCTUATION = set(".,;:!?\"'()[]{}-–—/|।॥")


def classify_line_error_cues(ref_line: str, hyp_line: str) -> list[str]:
    """Heuristically tag candidate error categories from 05-benchmark-methodology.md."""
    if not hyp_line.strip():
        return ["omission"]
    if not ref_line.strip():
        return ["insertion"]

    categories: set[str] = set()
    matcher = difflib.SequenceMatcher(None, ref_line, hyp_line)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        ref_seg = ref_line[i1:i2]
        hyp_seg = hyp_line[j1:j2]
        combined = ref_seg + hyp_seg

        if any(ch.isspace() for ch in combined):
            categories.add("word_boundary")
        if any(ch.isdigit() for ch in combined):
            categories.add("numeral")
        if any(ch in _PUNCTUATION for ch in combined):
            categories.add("punctuation")
        if _VIRAMA in combined or any(ch in _ZWNJ_ZWJ for ch in combined):
            categories.add("conjunct_or_virama")
        if any(ord(ch) in _TELUGU_VOWEL_SIGNS for ch in combined):
            categories.add("vowel_sign")
        if tag == "delete" and not any(ord(ch) in _TELUGU_VOWEL_SIGNS or ch == _VIRAMA for ch in ref_seg):
            categories.add("omission")
        elif tag == "insert" and not any(ord(ch) in _TELUGU_VOWEL_SIGNS or ch == _VIRAMA for ch in hyp_seg):
            categories.add("insertion")
        elif any("\u0c00" <= ch <= "\u0c7f" for ch in combined):
            categories.add("glyph_confusion")

    return sorted(categories) if categories else ["glyph_confusion"]


def extract_error_examples(
    page_rows: list[dict[str, Any]],
    limit: int = 10,
) -> tuple[dict[str, dict[str, int]], list[dict[str, Any]]]:
    """Summarize heuristic error categories and worst page/line mismatches per engine."""
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    worst_examples: list[dict[str, Any]] = []

    by_engine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in page_rows:
        if row.get("scored"):
            by_engine[str(row["engine"])].append(row)

    for engine, rows in by_engine.items():
        ranked = sorted(
            rows,
            key=lambda r: (
                -(r["nfc_cer"] if r.get("nfc_cer") is not None else 0.0),
                -int(r.get("nfc_edits", 0)),
            ),
        )
        for row in ranked:
            ref_lines = split_scored_lines(normalize_nfc(row.get("_reference_raw", "")))
            hyp_lines = split_scored_lines(normalize_nfc(row.get("_hypothesis_raw", "")))
            line_diffs: list[dict[str, Any]] = []
            for idx in range(max(len(ref_lines), len(hyp_lines))):
                r_line = ref_lines[idx] if idx < len(ref_lines) else ""
                h_line = hyp_lines[idx] if idx < len(hyp_lines) else ""
                if r_line != h_line:
                    cues = classify_line_error_cues(r_line, h_line)
                    for cue in cues:
                        category_counts[engine][cue] += 1
                    line_diffs.append(
                        {
                            "line_index": idx + 1,
                            "reference": r_line,
                            "hypothesis": h_line,
                            "heuristic_categories": cues,
                        }
                    )
            if line_diffs and len([e for e in worst_examples if e["engine"] == engine]) < limit:
                worst_examples.append(
                    {
                        "engine": engine,
                        "book_id": row["book_id"],
                        "page_number": row["page_number"],
                        "page_quality": row.get("page_quality", "unspecified"),
                        "layout_type": row.get("layout_type", "unspecified"),
                        "nfc_cer": row.get("nfc_cer"),
                        "grapheme_er": row.get("grapheme_er"),
                        "line_diffs": line_diffs[:5],
                    }
                )

    counts_dict = {eng: dict(cnt.most_common()) for eng, cnt in category_counts.items()}
    return counts_dict, worst_examples


def compute_grouped_summaries(
    page_rows: list[dict[str, Any]],
    warm_latencies_by_engine: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    """Group metrics overall and by book, page_quality, layout_type, and split."""
    overall: dict[str, Any] = {}
    by_engine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in page_rows:
        by_engine[str(row["engine"])].append(row)

    for engine, rows in sorted(by_engine.items()):
        warm = warm_latencies_by_engine.get(engine) if warm_latencies_by_engine else None
        overall[engine] = aggregate_metrics(rows, warm_elapsed_ms=warm)

    grouped: dict[str, dict[str, Any]] = {}
    for dimension in ("book_id", "page_quality", "layout_type", "split"):
        buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in page_rows:
            buckets[(str(row["engine"]), str(row.get(dimension, "unspecified")))].append(row)
        dim_map: dict[str, Any] = {}
        for (engine, group_val), rows in sorted(buckets.items()):
            dim_map.setdefault(group_val, {})[engine] = aggregate_metrics(rows)
        grouped[dimension] = dim_map

    return {"overall": overall, "grouped": grouped}


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.2f}%"


def _fmt_num(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def _choose_winner(metrics_by_engine: dict[str, dict[str, Any]]) -> str | None:
    candidates = [
        (eng, m)
        for eng, m in metrics_by_engine.items()
        if m.get("pages_scored", 0) > 0 and m.get("nfc_cer") is not None
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            item[1]["nfc_cer"],
            item[1]["grapheme_er"] if item[1]["grapheme_er"] is not None else 999.0,
            item[1]["wer"] if item[1]["wer"] is not None else 999.0,
            -(item[1]["exact_line_accuracy"] if item[1]["exact_line_accuracy"] is not None else -1.0),
        )
    )
    return candidates[0][0]


def render_markdown_report(
    *,
    dataset_version: str,
    run_id: str,
    run_date: str,
    provenance: dict[str, Any],
    run_metadata: dict[str, Any],
    summary_data: dict[str, Any],
    error_categories: dict[str, dict[str, int]],
    worst_examples: list[dict[str, Any]],
    failed_pages: list[dict[str, Any]],
    render_dpi: int,
    preprocessing_config: str = "none (unmodified 300 DPI RGB render)",
) -> str:
    """Format a Markdown benchmark report following 05-benchmark-methodology.md Section 8."""
    overall = summary_data["overall"]
    grouped = summary_data["grouped"]
    pkgs = provenance.get("packages", {})
    paddle_models = provenance.get("paddle_models", {})
    tess_info = provenance.get("tesseract", {})

    model_ids_str = ", ".join(
        f"{name} ({info.get('inference_pdiparams_sha256', '')[:12]})"
        for name, info in sorted(paddle_models.items())
    ) or "not recorded"

    lines: list[str] = [
        f"# Phase 1 OCR Benchmark Report — {run_id}",
        "",
        "## Environment & Provenance",
        "",
        f"- **Project / dataset version:** `{dataset_version}`",
        f"- **Run ID / date:** `{run_id}` / `{run_date}`",
        f"- **Host OS / CPU / RAM:** `{provenance.get('platform')}` / `{provenance.get('machine')}` ({provenance.get('cpu_count')} cores) / `{provenance.get('memory_gb')} GiB`",
        f"- **Python version:** `{provenance.get('python_version')}`",
        f"- **PaddleOCR / PaddleX / PaddlePaddle:** `{pkgs.get('paddleocr')}` / `{pkgs.get('paddlex')}` / `{pkgs.get('paddlepaddle')}`",
        f"- **Tesseract version:** `{tess_info.get('version_line', 'unavailable')}`",
        f"- **Paddle model IDs (SHA-256 prefix):** `{model_ids_str}`",
        f"- **Tesseract `tel.traineddata` SHA-256:** `{tess_info.get('tel_traineddata_sha256', 'unavailable')}`",
        f"- **Rendering DPI:** `{render_dpi}`",
        f"- **Preprocessing config:** `{preprocessing_config}`",
        "",
        "## Cold Start vs Warm Inference",
        "",
    ]

    for engine, meta in sorted(run_metadata.items()):
        cold_ms = meta.get("cold_start_ms")
        cold_str = f"{cold_ms:.1f} ms" if isinstance(cold_ms, (int, float)) else "N/A (per-invocation CLI)"
        warm_page_ms = meta.get("warmup_elapsed_ms")
        warm_str = f"{warm_page_ms:.1f} ms" if isinstance(warm_page_ms, (int, float)) else "not run"
        lines.append(
            f"- **{engine}**: `model_id={meta.get('model_id')}`, init cold start={cold_str}, warmup page={warm_str}"
        )

    lines.extend(
        [
            "",
            "## Overall Benchmark Results",
            "",
            "| Engine | Scored Pages | CER | NFC CER | WER | Grapheme ER | Exact-line % | Median sec/page | Pages/min |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for engine, m in sorted(overall.items()):
        lines.append(
            f"| `{engine}` | {m['pages_scored']} / {m['pages_total']} | "
            f"{_fmt_pct(m['cer'])} | {_fmt_pct(m['nfc_cer'])} | {_fmt_pct(m['wer'])} | "
            f"{_fmt_pct(m['grapheme_er'])} | {_fmt_pct(m['exact_line_accuracy'])} | "
            f"{_fmt_num(m['median_sec_per_page'])} | {_fmt_num(m['pages_per_minute'], 2)} |"
        )

    for dim_title, dim_key in (
        ("Results by Book", "book_id"),
        ("Results by Page Quality", "page_quality"),
        ("Results by Layout Type", "layout_type"),
        ("Results by Dataset Split", "split"),
    ):
        lines.extend(["", f"## {dim_title}", ""])
        dim_map = grouped.get(dim_key, {})
        if not dim_map:
            lines.append("_No entries._")
            continue
        lines.append("| Group | Engine | Scored Pages | NFC CER | WER | Grapheme ER | Exact-line % | Median sec/page |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for group_val, eng_map in sorted(dim_map.items()):
            for engine, m in sorted(eng_map.items()):
                lines.append(
                    f"| `{group_val}` | `{engine}` | {m['pages_scored']} / {m['pages_total']} | "
                    f"{_fmt_pct(m['nfc_cer'])} | {_fmt_pct(m['wer'])} | "
                    f"{_fmt_pct(m['grapheme_er'])} | {_fmt_pct(m['exact_line_accuracy'])} | "
                    f"{_fmt_num(m['median_sec_per_page'])} |"
                )

    lines.extend(["", "## Failed Pages", ""])
    if not failed_pages:
        lines.append("None (0 failed pages).")
    else:
        for item in failed_pages:
            lines.append(
                f"- `{item.get('engine')}` `{item.get('book_id')}` page {item.get('page_number')}: "
                f"`{item.get('error_type')}` — {item.get('error_message')}"
            )

    lines.extend(["", "## Top Heuristic Error Categories", ""])
    if not error_categories:
        lines.append("_No scored mismatches recorded._")
    else:
        for engine, cats in sorted(error_categories.items()):
            summary = ", ".join(f"`{k}`={v}" for k, v in cats.items())
            lines.append(f"- **{engine}**: {summary}")

    lines.extend(["", "## Representative Error Examples", ""])
    if not worst_examples:
        lines.append("_No mismatched lines to display._")
    else:
        for ex in worst_examples[:6]:
            lines.append(
                f"### `{ex['engine']}` — `{ex['book_id']}` p.{ex['page_number']} "
                f"(quality=`{ex['page_quality']}`, NFC CER={_fmt_pct(ex['nfc_cer'])})"
            )
            for diff in ex["line_diffs"][:3]:
                cues = ", ".join(diff["heuristic_categories"])
                lines.append(f"- Line {diff['line_index']} [{cues}]:")
                lines.append(f"  - Gold: `{diff['reference']}`")
                lines.append(f"  - OCR : `{diff['hypothesis']}`")

    lines.extend(["", "## Recommendation & Decision Notes", ""])
    overall_winner = _choose_winner(overall)
    quality_map = grouped.get("page_quality", {})
    clean_winner = _choose_winner(quality_map.get("clean", {}))
    degraded_winner = _choose_winner(quality_map.get("degraded", {}))
    total_scored = max((m["pages_scored"] for m in overall.values()), default=0)

    if overall_winner:
        lines.append(f"- **Best overall scored configuration on this dataset:** `{overall_winner}`.")
    else:
        lines.append("- **Best overall scored configuration:** Insufficient gold-annotated pages.")

    if clean_winner or degraded_winner:
        lines.append(
            f"- **Clean vs degraded breakdown:** clean winner=`{clean_winner or 'N/A'}`, "
            f"degraded winner=`{degraded_winner or 'N/A'}`."
        )

    lines.extend(
        [
            f"- **Sample size note:** {total_scored} gold-annotated page(s) scored in this run. "
            "Do not finalize production engine selection or Phase 2 acceptance thresholds until 20–30 real printed pages across at least three Telugu books (including a held-out test book) are evaluated.",
            "",
            "## Known Limitations",
            "",
            "- Unicode extended grapheme clusters (`\\X`) are a reproducible akshara proxy, not a full linguistic Telugu akshara parser.",
            "- Whitespace-delimited WER does not reflect Telugu compound words or hyphenated line splits identically across layouts.",
            "- OCR confidence scales differ between PaddleOCR (0–1) and Tesseract (0–100) and are not calibrated probabilities.",
            "- Heuristic error categories above are line-diff cues and require human inspection for final error taxonomy attribution.",
            "",
        ]
    )
    return "\n".join(lines)


def write_benchmark_outputs(
    *,
    output_dir: Path,
    dataset_version: str,
    run_id: str,
    run_date: str,
    provenance: dict[str, Any],
    run_metadata: dict[str, Any],
    page_rows: list[dict[str, Any]],
    warm_latencies_by_engine: dict[str, list[float]] | None,
    failed_pages: list[dict[str, Any]],
    render_dpi: int,
) -> dict[str, Path]:
    """Write benchmark CSVs, JSON, provenance manifest, and Markdown report atomically."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_data = compute_grouped_summaries(page_rows, warm_latencies_by_engine=warm_latencies_by_engine)
    error_categories, worst_examples = extract_error_examples(page_rows)

    public_page_rows = [
        {k: v for k, v in row.items() if not k.startswith("_")}
        for row in page_rows
    ]

    pages_csv = output_dir / "benchmark_pages.csv"
    atomic_write_text(pages_csv, pd.DataFrame(public_page_rows).to_csv(index=False))

    summary_rows: list[dict[str, Any]] = []
    for engine, m in sorted(summary_data["overall"].items()):
        summary_rows.append({"dimension": "overall", "group": "all", "engine": engine, **{k: v for k, v in m.items() if k != "totals"}})
    for dim_key, dim_map in summary_data["grouped"].items():
        for group_val, eng_map in sorted(dim_map.items()):
            for engine, m in sorted(eng_map.items()):
                summary_rows.append({"dimension": dim_key, "group": group_val, "engine": engine, **{k: v for k, v in m.items() if k != "totals"}})

    summary_csv = output_dir / "benchmark_summary.csv"
    atomic_write_text(summary_csv, pd.DataFrame(summary_rows).to_csv(index=False))

    results_json = output_dir / "benchmark_results.json"
    atomic_write_json(
        results_json,
        {
            "dataset_version": dataset_version,
            "run_id": run_id,
            "run_date": run_date,
            "provenance": provenance,
            "run_metadata": run_metadata,
            "summary": summary_data,
            "error_categories": error_categories,
            "worst_examples": worst_examples,
            "failed_pages": failed_pages,
            "pages": public_page_rows,
        },
    )

    provenance_json = output_dir / "provenance.json"
    atomic_write_json(provenance_json, provenance)

    report_md = output_dir / "benchmark_report.md"
    markdown = render_markdown_report(
        dataset_version=dataset_version,
        run_id=run_id,
        run_date=run_date,
        provenance=provenance,
        run_metadata=run_metadata,
        summary_data=summary_data,
        error_categories=error_categories,
        worst_examples=worst_examples,
        failed_pages=failed_pages,
        render_dpi=render_dpi,
    )
    atomic_write_text(report_md, markdown)

    return {
        "pages_csv": pages_csv,
        "summary_csv": summary_csv,
        "results_json": results_json,
        "provenance_json": provenance_json,
        "report_md": report_md,
    }
