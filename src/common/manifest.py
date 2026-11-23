"""Dataset manifest schemas and runtime environment provenance collection."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.common.io import atomic_write_json, sanitize_id, sha256_file

PHASE1_PACKAGES = [
    "paddlepaddle",
    "paddleocr",
    "paddlex",
    "pymupdf",
    "opencv-python-headless",
    "pillow",
    "numpy",
    "regex",
    "pandas",
    "jiwer",
    "pytest",
]


@dataclass
class PageManifestEntry:
    """Single page entry inside a Phase 1 dataset/book manifest."""

    book_id: str
    page_number: int
    pdf_page_index: int
    source_pdf_path: str
    source_pdf_sha256: str
    image_path: str
    image_sha256: str | None
    render_dpi: int
    page_kind: str
    page_width_pt: float
    page_height_pt: float
    width_px: int | None
    height_px: int | None
    extracted_text_char_count: int = 0
    image_coverage_ratio: float = 0.0
    split: str = "unspecified"
    page_quality: str = "unspecified"
    layout_type: str = "unspecified"
    gold_path: str | None = None
    status: str = "rendered"
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PageManifestEntry":
        return cls(
            book_id=sanitize_id(str(raw["book_id"])),
            page_number=int(raw["page_number"]),
            pdf_page_index=int(raw.get("pdf_page_index", int(raw["page_number"]) - 1)),
            source_pdf_path=str(raw.get("source_pdf_path", "")),
            source_pdf_sha256=str(raw.get("source_pdf_sha256", "")),
            image_path=str(raw["image_path"]),
            image_sha256=raw.get("image_sha256"),
            render_dpi=int(raw.get("render_dpi", 300)),
            page_kind=str(raw.get("page_kind", "scanned_image")),
            page_width_pt=float(raw.get("page_width_pt", 0.0)),
            page_height_pt=float(raw.get("page_height_pt", 0.0)),
            width_px=int(raw["width_px"]) if raw.get("width_px") is not None else None,
            height_px=int(raw["height_px"]) if raw.get("height_px") is not None else None,
            extracted_text_char_count=int(raw.get("extracted_text_char_count", 0)),
            image_coverage_ratio=float(raw.get("image_coverage_ratio", 0.0)),
            split=str(raw.get("split", "unspecified")),
            page_quality=str(raw.get("page_quality", "unspecified")),
            layout_type=str(raw.get("layout_type", "unspecified")),
            gold_path=raw.get("gold_path"),
            status=str(raw.get("status", "rendered")),
            error_type=raw.get("error_type"),
            error_message=raw.get("error_message"),
        )


@dataclass
class DatasetManifest:
    """Container for rendered pages, split metadata, and gold transcription paths."""

    dataset_version: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    annotation_policy: str = "docs/phase-1-annotation-guide.md"
    pages: list[PageManifestEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version,
            "created_at": self.created_at,
            "annotation_policy": self.annotation_policy,
            "page_count": len(self.pages),
            "pages": [page.to_dict() for page in self.pages],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DatasetManifest":
        return cls(
            dataset_version=str(raw.get("dataset_version", "v1")),
            created_at=str(raw.get("created_at", datetime.now(timezone.utc).isoformat())),
            annotation_policy=str(raw.get("annotation_policy", "docs/phase-1-annotation-guide.md")),
            pages=[PageManifestEntry.from_dict(item) for item in raw.get("pages", [])],
        )


def load_manifest(path: Path) -> DatasetManifest:
    """Load and validate a DatasetManifest JSON file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "pages" not in data:
        raise ValueError(f"Manifest {path} must be a JSON object with a 'pages' list.")
    return DatasetManifest.from_dict(data)


def save_manifest(manifest: DatasetManifest, path: Path) -> Path:
    """Atomically write a DatasetManifest JSON file."""
    return atomic_write_json(path, manifest.to_dict())


def _get_memory_gb() -> float | None:
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
            total_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            return round(total_bytes / (1024 ** 3), 2)
    except (OSError, ValueError):
        return None
    return None


def resolve_tesseract_command(explicit_cmd: str | None = None) -> str:
    """Resolve the tesseract binary path from explicit path, PATH, or local .venv/.tools."""
    if explicit_cmd:
        cmd_path = Path(explicit_cmd)
        if cmd_path.is_file():
            return str(cmd_path)
        found = shutil.which(explicit_cmd)
        if found:
            return found
        raise FileNotFoundError(f"Configured tesseract binary not found: {explicit_cmd}")

    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        shutil.which("tesseract"),
        str(repo_root / ".venv" / "bin" / "tesseract"),
        str(repo_root / ".tools" / "tesseract" / "bin" / "tesseract"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise FileNotFoundError(
        "tesseract binary not found in PATH, .venv/bin/tesseract, or .tools/tesseract/bin/tesseract."
    )


def collect_provenance(
    tessdata_dir: Path | None = None,
    tesseract_cmd: str | None = None,
    paddle_models_dir: Path | None = None,
) -> dict[str, Any]:
    """Collect exact runtime, package, and OCR model provenance metadata."""
    packages: dict[str, str | None] = {}
    for pkg in PHASE1_PACKAGES:
        try:
            packages[pkg] = importlib.metadata.version(pkg)
        except importlib.metadata.PackageNotFoundError:
            packages[pkg] = None

    tesseract_info: dict[str, Any] = {"available": False}
    try:
        tess_bin = resolve_tesseract_command(tesseract_cmd)
        proc = subprocess.run([tess_bin, "--version"], capture_output=True, check=True)
        first_line = proc.stdout.decode("utf-8", errors="replace").splitlines()[0]
        tesseract_info["available"] = True
        tesseract_info["command"] = tess_bin
        tesseract_info["version_line"] = first_line
    except Exception as exc:
        tesseract_info["error"] = f"{type(exc).__name__}: {exc}"

    if tessdata_dir is not None:
        traineddata = tessdata_dir / "tel.traineddata"
        tesseract_info["tessdata_dir"] = str(tessdata_dir)
        if traineddata.is_file():
            tesseract_info["tel_traineddata_sha256"] = sha256_file(traineddata)
            tesseract_info["tel_traineddata_bytes"] = traineddata.stat().st_size

    paddle_models: dict[str, Any] = {}
    models_root = paddle_models_dir or (Path.home() / ".paddlex" / "official_models")
    for model_name in ("PP-OCRv5_server_det", "te_PP-OCRv5_mobile_rec"):
        model_dir = models_root / model_name
        params_file = model_dir / "inference.pdiparams"
        if params_file.is_file():
            paddle_models[model_name] = {
                "dir": str(model_dir),
                "inference_pdiparams_sha256": sha256_file(params_file),
                "inference_pdiparams_bytes": params_file.stat().st_size,
            }

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "memory_gb": _get_memory_gb(),
        "packages": packages,
        "tesseract": tesseract_info,
        "paddle_models": paddle_models,
    }
