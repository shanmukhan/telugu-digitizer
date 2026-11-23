"""Filesystem safety, hashing, and atomic output helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def sanitize_id(raw_id: str) -> str:
    """Validate and return a filesystem-safe identifier (book ID, run ID, etc.)."""
    cleaned = raw_id.strip()
    if not cleaned or ".." in cleaned or not _SAFE_ID_PATTERN.match(cleaned):
        raise ValueError(
            f"Invalid identifier {raw_id!r}: must match ^[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}$ without '..'."
        )
    return cleaned


def validate_within_workspace(path: Path, workspace_root: Path) -> Path:
    """Ensure a target path resolves inside the configured workspace directory."""
    resolved_root = workspace_root.resolve()
    resolved_path = path.resolve()
    if resolved_path != resolved_root and not resolved_path.is_relative_to(resolved_root):
        raise ValueError(
            f"Path {resolved_path} escapes configured workspace root {resolved_root}."
        )
    return resolved_path


def sha256_bytes(data: bytes) -> str:
    """Compute hex-encoded SHA-256 digest of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute hex-encoded SHA-256 digest of a file using streaming reads."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> Path:
    """Write bytes atomically using a temporary file in the target directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return path


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    """Write UTF-8 text atomically without altering line endings or Unicode forms."""
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: Path, payload: Any) -> Path:
    """Serialize JSON with UTF-8 preservation and write atomically."""
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return atomic_write_text(path, serialized, encoding="utf-8")
