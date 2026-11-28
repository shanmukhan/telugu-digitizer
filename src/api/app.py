"""FastAPI application factory with structured errors, security middleware, and durable worker lifecycle."""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, update

from src.api.errors import AppError
from src.api.routes import router as v1_router
from src.common.logging_utils import configure_logging, log_event
from src.common.rate_limit import SlidingWindowRateLimiter
from src.core.config import AppSettings
from src.core.storage import LocalFilesystemStorage
from src.db.models import OCRRun, ProcessingJob
from src.db.session import build_engine, build_session_factory
from src.services.ocr_service import OCRJobExecutor

LOGGER = logging.getLogger("telugu_digitizer.api")

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_AUTH_REALM_STUDIO = 'Basic realm="Telugu Book Digitizer", charset="UTF-8"'
_CSP_HEADER = (
    "default-src 'self'; "
    "script-src 'self' 'wasm-unsafe-eval' blob:; "
    "worker-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'self'; "
    "base-uri 'self'"
)


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _parse_basic_auth_header(header_value: str) -> tuple[str, str] | None:
    if not header_value.startswith("Basic "):
        return None
    token = header_value[6:].strip()
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    if ":" not in decoded:
        return None
    user, password = decoded.split(":", 1)
    return user, password


def _origin_matches_request(origin: str, request: Request, allowed_origins: set[str]) -> bool:
    norm_origin = origin.strip().rstrip("/").lower()
    if norm_origin in allowed_origins:
        return True
    parsed_origin = urlparse(norm_origin)
    if not parsed_origin.scheme or not parsed_origin.netloc:
        return False

    host_header = (request.headers.get("host") or "").strip().lower()
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    req_scheme = forwarded_proto or request.url.scheme.lower()
    if host_header and parsed_origin.netloc.lower() == host_header and parsed_origin.scheme == req_scheme:
        return True
    return False


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI backend application."""
    cfg = settings or AppSettings.from_env()
    configure_logging("INFO", log_file=cfg.workspace_dir / "logs" / "telugu-digitizer.log")
    engine = build_engine(cfg.database_url)
    session_factory = build_session_factory(engine)
    storage = LocalFilesystemStorage(cfg.workspace_dir)
    rate_limiter = SlidingWindowRateLimiter()
    executor = OCRJobExecutor(
        session_factory=session_factory,
        storage=storage,
        settings=cfg,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Recover any runs left in 'running' or 'queued' state by a previous unexpected shutdown.
        with session_factory() as db:
            interrupted_ids = [
                str(rid)
                for rid in db.scalars(
                    select(OCRRun.id).where(OCRRun.status.in_(["running", "queued"]))
                ).all()
            ]
            if interrupted_ids:
                db.execute(
                    update(OCRRun)
                    .where(OCRRun.status.in_(["running", "queued"]))
                    .values(status="partial", error_summary="Interrupted before completion; ready to resume.")
                )
                db.execute(
                    update(ProcessingJob)
                    .where(ProcessingJob.status.in_(["running", "queued"]))
                    .values(status="partial")
                )
                db.commit()
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "Recovered interrupted OCR runs after unexpected shutdown",
                    count=len(interrupted_ids),
                    run_ids=interrupted_ids,
                )

        if cfg.auth_username and cfg.auth_password:
            auth_mode = "full_basic_auth"
        elif cfg.is_network_exposed and cfg.effective_admin_credentials:
            auth_mode = "guest_ocr_with_admin_delete"
        elif cfg.is_network_exposed:
            auth_mode = "guest_ocr_fail_closed_delete"
        else:
            auth_mode = "localhost_single_user"

        log_event(
            LOGGER,
            logging.WARNING if auth_mode == "guest_ocr_fail_closed_delete" else logging.INFO,
            "API security posture initialized",
            auth_mode=auth_mode,
            network_exposed=cfg.is_network_exposed,
            guest_ocr_enabled=not (cfg.auth_username and cfg.auth_password) and cfg.allow_guest_ocr,
            admin_delete_configured=bool(cfg.effective_admin_credentials),
            rate_limit_enabled=cfg.effective_rate_limit_enabled,
            api_docs_enabled=cfg.effective_api_docs_enabled,
        )
        if auth_mode == "guest_ocr_fail_closed_delete":
            log_event(
                LOGGER,
                logging.WARNING,
                "Running network-exposed without APP_ADMIN_USERNAME/APP_ADMIN_PASSWORD; destructive DELETE routes will fail closed with 403.",
            )

        if cfg.lexicon_path and not cfg.lexicon_path.is_file():
            log_event(
                LOGGER,
                logging.WARNING,
                "Telugu lexicon archive not found; dictionary auto-correct will run in degraded mode until built.",
                lexicon_path=str(cfg.lexicon_path),
            )
        elif cfg.lexicon_path and cfg.lexicon_path.is_file() and cfg.prewarm_lexicon:
            def _bg_warm_lexicon() -> None:
                try:
                    from src.services.lexicon_service import get_telugu_lexicon
                    get_telugu_lexicon(cfg.lexicon_path)
                except Exception as exc:
                    LOGGER.warning("Background lexicon warm-up skipped: %s", exc)

            threading.Thread(target=_bg_warm_lexicon, daemon=True, name="lexicon-warmup").start()

        if cfg.dictionary_db_path and not cfg.dictionary_db_path.is_file():
            log_event(
                LOGGER,
                logging.WARNING,
                "Standalone Telugu SQLite dictionary database not found; dictionary definitions lookup unavailable until built.",
                dictionary_db_path=str(cfg.dictionary_db_path),
            )

        try:
            yield
        finally:
            executor.shutdown(wait=True)
            engine.dispose()

    docs_url = "/docs" if cfg.effective_api_docs_enabled else None
    redoc_url = "/redoc" if cfg.effective_api_docs_enabled else None
    openapi_url = "/openapi.json" if cfg.effective_api_docs_enabled else None

    app = FastAPI(
        title="Telugu Book Digitizer API",
        version="0.2.0",
        lifespan=lifespan,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    app.state.settings = cfg
    app.state.db_engine = engine
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.rate_limiter = rate_limiter
    app.state.ocr_executor = executor

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed.",
                    "details": {"issues": exc.errors()},
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "HTTP_ERROR",
                    "message": str(exc.detail),
                    "details": {},
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception("Unhandled server exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": f"Unexpected server error: {type(exc).__name__}",
                    "details": {},
                }
            },
        )

    allowed_csrf_origins = {
        origin.strip().rstrip("/").lower()
        for origin in cfg.cors_allowed_origins
        if origin.strip() and origin.strip() != "*"
    }

    @app.middleware("http")
    async def security_and_rate_limit_middleware(request: Request, call_next):
        raw_req_id = request.headers.get("x-request-id", "").strip()
        req_id = raw_req_id[:64] if raw_req_id and raw_req_id.replace("-", "").isalnum() else uuid.uuid4().hex[:16]
        client_ip = _client_ip(request)
        path = request.url.path
        started = time.perf_counter()

        # 1. CSRF / Origin protection on state-changing browser requests.
        if request.method in _MUTATING_METHODS:
            origin = request.headers.get("origin")
            sec_fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
            if origin:
                if not _origin_matches_request(origin, request, allowed_csrf_origins):
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": {
                                "code": "CSRF_ORIGIN_DENIED",
                                "message": "Cross-origin state-changing request denied.",
                                "details": {},
                            }
                        },
                        headers={"X-Request-ID": req_id},
                    )
            elif sec_fetch_site == "cross-site":
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "CSRF_ORIGIN_DENIED",
                            "message": "Cross-site state-changing request denied.",
                            "details": {},
                        }
                    },
                    headers={"X-Request-ID": req_id},
                )

        # 2. Full-site Basic Auth (when APP_AUTH_USERNAME/APP_AUTH_PASSWORD are set).
        if cfg.auth_username and cfg.auth_password:
            if request.method != "OPTIONS" and path != "/api/v1/health":
                locked, retry_after = rate_limiter.is_limited(
                    "auth_fail",
                    client_ip,
                    limit=cfg.rate_limit_auth_failures,
                    window_seconds=300.0,
                )
                if locked:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": {
                                "code": "RATE_LIMIT_EXCEEDED",
                                "message": "Too many failed authentication attempts. Please retry later.",
                                "details": {"retry_after_seconds": retry_after},
                            }
                        },
                        headers={"Retry-After": str(retry_after), "X-Request-ID": req_id},
                    )

                creds = _parse_basic_auth_header(request.headers.get("authorization", ""))
                authorized = False
                if creds is not None:
                    user, password = creds
                    authorized = hmac.compare_digest(
                        user.encode("utf-8"), cfg.auth_username.encode("utf-8")
                    ) and hmac.compare_digest(
                        password.encode("utf-8"), cfg.auth_password.encode("utf-8")
                    )

                if not authorized:
                    if creds is not None:
                        rate_limiter.allow(
                            "auth_fail",
                            client_ip,
                            limit=cfg.rate_limit_auth_failures,
                            window_seconds=300.0,
                        )
                    headers = {"WWW-Authenticate": _AUTH_REALM_STUDIO, "X-Request-ID": req_id}
                    if path.startswith("/api/"):
                        return JSONResponse(
                            status_code=401,
                            content={
                                "error": {
                                    "code": "UNAUTHORIZED",
                                    "message": "Authentication required.",
                                    "details": {},
                                }
                            },
                            headers=headers,
                        )
                    return Response(content="Authentication required.", status_code=401, headers=headers)

        elif not cfg.allow_guest_ocr and path.startswith("/api/") and path != "/api/v1/health":
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "GUEST_ACCESS_DISABLED",
                        "message": "Guest access is disabled and full Basic Auth is not configured.",
                        "details": {},
                    }
                },
                headers={"X-Request-ID": req_id},
            )

        # 3. Rate limiting on heavy compute/upload routes when network-exposed or explicitly enabled.
        if cfg.effective_rate_limit_enabled and request.method in _MUTATING_METHODS and path.startswith("/api/v1/"):
            allowed = True
            retry_after = 0
            if path == "/api/v1/books" and request.method == "POST":
                allowed, retry_after = rate_limiter.allow(
                    "upload_pdf",
                    client_ip,
                    limit=cfg.rate_limit_uploads_per_10min,
                    window_seconds=600.0,
                )
            elif (
                (path.startswith("/api/v1/books/") and path.endswith("/ocr-runs"))
                or (path.startswith("/api/v1/ocr-runs/") and path.endswith("/resume"))
            ):
                allowed, retry_after = rate_limiter.allow(
                    "ocr_start",
                    client_ip,
                    limit=cfg.rate_limit_ocr_starts_per_10min,
                    window_seconds=600.0,
                )
            else:
                allowed, retry_after = rate_limiter.allow(
                    "api_write",
                    client_ip,
                    limit=240,
                    window_seconds=60.0,
                )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": "Rate limit exceeded; please slow down and try again shortly.",
                            "details": {"retry_after_seconds": retry_after},
                        }
                    },
                    headers={"Retry-After": str(retry_after), "X-Request-ID": req_id},
                )

        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)

        response.headers.setdefault("X-Request-ID", req_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not path.startswith("/api/") and path not in ("/docs", "/redoc", "/openapi.json"):
            response.headers.setdefault("Content-Security-Policy", _CSP_HEADER)

        if path.startswith("/api/") and response.status_code >= 400:
            log_event(
                LOGGER,
                logging.WARNING if response.status_code < 500 else logging.ERROR,
                "API error response",
                request_id=req_id,
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                client_ip=client_ip,
            )
        return response

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o for o in cfg.cors_allowed_origins if o != "*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    app.include_router(v1_router)

    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if (frontend_dist / "index.html").is_file():
        assets_dir = frontend_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str):
            if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
                raise HTTPException(status_code=404, detail="Not found")
            candidate = (frontend_dist / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(frontend_dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app
