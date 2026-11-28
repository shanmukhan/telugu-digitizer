"""Visual OCR fine-tuning dataset curation, crop harvesting, and PaddleOCR + Tesseract export."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.errors import AppError
from src.common.logging_utils import log_event
from src.core.storage import LocalFilesystemStorage
from src.db.models import Book, BookPage, DocumentTextBlock, DocumentTextVersion, OCRBlock, ReviewEdit, TrainingSample
from src.evaluation.metrics import normalize_nfc
from src.services.review_service import _maybe_record_training_sample

LOGGER = logging.getLogger("telugu_digitizer.services.training")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def set_book_training_consent(
    *,
    db: Session,
    storage: LocalFilesystemStorage,
    book_id: uuid.UUID,
    training_consent: bool,
    harvest_existing: bool = True,
) -> dict[str, Any]:
    """Toggle training consent for a book and optionally backfill verified line crops from past edits."""
    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    book.training_consent = bool(training_consent)
    db.flush()

    harvested_count = 0
    if not training_consent:
        # Respect revoked consent immediately by disallowing existing samples from export.
        for sample in db.scalars(select(TrainingSample).where(TrainingSample.book_id == book.id)).all():
            sample.allowed_for_training = False
    elif harvest_existing:
        # Backfill verified crops from human-corrected/approved blocks across this book.
        pages = list(
            db.scalars(select(BookPage).where(BookPage.book_id == book.id).order_by(BookPage.page_number)).all()
        )
        page_by_id = {p.id: p for p in pages}

        draft_ver = db.scalars(
            select(DocumentTextVersion)
            .where(DocumentTextVersion.book_id == book.id, DocumentTextVersion.origin == "human_approved")
            .order_by(DocumentTextVersion.version_number.desc())
        ).first()
        ignored_block_ids: set[uuid.UUID] = set()
        if draft_ver is not None:
            ignored_block_ids = set(
                db.scalars(
                    select(DocumentTextBlock.ocr_block_id).where(
                        DocumentTextBlock.version_id == draft_ver.id,
                        DocumentTextBlock.block_role == "ignore",
                        DocumentTextBlock.ocr_block_id.is_not(None),
                    )
                ).all()
            )

        # Find latest human-verified edits (corrected or approved) for blocks in this book.
        block_rows = list(
            db.scalars(
                select(OCRBlock)
                .join(BookPage, OCRBlock.book_page_id == BookPage.id)
                .where(BookPage.book_id == book.id)
            ).all()
        )
        block_by_id = {b.id: b for b in block_rows}
        if block_by_id:
            latest_human_edit: dict[uuid.UUID, ReviewEdit] = {}
            for edit in db.scalars(
                select(ReviewEdit)
                .where(
                    ReviewEdit.ocr_block_id.in_(list(block_by_id.keys())),
                    ReviewEdit.action.in_(["corrected", "approved"]),
                )
                .order_by(ReviewEdit.created_at.asc(), ReviewEdit.id.asc())
            ).all():
                latest_human_edit[edit.ocr_block_id] = edit

            before_existing = int(
                db.scalar(
                    select(func.count(TrainingSample.id)).where(
                        TrainingSample.book_id == book.id,
                        TrainingSample.allowed_for_training.is_(True),
                    )
                )
                or 0
            )
            for blk_id, edit in latest_human_edit.items():
                if blk_id in ignored_block_ids:
                    continue
                blk = block_by_id.get(blk_id)
                if blk is None:
                    continue
                page = page_by_id.get(blk.book_page_id)
                if page is None:
                    continue
                _maybe_record_training_sample(
                    db=db,
                    storage=storage,
                    book=book,
                    page=page,
                    block=blk,
                    verified_text=edit.edited_text,
                    reviewer_id=edit.reviewer_id,
                )
            db.flush()
            after_existing = int(
                db.scalar(
                    select(func.count(TrainingSample.id)).where(
                        TrainingSample.book_id == book.id,
                        TrainingSample.allowed_for_training.is_(True),
                    )
                )
                or 0
            )
            harvested_count = max(0, after_existing - before_existing)

    db.commit()
    total_book_samples = int(
        db.scalar(
            select(func.count(TrainingSample.id)).where(
                TrainingSample.book_id == book.id,
                TrainingSample.allowed_for_training.is_(True),
            )
        )
        or 0
    )
    log_event(
        LOGGER,
        logging.INFO,
        "Updated book training consent",
        book_id=str(book.id),
        training_consent=book.training_consent,
        harvested_crops_count=harvested_count,
        total_book_samples=total_book_samples,
    )
    return {
        "book_id": book.id,
        "training_consent": book.training_consent,
        "harvested_crops_count": harvested_count,
        "total_book_samples": total_book_samples,
    }


def get_training_dataset_summary(
    db: Session,
    *,
    book_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Summarize verified visual OCR training crops across consented books."""
    books = list(db.scalars(select(Book).order_by(Book.created_at.desc())).all())
    sample_counts_rows = db.execute(
        select(
            TrainingSample.book_id,
            func.count(TrainingSample.id),
            func.count(func.distinct(TrainingSample.image_crop_sha256)),
        )
        .join(Book, TrainingSample.book_id == Book.id)
        .where(
            TrainingSample.allowed_for_training.is_(True),
            Book.training_consent.is_(True),
        )
        .group_by(TrainingSample.book_id)
    ).all()
    counts_by_book = {row[0]: int(row[1]) for row in sample_counts_rows}

    total_verified = sum(counts_by_book.values())
    unique_hashes = int(
        db.scalar(
            select(func.count(func.distinct(TrainingSample.image_crop_sha256)))
            .join(Book, TrainingSample.book_id == Book.id)
            .where(
                TrainingSample.allowed_for_training.is_(True),
                Book.training_consent.is_(True),
            )
        )
        or 0
    )

    book_items = [
        {
            "book_id": b.id,
            "title": b.title,
            "training_consent": b.training_consent,
            "verified_samples_count": counts_by_book.get(b.id, 0),
        }
        for b in books
    ]
    consented_books_count = sum(1 for b in books if b.training_consent)
    selected_book = next((b for b in books if b.id == book_id), None) if book_id else None

    return {
        "total_verified_samples": total_verified,
        "unique_crop_hashes": unique_hashes,
        "consented_books_count": consented_books_count,
        "selected_book_consent": selected_book.training_consent if selected_book else None,
        "selected_book_samples": counts_by_book.get(selected_book.id, 0) if selected_book else 0,
        "books": book_items,
    }


