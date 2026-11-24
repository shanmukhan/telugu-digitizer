"""FastAPI application factory with structured errors and durable worker lifecycle."""

from __future__ import annotations

import base64
import binascii
import hmac
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import update

from src.api.errors import AppError
from src.api.routes import router as v1_router
from src.common.logging_utils import configure_logging
from src.core.config import AppSettings
from src.core.storage import LocalFilesystemStorage
from src.db.models import OCRRun, ProcessingJob
from src.db.session import build_engine, build_session_factory
from src.services.ocr_service import OCRJobExecutor


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI Phase 2 backend application."""
    cfg = settings or AppSettings.from_env()
    configure_logging("INFO")
    engine = build_engine(cfg.database_url)
    session_factory = build_session_factory(engine)
    storage = LocalFilesystemStorage(cfg.workspace_dir)
    executor = OCRJobExecutor(
        session_factory=session_factory,
        storage=storage,
        settings=cfg,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Recover any runs left in 'running' state by a previous unexpected shutdown.
        with session_factory() as db:
            db.execute(
                update(OCRRun)
                .where(OCRRun.status == "running")
                .values(status="partial", error_summary="Interrupted before completion; ready to resume.")
            )
            db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.status == "running")
                .values(status="partial")
            )
            db.commit()
        try:
            yield
        finally:
            executor.shutdown(wait=True)
            engine.dispose()

    app = FastAPI(
        title="Telugu Book Digitizer API",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.db_engine = engine
    app.state.session_factory = session_factory
    app.state.storage = storage
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

    if cfg.auth_username and cfg.auth_password:
        expected_user = cfg.auth_username.encode("utf-8")
        expected_pass = cfg.auth_password.encode("utf-8")

        @app.middleware("http")
        async def require_basic_auth(request: Request, call_next):
            if request.method == "OPTIONS" or request.url.path == "/api/v1/health":
                return await call_next(request)

            auth_header = request.headers.get("authorization", "")
            authorized = False
            if auth_header.startswith("Basic "):
                token = auth_header[6:].strip()
                try:
                    decoded = base64.b64decode(token, validate=True).decode("utf-8")
                    if ":" in decoded:
                        user, password = decoded.split(":", 1)
                        authorized = hmac.compare_digest(
                            user.encode("utf-8"), expected_user
                        ) and hmac.compare_digest(password.encode("utf-8"), expected_pass)
                except (binascii.Error, UnicodeDecodeError):
                    authorized = False

            if not authorized:
                headers = {"WWW-Authenticate": 'Basic realm="Telugu Book Digitizer", charset="UTF-8"'}
                if request.url.path.startswith("/api/"):
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

            return await call_next(request)

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_allowed_origins),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
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
