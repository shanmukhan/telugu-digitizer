"""Structured logging setup that avoids printing book contents by default."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class _StructuredFormatter(logging.Formatter):
    """Format log records as single-line structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "structured_fields", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
) -> logging.Logger:
    """Configure logger for structured stderr output and optional rotating disk log."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger("telugu_digitizer")
    root.setLevel(numeric_level)
    formatter = _StructuredFormatter()
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(formatter)

    if log_file is not None:
        resolved = log_file.resolve()
        has_file_handler = any(
            isinstance(h, RotatingFileHandler) and Path(h.baseFilename).resolve() == resolved
            for h in root.handlers
        )
        if not has_file_handler:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                resolved,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

    root.propagate = False
    return root


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    **fields: Any,
) -> None:
    """Emit a structured log record with metadata fields (never raw book text)."""
    logger.log(level, message, extra={"structured_fields": fields})
