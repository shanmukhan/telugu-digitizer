#!/usr/bin/env python3
"""CLI tool to inspect, classify, and rasterize PDF pages to 300 DPI PNGs."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.common.io import sanitize_id, validate_within_workspace
from src.common.logging_utils import configure_logging, log_event
from src.common.manifest import DatasetManifest, load_manifest, save_manifest
from src.pdf.rasterizer import render_pdf_pages


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render PDF pages to deterministic RGB PNGs and write/update a page manifest."
    )
    parser.add_argument("--pdf", type=Path, required=True, help="Path to source PDF file.")
    parser.add_argument("--book-id", type=str, required=True, help="Filesystem-safe book identifier.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/pages"),
        help="Directory where <book_id>/page-NNNN.png will be written.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional manifest JSON path (created or updated for book_id/pages).",
    )
    parser.add_argument("--dataset-version", type=str, default="phase1-v1")
    parser.add_argument("--dpi", type=int, default=300, help="Render DPI (default: 300).")
    parser.add_argument("--start-page", type=int, default=None, help="1-based start page.")
    parser.add_argument("--end-page", type=int, default=None, help="1-based end page.")
    parser.add_argument("--split", type=str, default="unspecified", help="Dataset split (dev/val/test).")
    parser.add_argument("--page-quality", type=str, default="unspecified", help="clean/degraded/etc.")
    parser.add_argument("--layout-type", type=str, default="unspecified", help="single_column/two_column/etc.")
    parser.add_argument("--skip-existing", action="store_true", help="Reuse existing rendered PNGs.")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=Path.cwd(),
        help="Workspace root used to validate output paths.",
    )
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logger = configure_logging(args.log_level)
    book_id = sanitize_id(args.book_id)
    workspace_root = args.workspace_root.resolve()

    entries = render_pdf_pages(
        pdf_path=args.pdf,
        book_id=book_id,
        output_dir=args.output_dir,
        workspace_root=workspace_root,
        dpi=args.dpi,
        start_page=args.start_page,
        end_page=args.end_page,
        split=args.split,
        page_quality=args.page_quality,
        layout_type=args.layout_type,
        skip_existing=args.skip_existing,
    )

    manifest_path = args.manifest or (Path("data/manifests") / f"{book_id}.json")
    manifest_path = validate_within_workspace(manifest_path, workspace_root)
    if manifest_path.is_file():
        manifest = load_manifest(manifest_path)
        existing = {(e.book_id, e.page_number): e for e in manifest.pages}
        for entry in entries:
            existing[(entry.book_id, entry.page_number)] = entry
        manifest.pages = sorted(existing.values(), key=lambda e: (e.book_id, e.page_number))
    else:
        manifest = DatasetManifest(dataset_version=args.dataset_version, pages=entries)

    save_manifest(manifest, manifest_path)
    failed = [e for e in entries if e.status != "rendered"]
    log_event(
        logger,
        logging.INFO,
        "Saved rasterized page manifest",
        manifest_path=str(manifest_path),
        rendered_count=len(entries) - len(failed),
        failed_count=len(failed),
    )
    return 1 if failed and len(failed) == len(entries) else 0


if __name__ == "__main__":
    sys.exit(main())