def _paddle_finetune_yaml_template() -> str:
    return """# PaddleOCR PP-OCRv5 Telugu Recognition Fine-Tuning Template
# Generated by Telugu Book Digitizer from human-verified line crops.
# Train offline on a GPU workstation using official PaddleOCR:
#   python3 tools/train.py -c paddleocr/rec_te_ppocrv5_finetune.yml

Global:
  use_gpu: true
  epoch_num: 40
  log_smooth_window: 20
  print_batch_step: 10
  save_model_dir: ./output/te_ppocrv5_book_finetune
  save_epoch_step: 5
  eval_batch_step: [0, 200]
  pretrained_model: ./pretrain_models/te_PP-OCRv5_mobile_rec/best_accuracy
  character_dict_path: ./ppocr/utils/dict/te_dict.txt
  use_space_char: true
  max_text_length: 80

Train:
  dataset:
    name: SimpleDataSet
    data_dir: ./paddleocr/
    label_file_list:
      - ./paddleocr/train_list.txt
  loader:
    shuffle: true
    batch_size_per_card: 32
    num_workers: 4

Eval:
  dataset:
    name: SimpleDataSet
    data_dir: ./paddleocr/
    label_file_list:
      - ./paddleocr/val_list.txt
  loader:
    shuffle: false
    batch_size_per_card: 32
    num_workers: 2
"""


