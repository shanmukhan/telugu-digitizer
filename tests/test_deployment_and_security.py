"""Tests for Raspberry Pi / lahari.org hosting configuration, Basic Auth, CORS, and OCR capabilities."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.api.app import create_app
from src.core.config import AppSettings
from src.db.session import build_engine

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://telugu_digitizer:telugu_digitizer@127.0.0.1:5432/telugu_digitizer_test",
)


@pytest.fixture()
def hosted_client(tmp_path: Path):
    """TestClient configured similarly to public lahari.org hosting (Basic Auth + CORS + capabilities)."""
    repo_root = Path(__file__).resolve().parents[1]
    engine = build_engine(TEST_DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL test database unavailable ({TEST_DB_URL}): {exc}")

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()

    alembic_cfg = Config(str(repo_root / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    os.environ["DATABASE_URL"] = TEST_DB_URL
    try:
        command.upgrade(alembic_cfg, "head")
        settings = AppSettings(
            database_url=TEST_DB_URL,
            workspace_dir=(tmp_path / "workspace").resolve(),
            tessdata_dir=(repo_root / "models" / "tesseract" / "tessdata").resolve(),
            tesseract_cmd=None,
            api_host="0.0.0.0",
            api_port=8000,
            max_upload_mb=200,
            max_pdf_pages=1000,
            default_render_dpi=300,
            paddle_device="cpu",
            cors_allowed_origins=("https://lahari.org", "https://www.lahari.org"),
            proxy_headers=True,
            forwarded_allow_ips="*",
            auth_username="admin",
            auth_password="strong-test-password",
            enable_paddle_ocr=False,
        )
        app = create_app(settings)
        with TestClient(app) as client:
            yield client
    finally:
        os.environ.pop("DATABASE_URL", None)


def _basic_header(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_basic_auth_cors_and_capabilities_for_hosted_deployment(hosted_client: TestClient) -> None:
    # 1. Health endpoint remains accessible for container / reverse-proxy healthchecks
    health = hosted_client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["database"] == "connected"

    # 2. Protected routes and SPA reject unauthenticated and wrong credentials
    unauth_books = hosted_client.get("/api/v1/books")
    assert unauth_books.status_code == 401
    assert unauth_books.json()["error"]["code"] == "UNAUTHORIZED"
    assert "Basic" in unauth_books.headers.get("www-authenticate", "")

    unauth_root = hosted_client.get("/")
    assert unauth_root.status_code == 401

    wrong_auth = hosted_client.get("/api/v1/books", headers=_basic_header("admin", "wrong"))
    assert wrong_auth.status_code == 401

    # 3. Valid credentials grant access + expose CORS for https://lahari.org
    authed_headers = {**_basic_header("admin", "strong-test-password"), "Origin": "https://lahari.org"}
    books_ok = hosted_client.get("/api/v1/books", headers=authed_headers)
    assert books_ok.status_code == 200
    assert books_ok.headers.get("access-control-allow-origin") == "https://lahari.org"

    # 4. Capabilities reflect ENABLE_PADDLE_OCR=false and return 503 cleanly if requested
    caps = hosted_client.get("/api/v1/capabilities", headers=_basic_header("admin", "strong-test-password"))
    assert caps.status_code == 200
    caps_json = caps.json()
    assert caps_json["auth_enabled"] is True
    assert caps_json["engines"]["paddle_ppocrv5_te"]["available"] is False
    assert "ENABLE_PADDLE_OCR=false" in (caps_json["engines"]["paddle_ppocrv5_te"]["reason"] or "")

    # 5. Requesting disabled PaddleOCR returns clean 503 OCR_MODEL_NOT_AVAILABLE when starting OCR
    from tests.test_phase2_api_and_db import _build_mixed_fixture_pdf

    upload = hosted_client.post(
        "/api/v1/books",
        files={"file": ("cap_test.pdf", _build_mixed_fixture_pdf(), "application/pdf")},
        data={"title": "Capabilities Test"},
        headers=_basic_header("admin", "strong-test-password"),
    )
    assert upload.status_code == 201
    book_id = upload.json()["book_id"]

    disabled_run = hosted_client.post(
        f"/api/v1/books/{book_id}/ocr-runs",
        json={"engines": ["paddle_ppocrv5_te"]},
        headers=_basic_header("admin", "strong-test-password"),
    )
    assert disabled_run.status_code == 503
    assert disabled_run.json()["error"]["code"] == "OCR_MODEL_NOT_AVAILABLE"
