"""PaddleOCR 3.x PP-OCRv5 Telugu adapter."""

from __future__ import annotations

import functools
import importlib.metadata
import os
import platform
import time
from pathlib import Path
from typing import Any

from src.common.io import sha256_file
from src.ocr.base import OCRProvider
from src.ocr.layout import order_ocr_blocks_geometrically


@functools.lru_cache(maxsize=16)
def _cached_file_sha256(path_str: str, mtime_ns: int, size: int) -> str:
    """Cache SHA-256 checksums of model weight files keyed by path, mtime, and size."""
    _ = (mtime_ns, size)
    return sha256_file(Path(path_str))


@functools.lru_cache(maxsize=1)
def _cached_package_versions() -> dict[str, str | None]:
    """Resolve paddleocr/paddlex/paddlepaddle package versions once per process."""
    versions: dict[str, str | None] = {}
    for pkg in ("paddleocr", "paddlex", "paddlepaddle"):
        try:
            versions[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            versions[pkg] = None
    return versions


def _to_json_compatible(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [_to_json_compatible(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _to_json_compatible(v) for k, v in value.items()}
    return value


class PaddleOCRProvider(OCRProvider):
    """PaddleOCR 3.x provider pinned explicitly to Telugu PP-OCRv5."""

    engine_name = "paddleocr"

    def __init__(
        self,
        lang: str = "te",
        ocr_version: str = "PP-OCRv5",
        device: str = "cpu",
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_textline_orientation: bool = False,
        disable_model_source_check: bool = True,
        models_dir: Path | None = None,
        cpu_threads: int | None = None,
        text_det_limit_side_len: int | None = None,
        text_det_limit_type: str | None = None,
    ) -> None:
        if lang != "te":
            raise ValueError(f"Phase 1 requires Telugu lang='te', got {lang!r}.")
        if ocr_version != "PP-OCRv5":
            raise ValueError(
                f"Phase 1 requires explicit ocr_version='PP-OCRv5' for Telugu support, got {ocr_version!r}."
            )

        is_linux_arm64 = platform.system() == "Linux" and platform.machine().lower() in {
            "aarch64",
            "arm64",
        }
        if cpu_threads is None:
            env_threads = os.environ.get("PADDLE_CPU_THREADS") or os.environ.get(
                "PADDLE_PDX_CPU_NUM_THREADS"
            )
            if env_threads and env_threads.isdigit():
                cpu_threads = max(1, int(env_threads))
            elif is_linux_arm64:
                # OpenBLAS-backed PaddlePaddle on ARM64 segfaults with PaddleX's default 10 threads.
                cpu_threads = 1

        if text_det_limit_side_len is None:
            env_limit = os.environ.get("PADDLE_DET_LIMIT_SIDE_LEN")
            if env_limit and env_limit.isdigit():
                text_det_limit_side_len = max(320, int(env_limit))
            elif is_linux_arm64:
                text_det_limit_side_len = 1280
            else:
                text_det_limit_side_len = 1920

        if text_det_limit_type is None:
            text_det_limit_type = "max"

        self.lang = lang
        self.ocr_version = ocr_version
        self.device = device
        self.use_doc_orientation_classify = use_doc_orientation_classify
        self.use_doc_unwarping = use_doc_unwarping
        self.use_textline_orientation = use_textline_orientation
        self.disable_model_source_check = disable_model_source_check
        self.models_dir = models_dir or (Path.home() / ".paddlex" / "official_models")
        self.cpu_threads = cpu_threads
        self.text_det_limit_side_len = text_det_limit_side_len
        self.text_det_limit_type = text_det_limit_type

        self._ocr: Any = None
        self._cold_start_ms: float | None = None
        self._det_model_name: str | None = None
        self._rec_model_name: str | None = None

    def ensure_loaded(self) -> float:
        """Initialize the PaddleOCR pipeline once and record cold-start latency."""
        if self._ocr is not None:
            return 0.0

        if self.disable_model_source_check and "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK" not in os.environ:
            os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        if self.cpu_threads is not None and "PADDLE_PDX_CPU_NUM_THREADS" not in os.environ:
            os.environ["PADDLE_PDX_CPU_NUM_THREADS"] = str(self.cpu_threads)

        from paddleocr import PaddleOCR

        init_kwargs: dict[str, Any] = {
            "lang": self.lang,
            "ocr_version": self.ocr_version,
            "device": self.device,
            "use_doc_orientation_classify": self.use_doc_orientation_classify,
            "use_doc_unwarping": self.use_doc_unwarping,
            "use_textline_orientation": self.use_textline_orientation,
            "text_det_limit_side_len": self.text_det_limit_side_len,
            "text_det_limit_type": self.text_det_limit_type,
        }
        if self.cpu_threads is not None:
            init_kwargs["cpu_threads"] = self.cpu_threads

        t0 = time.perf_counter()
        ocr = PaddleOCR(**init_kwargs)
        self._cold_start_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        params = getattr(ocr, "_params", {}) or {}
        det_name = str(params.get("text_detection_model_name") or "")
        rec_name = str(params.get("text_recognition_model_name") or "")

        if not rec_name.startswith("te_"):
            raise RuntimeError(
                f"Model selection guard failed: expected Telugu recognition model ('te_*'), got {rec_name!r}."
            )
        if not det_name:
            raise RuntimeError("Model selection guard failed: text_detection_model_name is empty.")

        self._det_model_name = det_name
        self._rec_model_name = rec_name
        self._ocr = ocr
        return self._cold_start_ms

    def _model_checksums(self) -> dict[str, str]:
        checksums: dict[str, str] = {}
        for model_name in filter(None, (self._det_model_name, self._rec_model_name)):
            params_path = self.models_dir / model_name / "inference.pdiparams"
            if params_path.is_file():
                st = params_path.stat()
                checksums[model_name] = _cached_file_sha256(
                    str(params_path.resolve()),
                    st.st_mtime_ns,
                    st.st_size,
                )
        return checksums

    def _package_versions(self) -> dict[str, str | None]:
        return dict(_cached_package_versions())

    def provider_metadata(self) -> dict[str, Any]:
        det_name = self._det_model_name or "PP-OCRv5_server_det"
        rec_name = self._rec_model_name or "te_PP-OCRv5_mobile_rec"
        versions = self._package_versions()
        return {
            "engine": self.engine_name,
            "engine_version": versions.get("paddleocr") or "unknown",
            "framework_version": versions.get("paddlepaddle"),
            "paddlex_version": versions.get("paddlex"),
            "model_id": f"{det_name}+{rec_name}",
            "model_checksums": self._model_checksums(),
            "cold_start_ms": self._cold_start_ms,
            "config": {
                "lang": self.lang,
                "ocr_version": self.ocr_version,
                "device": self.device,
                "use_doc_orientation_classify": self.use_doc_orientation_classify,
                "use_doc_unwarping": self.use_doc_unwarping,
                "use_textline_orientation": self.use_textline_orientation,
                "det_model_name": det_name,
                "rec_model_name": rec_name,
            },
        }

    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        """Run PaddleOCR PP-OCRv5 Telugu prediction on one PNG image."""
        img = Path(image_path)
        if not img.is_file():
            raise FileNotFoundError(f"OCR input image not found: {img}")

        cold_ms = self.ensure_loaded()
        t0 = time.perf_counter()
        raw_results = list(self._ocr.predict(str(img)))
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        blocks: list[dict[str, Any]] = []
        raw_pages: list[dict[str, Any]] = []
        lines: list[str] = []

        for result in raw_results:
            result_json = _to_json_compatible(getattr(result, "json", {}))
            raw_pages.append(result_json)
            res_body = result_json.get("res", result_json) if isinstance(result_json, dict) else {}

            rec_texts = res_body.get("rec_texts") or []
            rec_scores = res_body.get("rec_scores") or []
            rec_polys = res_body.get("rec_polys") or res_body.get("dt_polys") or []
            rec_boxes = res_body.get("rec_boxes") or []

            for idx, text in enumerate(rec_texts):
                raw_text = str(text)
                confidence = float(rec_scores[idx]) if idx < len(rec_scores) and rec_scores[idx] is not None else None
                polygon = rec_polys[idx] if idx < len(rec_polys) else None
                bbox = rec_boxes[idx] if idx < len(rec_boxes) else None
                block_index = len(blocks)
                blocks.append(
                    {
                        "block_index": block_index,
                        "block_type": "text_line",
                        "text": raw_text,
                        "confidence": confidence,
                        "polygon": polygon,
                        "bbox": bbox,
                        "reading_order": block_index,
                    }
                )

        blocks = order_ocr_blocks_geometrically(blocks)
        lines = [str(b["text"]) for b in blocks]

        meta = self.provider_metadata()
        return {
            "engine": self.engine_name,
            "engine_version": meta["engine_version"],
            "model_id": meta["model_id"],
            "config": meta["config"],
            "elapsed_ms": elapsed_ms,
            "cold_start_ms": cold_ms if cold_ms > 0 else None,
            "text": "\n".join(lines),
            "blocks": blocks,
            "raw_payload": {
                "format": "paddleocr_json",
                "model_checksums": meta["model_checksums"],
                "results": raw_pages,
            },
        }
