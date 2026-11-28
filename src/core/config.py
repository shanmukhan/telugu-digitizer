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


def _parse_int(raw: str | None, default: int, *, minimum: int = 1) -> int:
    if raw is None or not raw.strip():
        return default
    try:
        return max(minimum, int(raw.strip()))
    except ValueError:
        return default


def is_loopback_host(host: str | None) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


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
    admin_username: str | None = None
    admin_password: str | None = None
    allow_guest_ocr: bool = True
    enable_paddle_ocr: bool = True
    lexicon_path: Path | None = None
    dictionary_db_path: Path | None = None
    enable_api_docs: bool | None = None
    rate_limit_enabled: bool | None = None
    rate_limit_auth_failures: int = 15
    rate_limit_uploads_per_10min: int = 12
    rate_limit_ocr_starts_per_10min: int = 30
    max_render_pixels: int = 25_000_000
    ocr_page_timeout_sec: int = 180
    isolate_ocr_worker: bool = True
    prewarm_lexicon: bool = True
    low_conf_threshold_tesseract: float = 75.0
    low_conf_threshold_paddle: float = 0.85

    @property
    def is_network_exposed(self) -> bool:
        return bool(self.proxy_headers or not is_loopback_host(self.api_host))

    @property
    def effective_api_docs_enabled(self) -> bool:
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return not self.is_network_exposed

    @property
    def effective_rate_limit_enabled(self) -> bool:
        if self.rate_limit_enabled is not None:
            return self.rate_limit_enabled
        return self.is_network_exposed

    @property
    def effective_admin_credentials(self) -> tuple[str, str] | None:
        if self.admin_username and self.admin_password:
            return (self.admin_username, self.admin_password)
        if self.auth_username and self.auth_password:
            return (self.auth_username, self.auth_password)
        return None

    @classmethod
    def from_env(cls) -> "AppSettings":
        repo_root = Path(__file__).resolve().parents[2]
        default_db = (
            "postgresql+psycopg://telugu_digitizer:telugu_digitizer@127.0.0.1:5432/telugu_digitizer"
        )
        default_lexicon = repo_root / "models" / "lexicon" / "telugu_lexicon.tsv.gz"
        default_dict_db = repo_root / "models" / "lexicon" / "telugu_dictionary.sqlite"
        raw_api_docs = os.environ.get("ENABLE_API_DOCS")
        raw_rate_limit = os.environ.get("RATE_LIMIT_ENABLED")
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
            admin_username=os.environ.get("APP_ADMIN_USERNAME") or None,
            admin_password=os.environ.get("APP_ADMIN_PASSWORD") or None,
            allow_guest_ocr=_parse_bool(os.environ.get("ALLOW_GUEST_OCR"), True),
            enable_paddle_ocr=_parse_bool(os.environ.get("ENABLE_PADDLE_OCR"), True),
            lexicon_path=Path(os.environ.get("TELUGU_LEXICON_PATH", str(default_lexicon))).resolve(),
            dictionary_db_path=Path(
                os.environ.get("TELUGU_DICTIONARY_DB_PATH", str(default_dict_db))
            ).resolve(),
            enable_api_docs=_parse_bool(raw_api_docs, False) if raw_api_docs is not None else None,
            rate_limit_enabled=_parse_bool(raw_rate_limit, False) if raw_rate_limit is not None else None,
            rate_limit_auth_failures=_parse_int(os.environ.get("RATE_LIMIT_AUTH_FAILURES"), 15),
            rate_limit_uploads_per_10min=_parse_int(os.environ.get("RATE_LIMIT_UPLOADS_PER_10MIN"), 12),
            rate_limit_ocr_starts_per_10min=_parse_int(os.environ.get("RATE_LIMIT_OCR_STARTS_PER_10MIN"), 30),
            max_render_pixels=_parse_int(os.environ.get("MAX_RENDER_PIXELS"), 25_000_000, minimum=100_000),
            ocr_page_timeout_sec=_parse_int(os.environ.get("OCR_PAGE_TIMEOUT_SEC"), 180, minimum=5),
            isolate_ocr_worker=_parse_bool(os.environ.get("ISOLATE_PADDLE_WORKER" if "ISOLATE_PADDLE_WORKER" in os.environ else "ISOLATE_OCR_WORKER"), True),
            prewarm_lexicon=_parse_bool(os.environ.get("PREWARM_LEXICON"), True),
            low_conf_threshold_tesseract=float(os.environ.get("LOW_CONF_THRESHOLD_TESSERACT", "75.0")),
            low_conf_threshold_paddle=float(os.environ.get("LOW_CONF_THRESHOLD_PADDLE", "0.85")),
        )
