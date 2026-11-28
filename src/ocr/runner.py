"""Sequential batch OCR runner with per-page error isolation and atomic outputs."""

from __future__ import annotations

import logging
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.io import (
    atomic_write_json,
    atomic_write_text,
    sanitize_id,
    sha256_file,
    validate_within_workspace,
)
from src.common.logging_utils import log_event
from src.common.manifest import DatasetManifest
from src.ocr.base import OCRProvider, build_page_ocr_record
from src.ocr.paddle_provider import PaddleOCRProvider
from src.ocr.tesseract_provider import TesseractOCRProvider


def save_raw_payload(
    engine: str,
    raw_dir: Path,
    page_stem: str,
    raw_payload: dict[str, Any],
    workspace_root: Path,
) -> Path:
    """Persist untouched native engine payloads atomically."""
    if engine == "paddleocr":
        raw_path = validate_within_workspace(raw_dir / f"{page_stem}.raw.json", workspace_root)
        return atomic_write_json(raw_path, raw_payload)
    if engine == "tesseract":
        raw_txt_path = validate_within_workspace(raw_dir / f"{page_stem}.raw.txt", workspace_root)
        raw_tsv_path = validate_within_workspace(raw_dir / f"{page_stem}.raw.tsv", workspace_root)
        atomic_write_text(raw_txt_path, str(raw_payload.get("txt", "")))
        atomic_write_text(raw_tsv_path, str(raw_payload.get("tsv", "")))
        return raw_tsv_path
    raw_path = validate_within_workspace(raw_dir / f"{page_stem}.raw.json", workspace_root)
    return atomic_write_json(raw_path, raw_payload)


