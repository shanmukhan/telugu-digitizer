#!/usr/bin/env python3
"""Export verified Telugu OCR line crops into PaddleOCR PP-OCRv5 & Tesseract 5 tesstrain dataset bundles."""

from __future__ import annotations

import argparse
import uuid

from src.core.config import AppSettings
from src.core.storage import LocalFilesystemStorage
from src.db.session import build_engine, build_session_factory
from src.services.training_service import export_visual_training_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Export verified Telugu OCR crops for visual fine-tuning.")
    parser.add_argument("--book-id", type=str, default=None, help="Optional Book UUID to restrict export.")
    parser.add_argument("--val-ratio", type=float, default=0.15, help="Validation page split ratio (0.05–0.40).")
    args = parser.parse_args()

    settings = AppSettings.from_env()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    storage = LocalFilesystemStorage(settings.workspace_dir)

    with session_factory() as db:
        result = export_visual_training_dataset(
            db=db,
            storage=storage,
            book_id=uuid.UUID(args.book_id) if args.book_id else None,
            val_ratio=args.val_ratio,
        )
    print(f"Exported {result['total_samples']} verified samples (train={result['train_count']}, val={result['val_count']})")
    print(f"Archive: {settings.workspace_dir / 'training_exports' / str(result['export_id']) / result['filename']}")
    print(f"SHA-256: {result['archive_sha256']}")


if __name__ == "__main__":
    main()
