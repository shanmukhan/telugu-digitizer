"""Durable, restartable, idempotent Phase 2 OCR execution service."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import logging
import platform
import resource
import shutil
import sys
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from src.api.errors import AppError
from src.common.io import sha256_bytes, sha256_file
from src.common.logging_utils import log_event
from src.core.config import AppSettings
from src.core.storage import LocalFilesystemStorage
from src.db.models import Book, BookPage, ModelRegistry, OCRBlock, OCRRun, ProcessingJob
from src.evaluation.metrics import normalize_nfc
from src.ocr.base import OCRProvider, build_page_ocr_record
from src.ocr.paddle_provider import PaddleOCRProvider
from src.ocr.paddle_worker import IsolatedPaddleOCRProvider
from src.ocr.tesseract_provider import TesseractOCRProvider
from src.pdf.rasterizer import DEFAULT_MAX_RENDER_PIXELS, bounded_pixmap_matrix

LOGGER = logging.getLogger("telugu_digitizer.services.ocr")

ENGINE_ALIASES: dict[str, str] = {
    "paddle": "paddle_ppocrv5_te",
    "paddleocr": "paddle_ppocrv5_te",
    "paddle_ppocrv5_te": "paddle_ppocrv5_te",
    "tesseract": "tesseract_tel_best",
    "tesseract_tel_best": "tesseract_tel_best",
}

ALLOWED_PREPROCESSING_PROFILES = {"none", "deskew", "contrast_clahe", "textured_bold"}


def _peak_rss_mb() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
    return round(raw / divisor, 1)


def canonicalize_engine_name(raw_name: str) -> str:
    """Map API engine names to canonical Phase 1/2 engine identifiers."""
    key = raw_name.strip().lower()
    if key not in ENGINE_ALIASES:
        raise AppError(
            "UNSUPPORTED_OCR_ENGINE",
            f"Unsupported OCR engine {raw_name!r}. Allowed: paddle_ppocrv5_te, tesseract_tel_best.",
            status_code=400,
        )
    return ENGINE_ALIASES[key]


def inspect_host_ocr_capabilities(settings: AppSettings) -> dict[str, Any]:
    """Inspect which OCR engines are runnable on the current host without loading weights."""
    paddle_reason: str | None = None
    paddle_available = False
    if not settings.enable_paddle_ocr:
        paddle_reason = "Disabled via ENABLE_PADDLE_OCR=false"
    elif importlib.util.find_spec("paddle") is None:
        paddle_reason = "paddlepaddle package is not installed on this host"
    elif importlib.util.find_spec("paddleocr") is None:
        paddle_reason = "paddleocr package is not installed on this host"
    else:
        paddle_available = True

    tess_bin = settings.tesseract_cmd or shutil.which("tesseract")
    tess_traineddata = settings.tessdata_dir / "tel.traineddata"
    tess_reason: str | None = None
    tess_available = False
    if not tess_bin or not Path(str(tess_bin)).exists() and shutil.which(str(tess_bin or "")) is None:
        tess_reason = "tesseract CLI binary is not installed"
    elif not tess_traineddata.is_file():
        tess_reason = f"Missing {tess_traineddata}"
    else:
        tess_available = True

    admin_configured = bool(settings.effective_admin_credentials)
    auth_enabled = bool(settings.auth_username and settings.auth_password)
    return {
        "platform_machine": platform.machine(),
        "auth_enabled": auth_enabled,
        "guest_ocr_enabled": (not auth_enabled) and settings.allow_guest_ocr,
        "admin_delete_requires_auth": admin_configured or settings.is_network_exposed,
        "book_delete_enabled": False if not settings.is_network_exposed else False,
        "max_upload_mb": settings.max_upload_mb,
        "max_pdf_pages": settings.max_pdf_pages,
        "engines": {
            "paddle_ppocrv5_te": {
                "available": paddle_available,
                "reason": paddle_reason,
                "model_id": "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
            },
            "tesseract_tel_best": {
                "available": tess_available,
                "reason": tess_reason,
                "model_id": "tesseract-5-tel-best",
            },
        },
    }


def build_ocr_provider(
    canonical_engine: str,
    settings: AppSettings,
    *,
    tesseract_psm: int = 6,
) -> OCRProvider:
    """Instantiate a pinned Phase 1/2 OCRProvider for the canonical engine key."""
    if canonical_engine == "paddle_ppocrv5_te":
        if not settings.enable_paddle_ocr:
            raise AppError(
                "OCR_MODEL_NOT_AVAILABLE",
                "PaddleOCR is disabled on this host (ENABLE_PADDLE_OCR=false). Select Tesseract 5 Telugu instead.",
                status_code=503,
                details={"engine": "paddleocr"},
            )
        if importlib.util.find_spec("paddle") is None or importlib.util.find_spec("paddleocr") is None:
            raise AppError(
                "OCR_MODEL_NOT_AVAILABLE",
                "PaddleOCR runtime (paddlepaddle/paddleocr) is not installed on this host.",
                status_code=503,
                details={"engine": "paddleocr"},
            )
        if settings.isolate_ocr_worker:
            return IsolatedPaddleOCRProvider(
                lang="te",
                ocr_version="PP-OCRv5",
                device=settings.paddle_device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                timeout_sec=float(settings.ocr_page_timeout_sec),
            )
        return PaddleOCRProvider(
            lang="te",
            ocr_version="PP-OCRv5",
            device=settings.paddle_device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    if canonical_engine == "tesseract_tel_best":
        try:
            return TesseractOCRProvider(
                tessdata_dir=settings.tessdata_dir,
                lang="tel",
                oem=1,
                psm=tesseract_psm,
                tesseract_cmd=settings.tesseract_cmd,
                timeout_sec=float(settings.ocr_page_timeout_sec),
            )
        except FileNotFoundError as exc:
            raise AppError(
                "OCR_MODEL_NOT_AVAILABLE",
                f"Configured Telugu OCR model or runtime unavailable: {exc}",
                status_code=503,
                details={"engine": "tesseract", "tessdata_dir": str(settings.tessdata_dir)},
            ) from exc
    raise AppError("UNSUPPORTED_OCR_ENGINE", f"Unknown engine: {canonical_engine}", status_code=400)


def get_or_create_model_registry(db: Session, provider: OCRProvider) -> ModelRegistry:
    """Persist or reuse a ModelRegistry entry from provider metadata."""
    meta = provider.provider_metadata()
    engine_name = str(meta["engine"])
    engine_version = str(meta.get("engine_version") or "")
    model_id = str(meta["model_id"])

    sha = meta.get("traineddata_sha256")
    if not sha and isinstance(meta.get("model_checksums"), dict) and meta["model_checksums"]:
        combined = json.dumps(meta["model_checksums"], sort_keys=True)
        sha = sha256_bytes(combined.encode("utf-8"))

    existing = db.scalars(
        select(ModelRegistry).where(
            ModelRegistry.engine_name == engine_name,
            ModelRegistry.engine_version == engine_version,
            ModelRegistry.model_id == model_id,
            ModelRegistry.model_sha256 == sha,
        )
    ).first()
    if existing is not None:
        return existing

    entry = ModelRegistry(
        engine_name=engine_name,
        engine_version=engine_version,
        model_family="PP-OCRv5" if engine_name == "paddleocr" else "tessdata_best",
        model_id=model_id,
        model_sha256=sha,
        runtime_name="paddlepaddle" if engine_name == "paddleocr" else "tesseract-cli",
        runtime_version=meta.get("framework_version") or engine_version,
        device=meta.get("config", {}).get("device") if isinstance(meta.get("config"), dict) else "cpu",
        model_metadata=meta,
    )
    db.add(entry)
    db.flush()
    return entry


def compute_run_idempotency_key(
    *,
    book_id: uuid.UUID,
    canonical_engine: str,
    start_page: int,
    end_page: int,
    render_dpi: int,
    preprocessing_profile: str,
    tesseract_psm: int,
    include_digital_text_pages: bool,
    apply_calibration_corrections: bool = False,
) -> str:
    """Compute a deterministic SHA-256 key for idempotent OCR run lookup."""
    payload = {
        "book_id": str(book_id),
        "engine": canonical_engine,
        "start_page": start_page,
        "end_page": end_page,
        "render_dpi": render_dpi,
        "preprocessing_profile": preprocessing_profile,
        "tesseract_psm": tesseract_psm if canonical_engine == "tesseract_tel_best" else None,
        "include_digital_text_pages": include_digital_text_pages,
        "apply_calibration_corrections": bool(apply_calibration_corrections),
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True).encode("utf-8"))


class OCRJobExecutor:
    """Single-worker background executor for durable PostgreSQL-backed OCR runs."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        storage: LocalFilesystemStorage,
        settings: AppSettings,
    ) -> None:
        self.session_factory = session_factory
        self.storage = storage
        self.settings = settings
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr-worker")
        self._futures: dict[uuid.UUID, Future[Any]] = {}
        self._providers: dict[tuple[str, int], OCRProvider] = {}
        self._cancelled_runs: set[uuid.UUID] = set()

    def get_provider(self, canonical_engine: str, *, tesseract_psm: int = 6) -> OCRProvider:
        """Return a cached OCRProvider instance so warm model weights persist across runs."""
        cache_key = (
            canonical_engine,
            int(tesseract_psm) if canonical_engine == "tesseract_tel_best" else 0,
        )
        with self._lock:
            provider = self._providers.get(cache_key)
            if provider is None:
                provider = build_ocr_provider(
                    canonical_engine,
                    self.settings,
                    tesseract_psm=tesseract_psm,
                )
                self._providers[cache_key] = provider
            return provider

    def submit_runs(self, run_ids: list[uuid.UUID]) -> None:
        with self._lock:
            # Prune older completed futures to prevent unbounded memory retention.
            if len(self._futures) > 64:
                done_ids = [rid for rid, f in self._futures.items() if f.done()]
                for rid in done_ids[:-32]:
                    self._futures.pop(rid, None)
            for run_id in run_ids:
                self._cancelled_runs.discard(run_id)
                existing_fut = self._futures.get(run_id)
                if existing_fut is not None and not existing_fut.done():
                    continue
                fut = self._executor.submit(self.execute_run, run_id)
                self._futures[run_id] = fut

    def cancel_run(self, run_id: uuid.UUID) -> None:
        """Mark an active or queued run for cooperative cancellation."""
        with self._lock:
            self._cancelled_runs.add(run_id)
            fut = self._futures.get(run_id)
            if fut is not None and not fut.done():
                fut.cancel()

    def wait_for_run(self, run_id: uuid.UUID, timeout: float | None = 120.0) -> None:
        with self._lock:
            fut = self._futures.get(run_id)
        if fut is not None:
            fut.result(timeout=timeout)

    def wait_for_runs_settled(self, run_ids: list[uuid.UUID], timeout: float = 5.0) -> None:
        with self._lock:
            futs = [self._futures[rid] for rid in run_ids if rid in self._futures]
        deadline = datetime.now(timezone.utc).timestamp() + max(0.1, timeout)
        for fut in futs:
            remaining = max(0.05, deadline - datetime.now(timezone.utc).timestamp())
            try:
                fut.result(timeout=remaining)
            except Exception:
                pass

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            providers = list(self._providers.values())
            self._providers.clear()
        self._executor.shutdown(wait=wait)
        for prov in providers:
            close_fn = getattr(prov, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass
        with self._lock:
            self._futures.clear()

    def _ensure_page_image_path(
        self,
        *,
        book: Book,
        page: BookPage,
        requested_dpi: int,
        open_pdf_doc: pymupdf.Document | None = None,
    ) -> tuple[Path, str, str, int | None, int | None]:
        """Resolve or deterministically render the page PNG at requested_dpi."""
        if (
            page.image_storage_key
            and page.render_dpi == requested_dpi
            and self.storage.exists(page.image_storage_key)
        ):
            img_path = self.storage.resolve_key(page.image_storage_key)
            img_sha = page.image_sha256 or sha256_file(img_path)
            return img_path, page.image_storage_key, img_sha, page.width_px, page.height_px

        target_key = (
            page.image_storage_key
            if (page.image_storage_key and (page.render_dpi or 300) == requested_dpi)
            else f"pages/{book.id}/dpi-{requested_dpi}/page-{page.page_number:04d}.png"
        )
        if self.storage.exists(target_key):
            img_path = self.storage.resolve_key(target_key)
            with Image.open(img_path) as im:
                w, h = im.size
            return img_path, target_key, sha256_file(img_path), w, h

        max_pixels = getattr(self.settings, "max_render_pixels", DEFAULT_MAX_RENDER_PIXELS)
        if open_pdf_doc is not None:
            pdf_page = open_pdf_doc.load_page(page.page_number - 1)
            matrix, _eff_dpi, _clamped = bounded_pixmap_matrix(
                pdf_page.rect, requested_dpi, max_pixels=max_pixels
            )
            pix = pdf_page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)
            png_bytes = pix.tobytes("png")
            width_px, height_px = int(pix.width), int(pix.height)
        else:
            source_pdf_path = self.storage.resolve_key(book.source_storage_key)
            with pymupdf.open(source_pdf_path) as doc:
                pdf_page = doc.load_page(page.page_number - 1)
                matrix, _eff_dpi, _clamped = bounded_pixmap_matrix(
                    pdf_page.rect, requested_dpi, max_pixels=max_pixels
                )
                pix = pdf_page.get_pixmap(matrix=matrix, colorspace=pymupdf.csRGB, alpha=False)
                png_bytes = pix.tobytes("png")
                width_px, height_px = int(pix.width), int(pix.height)
        img_path = self.storage.write_bytes(target_key, png_bytes, read_only=False)
        img_sha = sha256_bytes(png_bytes)
        if target_key == page.image_storage_key:
            page.image_sha256 = img_sha
            page.width_px = width_px
            page.height_px = height_px
        return img_path, target_key, img_sha, width_px, height_px

    def _apply_preprocessing_profile(
        self,
        *,
        img_path: Path,
        img_key: str,
        img_sha: str,
        img_w: int | None,
        img_h: int | None,
        book_id: uuid.UUID,
        page_number: int,
        render_dpi: int,
        profile: str,
    ) -> tuple[Path, str, str, int | None, int | None]:
        """Apply optional non-destructive preprocessing without modifying the original render."""
        if profile == "none":
            return img_path, img_key, img_sha, img_w, img_h

        derived_key = f"pages/{book_id}/pre-{profile}-dpi-{render_dpi}/page-{page_number:04d}.png"
        if self.storage.exists(derived_key):
            derived_path = self.storage.resolve_key(derived_key)
            with Image.open(derived_path) as im:
                w, h = im.size
            return derived_path, derived_key, sha256_file(derived_path), w, h

        import cv2
        import numpy as np

        img_bgr = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if img_bgr is None:
            return img_path, img_key, img_sha, img_w, img_h

        if profile == "contrast_clahe":
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            out_img = clahe.apply(gray)
        elif profile == "textured_bold":
            # Designed for bold halftone/stippled display headings and degraded book scans:
            # 1) Mild auto-deskew on inner margin, 2) CLAHE contrast normalization,
            # 3) 2x2 morphological opening to fill white stippling inside dark strokes,
            # 4) Gentle unsharp mask to keep Telugu vattus and vowel ticks crisp.
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            h_img, w_img = gray.shape[:2]
            margin_y = max(0, int(h_img * 0.05))
            margin_x = max(0, int(w_img * 0.05))
            roi = gray[margin_y : h_img - margin_y, margin_x : w_img - margin_x]
            if roi.size == 0:
                roi = gray
            inv = cv2.bitwise_not(roi)
            thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
            dil_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
            dilated = cv2.dilate(thresh, dil_kernel, iterations=1)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            angles: list[float] = []
            for cnt in contours:
                x_c, y_c, w_c, h_c = cv2.boundingRect(cnt)
                if w_c < 40 or h_c < 8 or w_c > roi.shape[1] * 0.95 or h_c > roi.shape[0] * 0.30:
                    continue
                rect_angle = float(cv2.minAreaRect(cnt)[-1])
                if rect_angle < -45:
                    cand_angle = -(90 + rect_angle)
                elif rect_angle > 45:
                    cand_angle = 90 - rect_angle
                else:
                    cand_angle = -rect_angle
                if abs(cand_angle) <= 12.0:
                    angles.append(cand_angle)
            angle = float(np.median(angles)) if angles else 0.0
            work_gray = gray
            if 0.4 <= abs(angle) <= 12.0:
                center = (w_img // 2, h_img // 2)
                rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
                work_gray = cv2.warpAffine(
                    gray,
                    rot_mat,
                    (w_img, h_img),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )
            clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
            norm_gray = clahe.apply(work_gray)
            stipple_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
            solid_ink = cv2.morphologyEx(norm_gray, cv2.MORPH_OPEN, stipple_kernel)
            blurred = cv2.GaussianBlur(solid_ink, (0, 0), sigmaX=1.0)
            out_img = cv2.addWeighted(solid_ink, 1.35, blurred, -0.35, 0)
        elif profile == "deskew":
            # Focus on the inner 90% margin and horizontally dilate text glyphs into line bars
            # so dark scanner borders / spine shadows do not dominate minAreaRect.
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            h_img, w_img = gray.shape[:2]
            margin_y = max(0, int(h_img * 0.05))
            margin_x = max(0, int(w_img * 0.05))
            roi = gray[margin_y : h_img - margin_y, margin_x : w_img - margin_x]
            if roi.size == 0:
                roi = gray
            inv = cv2.bitwise_not(roi)
            thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
            dilated = cv2.dilate(thresh, kernel, iterations=1)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            angles: list[float] = []
            for cnt in contours:
                x_c, y_c, w_c, h_c = cv2.boundingRect(cnt)
                if w_c < 40 or h_c < 8 or w_c > roi.shape[1] * 0.95 or h_c > roi.shape[0] * 0.30:
                    continue
                rect_angle = float(cv2.minAreaRect(cnt)[-1])
                if rect_angle < -45:
                    cand_angle = -(90 + rect_angle)
                elif rect_angle > 45:
                    cand_angle = 90 - rect_angle
                else:
                    cand_angle = -rect_angle
                if abs(cand_angle) <= 12.0:
                    angles.append(cand_angle)
            angle = float(np.median(angles)) if angles else 0.0
            if 0.4 <= abs(angle) <= 12.0:
                center = (w_img // 2, h_img // 2)
                rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
                out_img = cv2.warpAffine(
                    img_bgr,
                    rot_mat,
                    (w_img, h_img),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )
            else:
                out_img = img_bgr
        else:
            return img_path, img_key, img_sha, img_w, img_h

        ok, enc = cv2.imencode(".png", out_img)
        if not ok:
            return img_path, img_key, img_sha, img_w, img_h
        png_bytes = enc.tobytes()
        derived_path = self.storage.write_bytes(derived_key, png_bytes, read_only=False)
        out_h, out_w = out_img.shape[:2]
        return derived_path, derived_key, sha256_bytes(png_bytes), int(out_w), int(out_h)

    def execute_run(self, run_id: uuid.UUID) -> None:
        """Execute or resume a durable OCRRun page-by-page without losing progress."""
        with self.session_factory() as db:
            ocr_run = db.get(OCRRun, run_id)
            if ocr_run is None:
                return
            book = db.get(Book, ocr_run.book_id)
            job = db.get(ProcessingJob, ocr_run.processing_job_id) if ocr_run.processing_job_id else None
            if book is None:
                return

            cfg = dict(ocr_run.config or {})
            canonical_engine = str(cfg["engine"])
            start_page = int(cfg["start_page"])
            end_page = int(cfg["end_page"])
            render_dpi = int(cfg.get("render_dpi") if cfg.get("render_dpi") is not None else 300)
            preprocessing_profile = str(cfg.get("preprocessing_profile") or "none")
            tesseract_psm = int(cfg.get("tesseract_psm") if cfg.get("tesseract_psm") is not None else 6)
            include_digital = bool(cfg.get("include_digital_text_pages", False))
            run_phase = str(cfg.get("run_phase") or "")
            apply_calibration = bool(cfg.get("apply_calibration_corrections", False))

            if run_id in self._cancelled_runs:
                ocr_run.status = "partial"
                ocr_run.error_summary = "Cancelled by user; ready to resume."
                if job is not None:
                    job.status = "partial"
                db.commit()
                return

            target_pages = list(
                db.scalars(
                    select(BookPage)
                    .where(
                        BookPage.book_id == book.id,
                        BookPage.page_number >= start_page,
                        BookPage.page_number <= end_page,
                    )
                    .order_by(BookPage.page_number)
                ).all()
            )
            if not include_digital:
                target_pages = [p for p in target_pages if p.page_kind != "digital_text"]

            now = datetime.now(timezone.utc)
            ocr_run.status = "running"
            if ocr_run.started_at is None:
                ocr_run.started_at = now
            if job is not None:
                job.status = "running"
                if job.started_at is None:
                    job.started_at = now
                job.progress_total = len(target_pages)
            db.commit()

            try:
                provider = self.get_provider(
                    canonical_engine,
                    tesseract_psm=tesseract_psm,
                )
            except Exception as exc:
                ocr_run.status = "failed"
                ocr_run.completed_at = datetime.now(timezone.utc)
                ocr_run.error_summary = f"{type(exc).__name__}: {exc}"
                if job is not None:
                    job.status = "failed"
                    job.completed_at = ocr_run.completed_at
                    job.error_details = {"init_error": ocr_run.error_summary}
                db.commit()
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "Failed to initialize OCR provider in backend job",
                    run_id=str(ocr_run.id),
                    book_id=str(book.id),
                    engine=canonical_engine,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                return

            completed_pages = 0
            failed_errors: list[dict[str, Any]] = []
            was_cancelled = False
            engine_dir = "paddle" if canonical_engine == "paddle_ppocrv5_te" else "tesseract"
            open_pdf_doc: pymupdf.Document | None = None

            # Preload all already-completed page IDs in one query (eliminates resume N+1 commits).
            completed_page_ids = set(
                db.scalars(
                    select(OCRBlock.book_page_id)
                    .where(OCRBlock.ocr_run_id == ocr_run.id)
                    .distinct()
                ).all()
            )
            ocr_page_dir = self.storage.workspace_root / "ocr" / str(book.id) / str(ocr_run.id) / engine_dir
            existing_json_names = (
                {e.name for e in ocr_page_dir.iterdir() if e.is_file()} if ocr_page_dir.is_dir() else set()
            )
            pending_pages: list[BookPage] = []
            for p in target_pages:
                p_json_name = f"page-{p.page_number:04d}.json"
                if p.id in completed_page_ids or p_json_name in existing_json_names:
                    completed_pages += 1
                else:
                    pending_pages.append(p)
            if completed_pages > 0 and job is not None:
                job.progress_current = completed_pages
                db.commit()

            try:
                for page in pending_pages:
                    if run_id in self._cancelled_runs:
                        was_cancelled = True
                        break

                    page_json_key = f"ocr/{book.id}/{ocr_run.id}/{engine_dir}/page-{page.page_number:04d}.json"

                    try:
                        needs_custom_render = not (
                            page.image_storage_key
                            and page.render_dpi == render_dpi
                            and self.storage.exists(page.image_storage_key)
                        )
                        if needs_custom_render and open_pdf_doc is None and self.storage.exists(book.source_storage_key):
                            open_pdf_doc = pymupdf.open(self.storage.resolve_key(book.source_storage_key))

                        img_path, img_key, img_sha, img_w, img_h = self._ensure_page_image_path(
                            book=book,
                            page=page,
                            requested_dpi=render_dpi,
                            open_pdf_doc=open_pdf_doc,
                        )
                        img_path, img_key, img_sha, img_w, img_h = self._apply_preprocessing_profile(
                            img_path=img_path,
                            img_key=img_key,
                            img_sha=img_sha,
                            img_w=img_w,
                            img_h=img_h,
                            book_id=book.id,
                            page_number=page.page_number,
                            render_dpi=render_dpi,
                            profile=preprocessing_profile,
                        )
                        log_event(
                            LOGGER,
                            logging.INFO,
                            "Starting OCR page in backend job",
                            run_id=str(ocr_run.id),
                            book_id=str(book.id),
                            page_number=page.page_number,
                            engine=canonical_engine,
                            preprocessing_profile=preprocessing_profile,
                            render_dpi=render_dpi,
                            width_px=img_w,
                            height_px=img_h,
                            rss_mb=_peak_rss_mb(),
                        )
                        recognition = provider.recognize(img_path)

                        # Abort cleanly without recreating files/rows if run was cancelled or book deleted mid-page.
                        if run_id in self._cancelled_runs or db.get(Book, book.id) is None:
                            was_cancelled = True
                            break

                        raw_payload = recognition["raw_payload"]
                        if provider.engine_name == "paddleocr":
                            raw_key = f"ocr/{book.id}/{ocr_run.id}/{engine_dir}/raw/page-{page.page_number:04d}.raw.json"
                            self.storage.write_json(raw_key, raw_payload)
                        else:
                            raw_txt_key = f"ocr/{book.id}/{ocr_run.id}/{engine_dir}/raw/page-{page.page_number:04d}.raw.txt"
                            raw_key = f"ocr/{book.id}/{ocr_run.id}/{engine_dir}/raw/page-{page.page_number:04d}.raw.tsv"
                            self.storage.write_text(raw_txt_key, str(raw_payload.get("txt", "")))
                            self.storage.write_text(raw_key, str(raw_payload.get("tsv", "")))

                        structured = build_page_ocr_record(
                            book_id=str(book.id),
                            page_number=page.page_number,
                            source_pdf_sha256=book.source_sha256,
                            render_dpi=render_dpi,
                            image_path=img_key,
                            image_sha256=img_sha,
                            recognition_result=recognition,
                            raw_result_path=raw_key,
                        )
                        self.storage.write_json(page_json_key, structured)

                        created_blocks: list[OCRBlock] = []
                        for blk in recognition["blocks"]:
                            raw_text = str(blk["text"])
                            blk_row = OCRBlock(
                                ocr_run_id=ocr_run.id,
                                book_page_id=page.id,
                                block_index=int(blk["block_index"]),
                                block_type=str(blk.get("block_type", "text_line")),
                                raw_text=raw_text,
                                normalized_text=normalize_nfc(raw_text),
                                confidence=blk.get("confidence"),
                                polygon=blk.get("polygon"),
                                reading_order=blk.get("reading_order"),
                                raw_engine_payload=blk,
                            )
                            db.add(blk_row)
                            created_blocks.append(blk_row)

                        auto_applied_count = 0
                        if apply_calibration and created_blocks:
                            db.flush()
                            from src.services.calibration_service import (
                                apply_learned_corrections_to_page_blocks,
                            )

                            auto_applied_count = apply_learned_corrections_to_page_blocks(
                                db=db,
                                book=book,
                                page=page,
                                blocks=created_blocks,
                                lexicon_path=self.settings.lexicon_path,
                            )

                        completed_pages += 1
                        if job is not None:
                            job.progress_current = completed_pages
                        db.commit()
                        log_event(
                            LOGGER,
                            logging.INFO,
                            "Completed OCR page in backend job",
                            run_id=str(ocr_run.id),
                            book_id=str(book.id),
                            page_number=page.page_number,
                            engine=canonical_engine,
                            block_count=len(recognition["blocks"]),
                            auto_applied_blocks=auto_applied_count,
                            elapsed_ms=recognition.get("elapsed_ms"),
                            rss_mb=_peak_rss_mb(),
                        )
                    except Exception as exc:
                        db.rollback()
                        err_entry = {
                            "page_number": page.page_number,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        }
                        failed_errors.append(err_entry)
                        log_event(
                            LOGGER,
                            logging.ERROR,
                            "Failed OCR page in backend job",
                            run_id=str(ocr_run.id),
                            book_id=str(book.id),
                            page_number=page.page_number,
                            error_type=type(exc).__name__,
                            error_message=str(exc),
                        )
            finally:
                if open_pdf_doc is not None:
                    open_pdf_doc.close()

            finished_at = datetime.now(timezone.utc)
            if was_cancelled or run_id in self._cancelled_runs:
                final_status = "partial"
            elif not failed_errors:
                final_status = "completed"
            elif completed_pages > 0:
                final_status = "partial"
            else:
                final_status = "failed"

            ocr_run = db.get(OCRRun, run_id)
            job = db.get(ProcessingJob, ocr_run.processing_job_id) if ocr_run and ocr_run.processing_job_id else None
            if ocr_run is not None:
                ocr_run.status = final_status
                ocr_run.completed_at = finished_at
                if was_cancelled or run_id in self._cancelled_runs:
                    ocr_run.error_summary = "Cancelled by user; ready to resume."
                else:
                    ocr_run.error_summary = (
                        f"{len(failed_errors)} page(s) failed" if failed_errors else None
                    )
            if job is not None:
                job.status = final_status
                job.progress_current = completed_pages
                job.completed_at = finished_at
                job.error_details = {"failed_pages": failed_errors}

            # Advance book processing_state cleanly when a calibration or remaining-pages run finishes.
            book_row = db.get(Book, ocr_run.book_id) if ocr_run is not None else None
            if book_row is not None and final_status in ("completed", "partial"):
                if run_phase == "calibration":
                    book_row.processing_state = "calibration_review"
                elif run_phase == "remaining":
                    book_row.processing_state = "review_in_progress"
                elif book_row.processing_state in ("uploaded", "calibration_pending"):
                    book_row.processing_state = "review_in_progress"
            db.commit()


def create_or_reuse_ocr_runs(
    *,
    db: Session,
    executor: OCRJobExecutor,
    settings: AppSettings,
    book_id: uuid.UUID,
    engines: list[str],
    start_page: int | None,
    end_page: int | None,
    render_dpi: int,
    preprocessing_profile: str,
    tesseract_psm: int,
    include_digital_text_pages: bool,
    force_rerun: bool,
    run_phase: str | None = None,
    apply_calibration_corrections: bool = False,
) -> dict[str, Any]:
    """Create durable ProcessingJob + OCRRun rows or reuse matching completed runs."""
    if preprocessing_profile not in ALLOWED_PREPROCESSING_PROFILES:
        raise AppError(
            "UNSUPPORTED_PREPROCESSING",
            f"Unsupported preprocessing_profile={preprocessing_profile!r}. Allowed: {sorted(ALLOWED_PREPROCESSING_PROFILES)}.",
            status_code=400,
        )

    book = db.get(Book, book_id)
    if book is None:
        raise AppError("BOOK_NOT_FOUND", f"Book {book_id} not found.", status_code=404)

    s_page = 1 if start_page is None else int(start_page)
    e_page = book.page_count if end_page is None else int(end_page)
    if s_page < 1 or e_page > book.page_count or s_page > e_page:
        raise AppError(
            "INVALID_PAGE_RANGE",
            f"Invalid page range {s_page}..{e_page} for book with {book.page_count} pages.",
            status_code=400,
        )

    pages = list(
        db.scalars(
            select(BookPage)
            .where(
                BookPage.book_id == book.id,
                BookPage.page_number >= s_page,
                BookPage.page_number <= e_page,
            )
            .order_by(BookPage.page_number)
        ).all()
    )
    target_pages = pages if include_digital_text_pages else [p for p in pages if p.page_kind != "digital_text"]
    if not target_pages:
        raise AppError(
            "NO_SCANNED_PAGES_IN_RANGE",
            "No scanned or mixed pages found in the selected page range. Digital-text pages are handled separately.",
            status_code=400,
            details={"start_page": s_page, "end_page": e_page},
        )

    canonical_engines = []
    for raw_eng in engines:
        canon = canonicalize_engine_name(raw_eng)
        if canon not in canonical_engines:
            canonical_engines.append(canon)

    created_run_ids: list[uuid.UUID] = []
    all_run_ids: list[uuid.UUID] = []
    reused_all = True
    primary_job_id: uuid.UUID | None = None

    for canon in canonical_engines:
        idem_key = compute_run_idempotency_key(
            book_id=book.id,
            canonical_engine=canon,
            start_page=s_page,
            end_page=e_page,
            render_dpi=render_dpi,
            preprocessing_profile=preprocessing_profile,
            tesseract_psm=tesseract_psm,
            include_digital_text_pages=include_digital_text_pages,
            apply_calibration_corrections=apply_calibration_corrections,
        )
        active_existing = db.scalars(
            select(OCRRun)
            .where(
                OCRRun.book_id == book.id,
                OCRRun.idempotency_key == idem_key,
                OCRRun.status.in_(("running", "queued")),
            )
            .order_by(OCRRun.created_at.desc())
        ).first()
        if active_existing is not None:
            all_run_ids.append(active_existing.id)
            if primary_job_id is None and active_existing.processing_job_id is not None:
                primary_job_id = active_existing.processing_job_id
            reused_all = False
            continue

        if not force_rerun:
            existing = db.scalars(
                select(OCRRun)
                .where(OCRRun.book_id == book.id, OCRRun.idempotency_key == idem_key)
                .order_by(OCRRun.created_at.desc())
            ).first()
            if existing is not None and existing.status == "completed":
                all_run_ids.append(existing.id)
                if primary_job_id is None and existing.processing_job_id is not None:
                    primary_job_id = existing.processing_job_id
                continue
            if existing is not None and existing.status in ("partial", "failed"):
                reused_all = False
                existing.status = "queued"
                job = db.get(ProcessingJob, existing.processing_job_id) if existing.processing_job_id else None
                if job is not None:
                    job.status = "queued"
                    primary_job_id = job.id
                db.commit()
                all_run_ids.append(existing.id)
                created_run_ids.append(existing.id)
                continue

        reused_all = False
        provider = executor.get_provider(canon, tesseract_psm=tesseract_psm)
        model_reg = get_or_create_model_registry(db, provider)

        job = ProcessingJob(
            book_id=book.id,
            job_type=f"ocr:{canon}",
            status="queued",
            progress_current=0,
            progress_total=len(target_pages),
            error_details={},
        )
        db.add(job)
        db.flush()
        if primary_job_id is None:
            primary_job_id = job.id

        ocr_run = OCRRun(
            book_id=book.id,
            model_registry_id=model_reg.id,
            processing_job_id=job.id,
            status="queued",
            idempotency_key=idem_key,
            config={
                "engine": canon,
                "start_page": s_page,
                "end_page": e_page,
                "render_dpi": render_dpi,
                "preprocessing_profile": preprocessing_profile,
                "tesseract_psm": tesseract_psm if canon == "tesseract_tel_best" else None,
                "include_digital_text_pages": include_digital_text_pages,
                "run_phase": run_phase,
                "apply_calibration_corrections": bool(apply_calibration_corrections),
            },
        )
        db.add(ocr_run)
        db.commit()
        db.refresh(ocr_run)
        all_run_ids.append(ocr_run.id)
        created_run_ids.append(ocr_run.id)

    if created_run_ids:
        executor.submit_runs(created_run_ids)

    first_run = db.get(OCRRun, all_run_ids[0])
    return {
        "ocr_run_id": all_run_ids[0],
        "ocr_run_ids": all_run_ids,
        "job_id": primary_job_id or (first_run.processing_job_id if first_run else uuid.uuid4()),
        "status": first_run.status if first_run else "queued",
        "pages_total": len(target_pages),
        "reused_existing": reused_all,
    }


def resume_ocr_run(
    *,
    db: Session,
    executor: OCRJobExecutor,
    run_id: uuid.UUID,
) -> OCRRun:
    """Resume a partial or failed OCR run from the last completed page."""
    ocr_run = db.get(OCRRun, run_id)
    if ocr_run is None:
        raise AppError("OCR_RUN_NOT_FOUND", f"OCR run {run_id} not found.", status_code=404)
    if ocr_run.status in ("completed", "running", "queued"):
        return ocr_run
    ocr_run.status = "queued"
    ocr_run.error_summary = None
    if ocr_run.processing_job_id:
        job = db.get(ProcessingJob, ocr_run.processing_job_id)
        if job is not None:
            job.status = "queued"
    db.commit()
    executor.submit_runs([ocr_run.id])
    db.refresh(ocr_run)
    return ocr_run


def cancel_ocr_run(
    *,
    db: Session,
    executor: OCRJobExecutor,
    run_id: uuid.UUID,
) -> OCRRun:
    """Cancel a queued or running OCR run, preserving completed pages as 'partial'."""
    ocr_run = db.get(OCRRun, run_id)
    if ocr_run is None:
        raise AppError("OCR_RUN_NOT_FOUND", f"OCR run {run_id} not found.", status_code=404)
    if ocr_run.status in ("completed", "failed"):
        return ocr_run
    executor.cancel_run(ocr_run.id)
    ocr_run.status = "partial"
    ocr_run.error_summary = "Cancelled by user; ready to resume."
    if ocr_run.processing_job_id:
        job = db.get(ProcessingJob, ocr_run.processing_job_id)
        if job is not None:
            job.status = "partial"
    db.commit()
    db.refresh(ocr_run)
    return ocr_run
