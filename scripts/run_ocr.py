#!/usr/bin/env python3
"""CLI runner to execute PaddleOCR PP-OCRv5 Telugu and/or Tesseract on rendered pages."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.common.io import sanitize_id, sha256_file
from src.common.logging_utils import configure_logging, log_event
from src.common.manifest import DatasetManifest, PageManifestEntry, load_manifest
from src.ocr.runner import run_ocr_on_manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PaddleOCR Telugu PP-OCRv5 and/or Tesseract Telugu on a page manifest or single PNG."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--manifest", type=Path, help="Path to page manifest JSON.")
    source.add_argument("--image", type=Path, help="Single PNG image path (vertical slice convenience).")
    parser.add_argument("--book-id", type=str, default="sample", help="Book ID when using --image.")
    parser.add_argument("--page-number", type=int, default=1, help="1-based page number when using --image.")
    parser.add_argument("--render-dpi", type=int, default=300, help="DPI metadata when using --image.")
    parser.add_argument(
        "--engines",
        nargs="+",
        default=["paddle", "tesseract"],
        choices=["paddle", "tesseract"],
        help="OCR engines to execute sequentially on identical images.",
    )
    parser.add_argument("--run-id", type=str, default="latest", help="Identifier for this OCR run.")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--tessdata-dir",
        type=Path,
        default=Path("models/tesseract/tessdata"),
        help="Directory containing tel.traineddata.",
    )
    parser.add_argument("--tesseract-psm", type=int, default=6, help="Tesseract --psm value (default: 6).")
    parser.add_argument("--tesseract-cmd", type=str, default=None, help="Optional explicit tesseract binary.")
    parser.add_argument("--paddle-device", type=str, default="cpu")
    parser.add_argument(
        "--include-digital-text-pages",
        action="store_true",
        help="Include digital_text pages (excluded from scanned OCR path by default).",
    )
    parser.add_argument(
        "--warmup",
        action="store_true",
        help="Run 1 warm-up page before recording per-page inference times.",
    )
    parser.add_argument("--workspace-root", type=Path, default=Path.cwd())
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = configure_logging(args.log_level)
    workspace_root = args.workspace_root.resolve()

    if args.manifest is not None:
        manifest = load_manifest(args.manifest)
    else:
        img_path = args.image
        if not img_path.is_file():
            raise FileNotFoundError(f"Input image not found: {img_path}")
        manifest = DatasetManifest(
            dataset_version="single-image",
            pages=[
                PageManifestEntry(
                    book_id=sanitize_id(args.book_id),
                    page_number=args.page_number,
                    pdf_page_index=max(args.page_number - 1, 0),
                    source_pdf_path="",
                    source_pdf_sha256="",
                    image_path=str(img_path),
                    image_sha256=sha256_file(img_path),
                    render_dpi=args.render_dpi,
                    page_kind="scanned_image",
                    page_width_pt=0.0,
                    page_height_pt=0.0,
                    width_px=None,
                    height_px=None,
                    status="rendered",
                )
            ],
        )

    summary = run_ocr_on_manifest(
        manifest=manifest,
        engines=list(args.engines),
        artifacts_dir=args.artifacts_dir,
        run_id=args.run_id,
        workspace_root=workspace_root,
        tessdata_dir=args.tessdata_dir,
        tesseract_psm=args.tesseract_psm,
        paddle_device=args.paddle_device,
        tesseract_cmd=args.tesseract_cmd,
        include_digital_text_pages=args.include_digital_text_pages,
        warmup=args.warmup,
        logger=logger,
    )

    total_failed = sum(engine_info["failed"] for engine_info in summary["engines"].values())
    log_event(
        logger,
        logging.INFO,
        "OCR run finished",
        run_id=summary["run_id"],
        run_manifest_path=summary["run_manifest_path"],
        total_failed=total_failed,
    )
    return 1 if total_failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
