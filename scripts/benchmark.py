#!/usr/bin/env python3
"""Phase 1 benchmark CLI: run/evaluate PaddleOCR and Tesseract against gold transcriptions."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.io import sanitize_id, validate_within_workspace
from src.common.logging_utils import configure_logging, log_event
from src.common.manifest import DatasetManifest, collect_provenance, load_manifest
from src.evaluation.metrics import evaluate_page_text
from src.evaluation.report import write_benchmark_outputs
from src.ocr.paddle_provider import PaddleOCRProvider
from src.ocr.runner import run_ocr_on_manifest
from src.ocr.tesseract_provider import TesseractOCRProvider


def _load_gold_text(gold_path_str: str | None, workspace_root: Path) -> str | None:
    if not gold_path_str:
        return None
    gold_path = Path(gold_path_str)
    if not gold_path.is_absolute():
        gold_path = workspace_root / gold_path
    if not gold_path.is_file():
        raise FileNotFoundError(f"Configured gold transcription file missing: {gold_path}")
    return gold_path.read_text(encoding="utf-8")


def _measure_extra_repeats(
    *,
    manifest: DatasetManifest,
    engines: list[str],
    tessdata_dir: Path,
    tesseract_psm: int,
    paddle_device: str,
    tesseract_cmd: str | None,
    extra_repeats: int,
    workspace_root: Path,
) -> dict[str, list[float]]:
    """Measure additional steady-state timing passes when repeats > 1."""
    warm_latencies: dict[str, list[float]] = {e: [] for e in engines}
    if extra_repeats <= 0:
        return warm_latencies
    target_pages = [
        p for p in manifest.pages if p.status == "rendered" and p.page_kind != "digital_text"
    ]
    if not target_pages:
        return warm_latencies

    for engine_key in engines:
        if engine_key == "paddle":
            provider = PaddleOCRProvider(device=paddle_device)
        else:
            provider = TesseractOCRProvider(
                tessdata_dir=tessdata_dir,
                psm=tesseract_psm,
                tesseract_cmd=tesseract_cmd,
            )
        for _ in range(extra_repeats):
            for page in target_pages:
                img_path = Path(page.image_path)
                if not img_path.is_absolute():
                    img_path = workspace_root / img_path
                if img_path.is_file():
                    res = provider.recognize(img_path)
                    warm_latencies[engine_key].append(float(res["elapsed_ms"]))

    return warm_latencies


def evaluate_run_manifest(
    *,
    dataset_manifest: DatasetManifest,
    run_manifest: dict[str, Any],
    workspace_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Score saved OCR outputs against gold files referenced in the dataset manifest."""
    page_lookup = {(p.book_id, p.page_number): p for p in dataset_manifest.pages}
    page_rows: list[dict[str, Any]] = []
    failed_pages: list[dict[str, Any]] = []
    run_metadata: dict[str, Any] = {}

    for engine_key, engine_data in run_manifest.get("engines", {}).items():
        run_metadata[engine_key] = dict(engine_data.get("metadata", {}))
        for page_rec in engine_data.get("pages", []):
            book_id = str(page_rec["book_id"])
            page_number = int(page_rec["page_number"])
            manifest_entry = page_lookup.get((book_id, page_number))
            page_quality = manifest_entry.page_quality if manifest_entry else "unspecified"
            layout_type = manifest_entry.layout_type if manifest_entry else "unspecified"
            split = manifest_entry.split if manifest_entry else "unspecified"
            page_kind = manifest_entry.page_kind if manifest_entry else "scanned_image"

            if page_rec.get("status") != "completed":
                failed_item = {
                    "engine": engine_key,
                    "book_id": book_id,
                    "page_number": page_number,
                    "status": "failed",
                    "error_type": page_rec.get("error_type"),
                    "error_message": page_rec.get("error_message"),
                }
                failed_pages.append(failed_item)
                page_rows.append(
                    {
                        "engine": engine_key,
                        "book_id": book_id,
                        "page_number": page_number,
                        "split": split,
                        "page_quality": page_quality,
                        "layout_type": layout_type,
                        "page_kind": page_kind,
                        "status": "failed",
                        "scored": False,
                        "elapsed_ms": None,
                    }
                )
                continue

            # Never include direct digital text extraction in OCR benchmark accuracy scores.
            if page_kind == "digital_text":
                continue

            out_json_path = Path(page_rec["output_json"])
            if not out_json_path.is_absolute():
                out_json_path = workspace_root / out_json_path
            ocr_record = json.loads(out_json_path.read_text(encoding="utf-8"))
            hyp_raw = str(ocr_record.get("text", ""))

            gold_raw = _load_gold_text(
                manifest_entry.gold_path if manifest_entry else None,
                workspace_root,
            )

            row: dict[str, Any] = {
                "engine": engine_key,
                "book_id": book_id,
                "page_number": page_number,
                "split": split,
                "page_quality": page_quality,
                "layout_type": layout_type,
                "page_kind": page_kind,
                "status": "completed",
                "scored": gold_raw is not None,
                "elapsed_ms": ocr_record.get("elapsed_ms"),
                "block_count": len(ocr_record.get("blocks", [])),
            }
            if gold_raw is not None:
                metrics = evaluate_page_text(gold_raw, hyp_raw)
                row.update(metrics.to_dict())
                row["_reference_raw"] = gold_raw
                row["_hypothesis_raw"] = hyp_raw
            page_rows.append(row)

    return page_rows, failed_pages, run_metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or evaluate Phase 1 Telugu OCR benchmark and emit CSV/JSON/Markdown reports."
    )
    parser.add_argument("--manifest", type=Path, required=True, help="Dataset page manifest JSON.")
    parser.add_argument("--run-id", type=str, default="benchmark-v1", help="Run identifier.")
    parser.add_argument(
        "--run-manifest",
        type=Path,
        default=None,
        help="Existing OCR run manifest JSON to score without rerunning OCR.",
    )
    parser.add_argument(
        "--engines",
        nargs="+",
        default=["paddle", "tesseract"],
        choices=["paddle", "tesseract"],
    )
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--output-dir", type=Path, default=None, help="Report output directory.")
    parser.add_argument("--tessdata-dir", type=Path, default=Path("models/tesseract/tessdata"))
    parser.add_argument("--tesseract-psm", type=int, default=6)
    parser.add_argument("--tesseract-cmd", type=str, default=None)
    parser.add_argument("--paddle-device", type=str, default="cpu")
    parser.add_argument("--warmup", action="store_true", help="Run 1 warm-up page before timing.")
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Timing repeats (when >1 or --warmup, collects median warm latency).",
    )
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = configure_logging(args.log_level)
    workspace_root = args.workspace_root.resolve()
    safe_run_id = sanitize_id(args.run_id)
    dataset_manifest = load_manifest(args.manifest)

    if args.run_manifest is not None:
        run_manifest = json.loads(args.run_manifest.read_text(encoding="utf-8"))
        warm_latencies_by_engine: dict[str, list[float]] | None = None
    else:
        run_manifest = run_ocr_on_manifest(
            manifest=dataset_manifest,
            engines=list(args.engines),
            artifacts_dir=args.artifacts_dir,
            run_id=safe_run_id,
            workspace_root=workspace_root,
            tessdata_dir=args.tessdata_dir,
            tesseract_psm=args.tesseract_psm,
            paddle_device=args.paddle_device,
            tesseract_cmd=args.tesseract_cmd,
            include_digital_text_pages=False,
            warmup=args.warmup,
            logger=logger,
        )
        warm_latencies_by_engine = None
        if args.repeats > 1:
            extra = _measure_extra_repeats(
                manifest=dataset_manifest,
                engines=list(args.engines),
                tessdata_dir=args.tessdata_dir,
                tesseract_psm=args.tesseract_psm,
                paddle_device=args.paddle_device,
                tesseract_cmd=args.tesseract_cmd,
                extra_repeats=args.repeats - 1,
                workspace_root=workspace_root,
            )
            warm_latencies_by_engine = {
                eng: list(run_manifest["engines"].get(eng, {}).get("elapsed_ms_values", [])) + extra.get(eng, [])
                for eng in args.engines
            }

    page_rows, failed_pages, run_metadata = evaluate_run_manifest(
        dataset_manifest=dataset_manifest,
        run_manifest=run_manifest,
        workspace_root=workspace_root,
    )

    provenance = collect_provenance(
        tessdata_dir=args.tessdata_dir,
        tesseract_cmd=args.tesseract_cmd,
    )
    render_dpi = dataset_manifest.pages[0].render_dpi if dataset_manifest.pages else 300
    report_dir = validate_within_workspace(
        args.output_dir or (args.artifacts_dir / "benchmark" / safe_run_id),
        workspace_root,
    )
    written = write_benchmark_outputs(
        output_dir=report_dir,
        dataset_version=dataset_manifest.dataset_version,
        run_id=safe_run_id,
        run_date=datetime.now(timezone.utc).isoformat(),
        provenance=provenance,
        run_metadata=run_metadata,
        page_rows=page_rows,
        warm_latencies_by_engine=warm_latencies_by_engine,
        failed_pages=failed_pages,
        render_dpi=render_dpi,
    )
    log_event(
        logger,
        logging.INFO,
        "Benchmark report written",
        run_id=safe_run_id,
        report_md=str(written["report_md"]),
        results_json=str(written["results_json"]),
        failed_count=len(failed_pages),
    )
    return 1 if failed_pages else 0


if __name__ == "__main__":
    sys.exit(main())
