"""Local filesystem object storage abstraction keyed inside workspace/."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Protocol

from src.common.io import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    validate_within_workspace,
)


class StorageBackend(Protocol):
    """Storage interface keyed by internal relative storage keys."""

    def resolve_key(self, storage_key: str) -> Path: ...
    def write_bytes(self, storage_key: str, data: bytes, *, read_only: bool = False) -> Path: ...
    def write_json(self, storage_key: str, payload: Any) -> Path: ...
    def write_text(self, storage_key: str, text: str) -> Path: ...
    def read_bytes(self, storage_key: str) -> bytes: ...
    def exists(self, storage_key: str) -> bool: ...
    def delete_prefix(self, prefix_key: str) -> None: ...


class LocalFilesystemStorage:
    """Predictable local directory storage enforcing workspace root containment."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

    def resolve_key(self, storage_key: str) -> Path:
        cleaned = storage_key.lstrip("/")
        if not cleaned or ".." in Path(cleaned).parts:
            raise ValueError(f"Invalid storage key: {storage_key!r}")
        return validate_within_workspace(self.workspace_root / cleaned, self.workspace_root)

    def install_file(self, storage_key: str, src_path: Path, *, read_only: bool = False) -> Path:
        """Install an existing on-disk file into workspace atomically without full RAM buffering."""
        import tempfile

        target = self.resolve_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and read_only:
            os.chmod(target, 0o644)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        tmp_path = Path(tmp_name)
        try:
            with src_path.open("rb") as src, os.fdopen(fd, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(tmp_path, target)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        if read_only:
            os.chmod(target, 0o444)
        return target

    def write_bytes(self, storage_key: str, data: bytes, *, read_only: bool = False) -> Path:
        target = self.resolve_key(storage_key)
        if target.exists() and read_only:
            # Allow idempotent overwrite only when explicitly re-imported; normally skipped upstream.
            os.chmod(target, 0o644)
        atomic_write_bytes(target, data)
        if read_only:
            os.chmod(target, 0o444)
        return target

    def write_json(self, storage_key: str, payload: Any) -> Path:
        target = self.resolve_key(storage_key)
        return atomic_write_json(target, payload)

    def write_text(self, storage_key: str, text: str) -> Path:
        target = self.resolve_key(storage_key)
        return atomic_write_text(target, text, encoding="utf-8")

    def read_bytes(self, storage_key: str) -> bytes:
        target = self.resolve_key(storage_key)
        return target.read_bytes()

    def read_json(self, storage_key: str) -> Any:
        target = self.resolve_key(storage_key)
        return json.loads(target.read_text(encoding="utf-8"))

    def exists(self, storage_key: str) -> bool:
        target = self.resolve_key(storage_key)
        return target.is_file()

    def delete_prefix(self, prefix_key: str) -> None:
        target_dir = self.resolve_key(prefix_key)
        if not target_dir.exists():
            return
        if target_dir.is_file():
            os.chmod(target_dir, 0o644)
            target_dir.unlink()
            return
        for root, dirs, files in os.walk(target_dir):
            for d in dirs:
                os.chmod(Path(root) / d, 0o755)
            for f in files:
                os.chmod(Path(root) / f, 0o644)
        shutil.rmtree(target_dir, ignore_errors=False)
