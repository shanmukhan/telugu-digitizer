"""FastAPI application factory with structured errors and durable worker lifecycle."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
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
