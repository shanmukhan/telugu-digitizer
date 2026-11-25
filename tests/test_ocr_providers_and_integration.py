"""Unit tests for OCR provider guards/TSV parsing and end-to-end integration test."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from scripts.benchmark import main as benchmark_main
from scripts.render_pdf import main as render_main
from scripts.run_ocr import main as run_ocr_main
from src.common.manifest import load_manifest, save_manifest
from src.ocr.paddle_provider import PaddleOCRProvider
from src.ocr.tesseract_provider import TesseractOCRProvider, parse_tesseract_tsv


def _system_telugu_font() -> str:
    candidates = [
        "/System/Library/Fonts/KohinoorTelugu.ttc",
        "/System/Library/Fonts/Supplemental/Telugu MN.ttc",
        "/System/Library/Fonts/Supplemental/Telugu Sangam MN.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    pytest.skip("No Telugu system font available for fixture rendering.")
    return ""


def test_paddle_provider_rejects_non_telugu_or_wrong_version(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError):
        PaddleOCRProvider(lang="en", ocr_version="PP-OCRv5")
    with pytest.raises(ValueError):
        PaddleOCRProvider(lang="te", ocr_version="PP-OCRv6")

    monkeypatch.setattr("src.ocr.paddle_provider.platform.system", lambda: "Linux")
    monkeypatch.setattr("src.ocr.paddle_provider.platform.machine", lambda: "aarch64")
    arm_provider = PaddleOCRProvider(lang="te", ocr_version="PP-OCRv5")
    assert arm_provider.cpu_threads == 1
    assert arm_provider.text_det_limit_type == "max"
    assert arm_provider.text_det_limit_side_len == 1280


def test_tesseract_tsv_parser_handles_quotes_and_missing_confidence() -> None:
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            '5\t1\t1\t1\t1\t1\t10\t20\t50\t30\t92.5\t"తెలుగు"',
            "5\t1\t1\t1\t1\t2\t70\t22\t60\t28\t87.5\tపుస్తకం",
            "5\t1\t1\t1\t2\t1\t10\t70\t80\t30\t-1\tవరుస",
        ]
    )
    blocks = parse_tesseract_tsv(tsv)
    assert len(blocks) == 2
    assert blocks[0]["text"] == '"తెలుగు" పుస్తకం'
    assert blocks[0]["confidence"] == 90.0
    assert blocks[0]["bbox"] == [10, 20, 130, 50]
    assert blocks[1]["text"] == "వరుస"
    assert blocks[1]["confidence"] is None


def test_tesseract_provider_guards_and_missing_traineddata(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        TesseractOCRProvider(tessdata_dir=tmp_path, lang="eng")
    with pytest.raises(ValueError):
        TesseractOCRProvider(tessdata_dir=tmp_path, lang="tel", oem=0)
    with pytest.raises(FileNotFoundError):
        TesseractOCRProvider(tessdata_dir=tmp_path, lang="tel", oem=1)


def test_end_to_end_phase1_pipeline_with_fixture_and_failure_isolation(tmp_path: Path) -> None:
    """Exercise PDF render -> Paddle + Tesseract OCR -> fault isolation -> benchmark report."""
    font_path = _system_telugu_font()
    tessdata_dir = Path("models/tesseract/tessdata").resolve()
    if not (tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("models/tesseract/tessdata/tel.traineddata not present.")

    # Compact 300-DPI scanned page (3.0" x 1.1" -> 900x330 px) plus 1 digital_text page.
    img = Image.new("RGB", (900, 330), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 38)
    gold_lines = [
        "తెలుగు పుస్తక పరీక్ష",
        "భాష మరియు లిపి 2026.",
    ]
    draw.text((40, 40), gold_lines[0], fill="black", font=font)
    draw.text((40, 160), gold_lines[1], fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    pdf_path = tmp_path / "fixture.pdf"
    doc = pymupdf.open()
    p1 = doc.new_page(width=216.0, height=79.2)
    p1.insert_image(p1.rect, stream=buf.getvalue())
    p2 = doc.new_page(width=400.0, height=200.0)
    p2.insert_text((30, 60), "Digital text page should not be scored as OCR.", fontsize=14)
    doc.save(pdf_path)
    doc.close()

    gold_file = tmp_path / "gold" / "page-0001.txt"
    gold_file.parent.mkdir(parents=True, exist_ok=True)
    gold_file.write_text("\n".join(gold_lines) + "\n", encoding="utf-8")

    pages_dir = tmp_path / "data" / "pages"
    manifest_path = tmp_path / "data" / "manifests" / "fixture.json"
    artifacts_dir = tmp_path / "artifacts"

    rc_render = render_main(
        [
            "--pdf",
            str(pdf_path),
            "--book-id",
            "fixture_int",
            "--output-dir",
            str(pages_dir),
            "--manifest",
            str(manifest_path),
            "--dpi",
            "300",
            "--split",
            "dev",
            "--page-quality",
            "clean",
            "--layout-type",
            "single_column",
            "--workspace-root",
            str(tmp_path),
        ]
    )
    assert rc_render == 0

    manifest = load_manifest(manifest_path)
    assert len(manifest.pages) == 2
    assert manifest.pages[0].page_kind == "scanned_image"
    assert manifest.pages[0].width_px == 900
    assert manifest.pages[1].page_kind == "digital_text"
    manifest.pages[0].gold_path = str(gold_file.relative_to(tmp_path))

    # Inject a missing-image rendered entry to prove per-page OCR failure does not abort the batch.
    broken_entry = manifest.pages[0].__class__.from_dict(manifest.pages[0].to_dict())
    broken_entry.page_number = 99
    broken_entry.image_path = "data/pages/fixture_int/does-not-exist.png"
    broken_entry.gold_path = None
    manifest.pages.append(broken_entry)
    save_manifest(manifest, manifest_path)

    rc_ocr = run_ocr_main(
        [
            "--manifest",
            str(manifest_path),
            "--engines",
            "paddle",
            "tesseract",
            "--run-id",
            "int-run",
            "--artifacts-dir",
            str(artifacts_dir),
            "--tessdata-dir",
            str(tessdata_dir),
            "--workspace-root",
            str(tmp_path),
        ]
    )
    # Expect rc=1 because injected page 99 failed, while page 1 completed cleanly.
    assert rc_ocr == 1

    run_manifest_path = artifacts_dir / "run-int-run.manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    for eng in ("paddle", "tesseract"):
        assert run_manifest["engines"][eng]["expected"] == 2
        assert run_manifest["engines"][eng]["completed"] == 1
        assert run_manifest["engines"][eng]["failed"] == 1

    paddle_json = json.loads(
        (artifacts_dir / "paddle" / "int-run" / "fixture_int" / "page-0001.json").read_text(
            encoding="utf-8"
        )
    )
    assert paddle_json["config"]["lang"] == "te"
    assert paddle_json["config"]["ocr_version"] == "PP-OCRv5"
    assert paddle_json["config"]["rec_model_name"] == "te_PP-OCRv5_mobile_rec"
    assert (tmp_path / paddle_json["raw_result_path"]).is_file()

    tess_json = json.loads(
        (artifacts_dir / "tesseract" / "int-run" / "fixture_int" / "page-0001.json").read_text(
            encoding="utf-8"
        )
    )
    assert tess_json["config"]["lang"] == "tel"
    assert tess_json["config"]["oem"] == 1
    assert (tmp_path / tess_json["raw_result_path"]).is_file()

    rc_bench = benchmark_main(
        [
            "--manifest",
            str(manifest_path),
            "--run-id",
            "int-run",
            "--run-manifest",
            str(run_manifest_path),
            "--artifacts-dir",
            str(artifacts_dir),
            "--tessdata-dir",
            str(tessdata_dir),
            "--workspace-root",
            str(tmp_path),
        ]
    )
    # Returns 1 when failed_pages is non-empty so CI/CLI sees partial failures while writing full report.
    assert rc_bench == 1

    bench_dir = artifacts_dir / "benchmark" / "int-run"
    results = json.loads((bench_dir / "benchmark_results.json").read_text(encoding="utf-8"))
    assert results["summary"]["overall"]["paddle"]["pages_scored"] == 1
    assert results["summary"]["overall"]["tesseract"]["pages_scored"] == 1
    assert len(results["failed_pages"]) == 2
    assert (bench_dir / "benchmark_report.md").is_file()
    assert (bench_dir / "benchmark_pages.csv").is_file()
    assert (bench_dir / "benchmark_summary.csv").is_file()
    assert (bench_dir / "provenance.json").is_file()


def test_cli_scripts_run_directly_without_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for script in ("scripts/render_pdf.py", "scripts/run_ocr.py", "scripts/benchmark.py"):
        proc = subprocess.run(
            [sys.executable, str(repo_root / script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"{script} --help failed: {proc.stderr}"
