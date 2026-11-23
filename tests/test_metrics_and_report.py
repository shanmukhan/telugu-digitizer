"""Unit tests for Unicode NFC normalization, Telugu grapheme metrics, and reporting."""

from __future__ import annotations

from pathlib import Path

from src.evaluation.metrics import (
    aggregate_metrics,
    evaluate_page_text,
    grapheme_clusters,
    normalize_nfc,
)
from src.evaluation.report import (
    classify_line_error_cues,
    compute_grouped_summaries,
    write_benchmark_outputs,
)


def test_telugu_nfc_normalization_vs_raw_codepoints() -> None:
    # U+0C48 (ై) canonically decomposes to U+0C46 (ె) + U+0C56 (ౖ).
    decomposed = "క\u0c46\u0c56లాసం"
    composed = "క\u0c48లాసం"

    assert decomposed != composed
    assert normalize_nfc(decomposed) == composed

    metrics = evaluate_page_text(composed, decomposed)
    # Raw CER reflects the 2 code-point differences (1 replace + 1 insert), while NFC CER is 0.
    assert metrics.raw_edits == 2
    assert metrics.raw_cer is not None and metrics.raw_cer > 0.0
    assert metrics.nfc_edits == 0
    assert metrics.nfc_cer == 0.0
    assert metrics.grapheme_edits == 0
    assert metrics.grapheme_er == 0.0
    assert metrics.exact_line_accuracy == 1.0


def test_telugu_grapheme_clusters_and_wer() -> None:
    clusters = grapheme_clusters("విద్యార్థులు")
    assert clusters == ["వి", "ద్యా", "ర్థు", "లు"]

    ref = "తెలుగు పుస్తకం 2026.\nరెండవ వరుస."
    hyp = "తెలుగు పుస్తకం 2026.\nరెండవ విరుస."
    m = evaluate_page_text(ref, hyp)

    assert m.ref_words == 5
    assert m.word_edits == 1
    assert abs((m.wer or 0.0) - 0.2) < 1e-9
    assert m.exact_line_matches == 1
    assert m.ref_lines == 2
    assert abs((m.exact_line_accuracy or 0.0) - 0.5) < 1e-9
    # One grapheme cluster changed ('వ' -> 'వి' within one akshara cluster).
    assert m.grapheme_edits == 1


def test_empty_reference_handling() -> None:
    both_empty = evaluate_page_text("", "")
    assert both_empty.raw_cer == 0.0
    assert both_empty.nfc_cer == 0.0
    assert both_empty.exact_line_accuracy == 1.0

    ref_empty = evaluate_page_text("", "అ")
    assert ref_empty.raw_cer is None
    assert ref_empty.raw_edits == 1


def test_grouped_aggregation_and_report_outputs(tmp_path: Path) -> None:
    m1 = evaluate_page_text("అఆ\nఇఈ", "అఆ\nఇఈ")
    m2 = evaluate_page_text("పుస్తకం", "పస్తకం")

    rows = [
        {
            "engine": "paddle",
            "book_id": "book_a",
            "page_number": 1,
            "split": "dev",
            "page_quality": "clean",
            "layout_type": "single_column",
            "page_kind": "scanned_image",
            "status": "completed",
            "scored": True,
            "elapsed_ms": 1200.0,
            "_reference_raw": "అఆ\nఇఈ",
            "_hypothesis_raw": "అఆ\nఇఈ",
            **m1.to_dict(),
        },
        {
            "engine": "tesseract",
            "book_id": "book_b",
            "page_number": 2,
            "split": "val",
            "page_quality": "degraded",
            "layout_type": "two_column",
            "page_kind": "scanned_image",
            "status": "completed",
            "scored": True,
            "elapsed_ms": 500.0,
            "_reference_raw": "పుస్తకం",
            "_hypothesis_raw": "పస్తకం",
            **m2.to_dict(),
        },
    ]

    agg = aggregate_metrics([rows[0]])
    assert agg["nfc_cer"] == 0.0
    assert agg["median_sec_per_page"] == 1.2

    summary = compute_grouped_summaries(rows)
    assert "paddle" in summary["overall"]
    assert "clean" in summary["grouped"]["page_quality"]

    cues = classify_line_error_cues("పుస్తకం 10.", "పస్తకం 10.")
    assert "vowel_sign" in cues

    written = write_benchmark_outputs(
        output_dir=tmp_path / "bench",
        dataset_version="test-v1",
        run_id="unit-run",
        run_date="2026-11-23T00:00:00Z",
        provenance={"python_version": "3.11.14", "packages": {}, "tesseract": {}, "paddle_models": {}},
        run_metadata={"paddle": {"model_id": "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec"}},
        page_rows=rows,
        warm_latencies_by_engine=None,
        failed_pages=[],
        render_dpi=300,
    )
    for key in ("pages_csv", "summary_csv", "results_json", "provenance_json", "report_md"):
        assert written[key].is_file()
    report_text = written["report_md"].read_text(encoding="utf-8")
    assert "Phase 1 OCR Benchmark Report" in report_text
    assert "paddle" in report_text
    assert "tesseract" in report_text
