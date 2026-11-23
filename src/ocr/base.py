"""Base OCRProvider interface and structured page result schema."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class OCRProvider(ABC):
    """Common interface for Phase 1 OCR engine adapters."""

    engine_name: str = "unknown"

    @abstractmethod
    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        """Run OCR on one image path and return structured blocks plus raw metadata."""
        raise NotImplementedError

    def provider_metadata(self) -> dict[str, Any]:
        """Return static engine/model configuration and checksum metadata."""
        return {"engine": self.engine_name}


def build_page_ocr_record(
    *,
    book_id: str,
    page_number: int,
    source_pdf_sha256: str,
    render_dpi: int,
    image_path: str,
    image_sha256: str,
    recognition_result: dict[str, Any],
    raw_result_path: str,
) -> dict[str, Any]:
    """Assemble a Phase 1 structured per-page OCR output record."""
    return {
        "book_id": book_id,
        "page_number": page_number,
        "source_pdf_sha256": source_pdf_sha256,
        "engine": recognition_result["engine"],
        "engine_version": recognition_result["engine_version"],
        "model_id": recognition_result["model_id"],
        "config": recognition_result["config"],
        "render_dpi": render_dpi,
        "image_path": image_path,
        "image_sha256": image_sha256,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": recognition_result["elapsed_ms"],
        "cold_start_ms": recognition_result.get("cold_start_ms"),
        "text": recognition_result["text"],
        "blocks": recognition_result["blocks"],
        "raw_result_path": raw_result_path,
    }
