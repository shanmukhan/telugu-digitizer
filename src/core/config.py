"""Application configuration settings for Phase 2 backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(raw: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return default
    items = tuple(item.strip() for item in raw.split(",") if item.strip())
    return items or default


@dataclass(frozen=True)
class AppSettings:
    """Runtime settings with localhost-first defaults."""

    database_url: str
    workspace_dir: Path
    tessdata_dir: Path
    tesseract_cmd: str | None
    api_host: str
    api_port: int
    max_upload_mb: int
    max_pdf_pages: int
    default_render_dpi: int
    paddle_device: str
    cors_allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    proxy_headers: bool = False
    forwarded_allow_ips: str = "127.0.0.1"
    auth_username: str | None = None
    auth_password: str | None = None
    enable_paddle_ocr: bool = True

    @classmethod
    def from_env(cls) -> "AppSettings":
        repo_root = Path(__file__).resolve().parents[2]
        default_db = (
            "postgresql+psycopg://telugu_digitizer:telugu_digitizer@127.0.0.1:5432/telugu_digitizer"
        )
        return cls(
            database_url=os.environ.get("DATABASE_URL", default_db),
            workspace_dir=Path(os.environ.get("WORKSPACE_DIR", str(repo_root / "workspace"))).resolve(),
            tessdata_dir=Path(
                os.environ.get("TESSDATA_DIR", str(repo_root / "models" / "tesseract" / "tessdata"))
            ).resolve(),
            tesseract_cmd=os.environ.get("TESSERACT_CMD") or None,
            api_host=os.environ.get("API_HOST", "127.0.0.1"),
            api_port=int(os.environ.get("API_PORT", "8000")),
            max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "200")),
            max_pdf_pages=int(os.environ.get("MAX_PDF_PAGES", "1000")),
            default_render_dpi=int(os.environ.get("DEFAULT_RENDER_DPI", "300")),
            paddle_device=os.environ.get("PADDLE_DEVICE", "cpu"),
            cors_allowed_origins=_parse_csv(
                os.environ.get("CORS_ALLOWED_ORIGINS"),
                ("http://127.0.0.1:5173", "http://localhost:5173"),
            ),
            proxy_headers=_parse_bool(os.environ.get("PROXY_HEADERS"), False),
            forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
            auth_username=os.environ.get("APP_AUTH_USERNAME") or None,
            auth_password=os.environ.get("APP_AUTH_PASSWORD") or None,
            enable_paddle_ocr=_parse_bool(os.environ.get("ENABLE_PADDLE_OCR"), True),
        )