def _training_readme_text(total: int, train_cnt: int, val_cnt: int) -> str:
    return (
        "Telugu Book Digitizer — Visual OCR Fine-Tuning Dataset Bundle\n"
        "=============================================================\n\n"
        f"Total deduplicated verified line crops: {total} (train={train_cnt}, val={val_cnt})\n"
        "Splits are grouped at the page level so crops from the same page never leak across train/val.\n\n"
        "1. PaddleOCR PP-OCRv5 Telugu fine-tuning (GPU workstation):\n"
        "   - Dataset images: paddleocr/images/*.png\n"
        "   - Labels: paddleocr/train_list.txt, paddleocr/val_list.txt\n"
        "   - Config template: paddleocr/rec_te_ppocrv5_finetune.yml\n"
        "   - Command:\n"
        "       python3 tools/train.py -c paddleocr/rec_te_ppocrv5_finetune.yml\n\n"
        "2. Tesseract 5 LSTM fine-tuning (tesstrain):\n"
        "   - Ground-truth pairs: tesseract/ground-truth/*.png + *.gt.txt\n"
        "   - Command (inside tesstrain repo):\n"
        "       make training MODEL_NAME=tel_custom START_MODEL=tel TESSDATA=/path/to/tessdata_best \\\n"
        "         GROUND_TRUTH_DIR=/path/to/extracted/tesseract/ground-truth MAX_ITERATIONS=2000\n"
    )


