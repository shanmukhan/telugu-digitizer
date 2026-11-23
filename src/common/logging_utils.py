"""Structured logging setup that avoids printing book contents by default."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
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


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configure root logger for structured Phase 1 CLI output."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger("telugu_digitizer")
    root.setLevel(numeric_level)
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_StructuredFormatter())
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(_StructuredFormatter())
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