def run_ocr_on_manifest(
    *,
    manifest: DatasetManifest,
    engines: list[str],
    artifacts_dir: Path,
    run_id: str,
    workspace_root: Path,
    tessdata_dir: Path,
    tesseract_psm: int = 6,
    paddle_device: str = "cpu",
    tesseract_cmd: str | None = None,
    include_digital_text_pages: bool = False,
    warmup: bool = False,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Run selected OCR engines sequentially across manifest pages with per-page fault tolerance."""
    safe_run_id = sanitize_id(run_id)
    root = workspace_root.resolve()
    log = logger or logging.getLogger("telugu_digitizer.ocr")

    providers: dict[str, OCRProvider] = {}
    init_times_ms: dict[str, float] = {}
    for engine_key in engines:
        t_init = time.perf_counter()
        if engine_key == "paddle":
            providers["paddle"] = PaddleOCRProvider(device=paddle_device)
        elif engine_key == "tesseract":
            providers["tesseract"] = TesseractOCRProvider(
                tessdata_dir=tessdata_dir,
                psm=tesseract_psm,
                tesseract_cmd=tesseract_cmd,
            )
        else:
            raise ValueError(f"Unsupported engine {engine_key!r}. Choose 'paddle' and/or 'tesseract'.")
        init_times_ms[engine_key] = round((time.perf_counter() - t_init) * 1000.0, 2)

    run_summary: dict[str, Any] = {
        "run_id": safe_run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": manifest.dataset_version,
        "engines": {},
        "pages_expected": 0,
    }

    target_pages = [
        p
        for p in manifest.pages
        if p.status == "rendered" and (include_digital_text_pages or p.page_kind != "digital_text")
    ]
    skipped_pages = [p for p in manifest.pages if p not in target_pages]
    run_summary["pages_expected"] = len(target_pages)
    run_summary["pages_skipped"] = [
        {
            "book_id": p.book_id,
            "page_number": p.page_number,
            "reason": f"status={p.status},page_kind={p.page_kind}",
        }
        for p in skipped_pages
    ]

    for engine_key, provider in providers.items():
        engine_dir_name = "paddle" if engine_key == "paddle" else "tesseract"
        completed = 0
        failed = 0
        page_records: list[dict[str, Any]] = []
        latencies_ms: list[float] = []
        warmup_elapsed_ms: float | None = None
        cold_start_ms: float | None = None

        if warmup and target_pages:
            first_img = Path(target_pages[0].image_path)
            if not first_img.is_absolute():
                first_img = root / first_img
            if first_img.is_file():
                try:
                    warm_res = provider.recognize(first_img)
                    warmup_elapsed_ms = float(warm_res["elapsed_ms"])
                    if warm_res.get("cold_start_ms") is not None:
                        cold_start_ms = float(warm_res["cold_start_ms"])
                except Exception as exc:
                    log_event(
                        log,
                        logging.WARNING,
                        "Warmup page failed; continuing benchmark",
                        engine=engine_key,
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )

        for page in target_pages:
            img_path = Path(page.image_path)
            if not img_path.is_absolute():
                img_path = root / img_path

            book_out_dir = validate_within_workspace(
                artifacts_dir / engine_dir_name / safe_run_id / page.book_id,
                root,
            )
            page_stem = f"page-{page.page_number:04d}"
            raw_dir = book_out_dir / "raw"

            try:
                image_sha = page.image_sha256 or sha256_file(img_path)
                result = provider.recognize(img_path)
                raw_path = save_raw_payload(
                    provider.engine_name,
                    raw_dir,
                    page_stem,
                    result["raw_payload"],
                    root,
                )
                try:
                    raw_rel = str(raw_path.resolve().relative_to(root))
                except ValueError:
                    raw_rel = str(raw_path)

                structured = build_page_ocr_record(
                    book_id=page.book_id,
                    page_number=page.page_number,
                    source_pdf_sha256=page.source_pdf_sha256,
                    render_dpi=page.render_dpi,
                    image_path=page.image_path,
                    image_sha256=image_sha,
                    recognition_result=result,
                    raw_result_path=raw_rel,
                )
                json_out = validate_within_workspace(book_out_dir / f"{page_stem}.json", root)
                txt_out = validate_within_workspace(book_out_dir / f"{page_stem}.txt", root)
                atomic_write_json(json_out, structured)
                atomic_write_text(txt_out, structured["text"])

                completed += 1
                latencies_ms.append(float(result["elapsed_ms"]))
                page_records.append(
                    {
                        "book_id": page.book_id,
                        "page_number": page.page_number,
                        "status": "completed",
                        "retry_status": "none",
                        "elapsed_ms": result["elapsed_ms"],
                        "block_count": len(result["blocks"]),
                        "output_json": str(json_out.relative_to(root)),
                        "output_txt": str(txt_out.relative_to(root)),
                    }
                )
                log_event(
                    log,
                    logging.INFO,
                    "OCR page completed",
                    engine=engine_key,
                    book_id=page.book_id,
                    page_number=page.page_number,
                    elapsed_ms=result["elapsed_ms"],
                    block_count=len(result["blocks"]),
                )
            except Exception as exc:
                failed += 1
                err_record = {
                    "book_id": page.book_id,
                    "page_number": page.page_number,
                    "status": "failed",
                    "retry_status": "pending_retry",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                }
                page_records.append(err_record)
                err_json = validate_within_workspace(book_out_dir / f"{page_stem}.error.json", root)
                atomic_write_json(err_json, err_record)
                log_event(
                    log,
                    logging.ERROR,
                    "OCR page failed",
                    engine=engine_key,
                    book_id=page.book_id,
                    page_number=page.page_number,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )

        engine_meta = provider.provider_metadata()
        if cold_start_ms is not None and engine_meta.get("cold_start_ms") is None:
            engine_meta["cold_start_ms"] = cold_start_ms
        if engine_meta.get("model_load_ms") is None:
            engine_meta["model_load_ms"] = (
                cold_start_ms if cold_start_ms is not None else init_times_ms.get(engine_key)
            )
        if warmup_elapsed_ms is not None:
            engine_meta["warmup_elapsed_ms"] = warmup_elapsed_ms
        ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_rss_mb = (
            float(ru_maxrss) / (1024.0 * 1024.0)
            if sys.platform == "darwin"
            else float(ru_maxrss) / 1024.0
        )
        engine_meta["peak_rss_mb"] = round(peak_rss_mb, 2)

        run_summary["engines"][engine_key] = {
            "metadata": engine_meta,
            "expected": len(target_pages),
            "completed": completed,
            "failed": failed,
            "elapsed_ms_values": latencies_ms,
            "pages": page_records,
        }

    run_summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    run_manifest_path = validate_within_workspace(
        artifacts_dir / f"run-{safe_run_id}.manifest.json",
        root,
    )
    atomic_write_json(run_manifest_path, run_summary)
    run_summary["run_manifest_path"] = str(run_manifest_path.relative_to(root))
    return run_summary