def export_visual_training_dataset(
    *,
    db: Session,
    storage: LocalFilesystemStorage,
    book_id: uuid.UUID | None = None,
    val_ratio: float = 0.15,
) -> dict[str, Any]:
    """Export deduplicated, page-split verified line crops as a ZIP bundle for PaddleOCR + Tesseract fine-tuning."""
    stmt = (
        select(TrainingSample, Book, BookPage)
        .join(Book, TrainingSample.book_id == Book.id)
        .join(BookPage, TrainingSample.book_page_id == BookPage.id)
        .where(
            TrainingSample.allowed_for_training.is_(True),
            Book.training_consent.is_(True),
        )
        .order_by(Book.id, BookPage.page_number, TrainingSample.created_at)
    )
    if book_id is not None:
        stmt = stmt.where(TrainingSample.book_id == book_id)

    rows = db.execute(stmt).all()
    if not rows:
        raise AppError(
            "NO_TRAINING_SAMPLES",
            "No verified training crops available. Enable 'Collect verified crops for OCR training' on a book and approve/correct lines first.",
            status_code=400,
        )

    # Deduplicate by crop SHA-256 and ensure crop files exist on disk.
    seen_hashes: set[str] = set()
    dedup_skipped = 0
    missing_files = 0
    grouped_by_page: dict[tuple[uuid.UUID, int], list[tuple[TrainingSample, Book, BookPage, Path]]] = defaultdict(list)

    for sample, book, page in rows:
        cleaned_text = normalize_nfc(sample.verified_text or "").strip().replace("\n", " ").replace("\t", " ")
        if not cleaned_text:
            continue
        if sample.image_crop_sha256 in seen_hashes:
            dedup_skipped += 1
            continue
        if not storage.exists(sample.image_crop_storage_key):
            missing_files += 1
            continue
        seen_hashes.add(sample.image_crop_sha256)
        grouped_by_page[(book.id, page.page_number)].append(
            (sample, book, page, storage.resolve_key(sample.image_crop_storage_key))
        )

    if not grouped_by_page:
        raise AppError(
            "NO_TRAINING_SAMPLES",
            "Verified training crop files were missing on disk. Re-enable training consent to re-harvest crops.",
            status_code=400,
        )

    # Deterministic page-level train/val split (prevents same-page leakage).
    page_keys = sorted(grouped_by_page.keys(), key=lambda pk: (str(pk[0]), pk[1]))
    safe_val_ratio = max(0.05, min(0.4, float(val_ratio)))
    val_page_set: set[tuple[uuid.UUID, int]] = set()
    if len(page_keys) >= 2:
        n_val_pages = max(1, int(round(len(page_keys) * safe_val_ratio)))
        step = max(1, len(page_keys) // n_val_pages)
        for idx in range(len(page_keys) - 1, -1, -step):
            val_page_set.add(page_keys[idx])
            if len(val_page_set) >= n_val_pages:
                break

    export_id = uuid.uuid4()
    filename = f"telugu-ocr-finetune-{str(export_id)[:8]}.zip"
    storage_key = f"training_exports/{export_id}/{filename}"
    out_path = storage.resolve_key(storage_key)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    train_lines: list[str] = []
    val_lines: list[str] = []
    manifest_samples: list[dict[str, Any]] = []

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for pk in page_keys:
            split = "val" if pk in val_page_set else "train"
            for sample, book, page, img_path in grouped_by_page[pk]:
                sample_stem = f"{str(book.id)[:8]}_p{page.page_number:04d}_{str(sample.id)[:8]}"
                img_bytes = img_path.read_bytes()
                verified_nfc = normalize_nfc(sample.verified_text).strip().replace("\n", " ").replace("\t", " ")

                # 1. PaddleOCR recognition format
                paddle_rel = f"images/{sample_stem}.png"
                zf.writestr(f"paddleocr/{paddle_rel}", img_bytes)
                label_line = f"{paddle_rel}\t{verified_nfc}"
                if split == "val":
                    val_lines.append(label_line)
                else:
                    train_lines.append(label_line)

                # 2. Tesseract 5 tesstrain format (.png + .gt.txt)
                zf.writestr(f"tesseract/ground-truth/{sample_stem}.png", img_bytes)
                zf.writestr(f"tesseract/ground-truth/{sample_stem}.gt.txt", f"{verified_nfc}\n")

                manifest_samples.append(
                    {
                        "sample_id": str(sample.id),
                        "split": split,
                        "book_id": str(book.id),
                        "book_title": book.title,
                        "page_number": page.page_number,
                        "crop_sha256": sample.image_crop_sha256,
                        "ocr_text": sample.ocr_text,
                        "verified_text": verified_nfc,
                    }
                )

        # If only 1 page existed, mirror val_list from train_list so PaddleOCR eval config runs smoothly.
        if not val_lines and train_lines:
            val_lines = list(train_lines[: max(1, min(5, len(train_lines)))])

        zf.writestr("paddleocr/train_list.txt", "\n".join(train_lines) + "\n")
        zf.writestr("paddleocr/val_list.txt", "\n".join(val_lines) + "\n")
        zf.writestr("paddleocr/rec_te_ppocrv5_finetune.yml", _paddle_finetune_yaml_template())
        zf.writestr(
            "README.txt",
            _training_readme_text(len(manifest_samples), len(train_lines), len(val_lines)),
        )
        manifest = {
            "export_id": str(export_id),
            "created_at": _utcnow().isoformat(),
            "book_filter": str(book_id) if book_id else None,
            "total_samples": len(manifest_samples),
            "train_count": len(train_lines),
            "val_count": len(val_lines),
            "deduplicated_skipped": dedup_skipped,
            "missing_files_skipped": missing_files,
            "samples": manifest_samples,
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    archive_sha = hashlib.sha256(out_path.read_bytes()).hexdigest()
    log_event(
        LOGGER,
        logging.INFO,
        "Exported visual OCR fine-tuning dataset bundle",
        export_id=str(export_id),
        total_samples=len(manifest_samples),
        train_count=len(train_lines),
        val_count=len(val_lines),
        deduplicated_skipped=dedup_skipped,
        archive_sha256=archive_sha,
    )
    return {
        "export_id": export_id,
        "filename": filename,
        "total_samples": len(manifest_samples),
        "train_count": len(train_lines),
        "val_count": len(val_lines),
        "deduplicated_skipped": dedup_skipped,
        "archive_sha256": archive_sha,
        "download_url": f"/api/v1/training/exports/{export_id}/download",
        "created_at": _utcnow(),
    }


def resolve_training_export_archive(
    storage: LocalFilesystemStorage,
    export_id: uuid.UUID,
) -> tuple[Path, str]:
    """Resolve an exported training dataset ZIP archive safely within workspace/training_exports."""
    export_dir = storage.workspace_root / "training_exports" / str(export_id)
    if not export_dir.is_dir():
        raise AppError("TRAINING_EXPORT_NOT_FOUND", f"Training export {export_id} not found.", status_code=404)
    zips = sorted(export_dir.glob("*.zip"))
    if not zips:
        raise AppError("TRAINING_EXPORT_NOT_FOUND", f"Training export archive missing for {export_id}.", status_code=404)
    return zips[0], zips[0].name
