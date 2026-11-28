"""Regression tests for SEC-01, SEC-02, SEC-04, SEC-07, SEC-08, and public guest OCR mode."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.compiler import compiles

from src.api.app import create_app
from src.core.config import AppSettings
from src.db.models import Base
from src.db.session import build_engine
from src.pdf.rasterizer import bounded_pixmap_matrix, bounded_render_dimensions

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://telugu_digitizer:telugu_digitizer@127.0.0.1:5432/telugu_digitizer_test",
)


@compiles(postgresql.JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(postgresql.UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(36)"


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _make_sample_pdf(
    path: Path,
    *,
    num_pages: int = 1,
    width: float = 595,
    height: float = 842,
    user_pw: str | None = None,
) -> Path:
    doc = pymupdf.open()
    try:
        for i in range(num_pages):
            page = doc.new_page(width=width, height=height)
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), 0)
            pix.set_rect(pix.irect, (255, 255, 255))
            page.insert_image(pymupdf.Rect(30, 30, min(width - 10, 300), min(height - 10, 200)), pixmap=pix)
            _ = i
        if user_pw:
            doc.save(
                str(path),
                encryption=pymupdf.PDF_ENCRYPT_AES_256,
                user_pw=user_pw,
                owner_pw=user_pw + "-owner",
            )
        else:
            doc.save(str(path))
    finally:
        doc.close()
    return path


def _prepare_test_db(tmp_path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    engine = build_engine(TEST_DB_URL)
    use_postgres = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        use_postgres = True
    except Exception:
        use_postgres = False
    finally:
        engine.dispose()

    if use_postgres:
        pg_engine = build_engine(TEST_DB_URL)
        with pg_engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        pg_engine.dispose()
        alembic_cfg = Config(str(repo_root / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
        os.environ["DATABASE_URL"] = TEST_DB_URL
        try:
            command.upgrade(alembic_cfg, "head")
        finally:
            os.environ.pop("DATABASE_URL", None)
        return TEST_DB_URL

    db_url = f"sqlite:///{(tmp_path / 'audit_sec.db').resolve()}"
    sq_engine = create_engine(db_url)
    Base.metadata.create_all(sq_engine)
    sq_engine.dispose()
    return db_url


def _make_settings(tmp_path: Path, db_url: str, **overrides) -> AppSettings:
    repo_root = Path(__file__).resolve().parents[1]
    defaults = dict(
        database_url=db_url,
        workspace_dir=(tmp_path / "workspace").resolve(),
        tessdata_dir=(repo_root / "models" / "tesseract" / "tessdata").resolve(),
        tesseract_cmd=None,
        api_host="127.0.0.1",
        api_port=8000,
        max_upload_mb=20,
        max_pdf_pages=100,
        default_render_dpi=300,
        paddle_device="cpu",
        cors_allowed_origins=["https://lahari.org"],
        proxy_headers=True,
        auth_username=None,
        auth_password=None,
        admin_username="admin",
        admin_password="admin-secret-password",
        allow_guest_ocr=True,
        enable_paddle_ocr=False,
        enable_api_docs=False,
        rate_limit_enabled=True,
        rate_limit_auth_failures=4,
        rate_limit_uploads_per_10min=20,
        rate_limit_ocr_starts_per_10min=20,
        prewarm_lexicon=False,
    )
    defaults.update(overrides)
    return AppSettings(**defaults)


def test_sec01_guest_ocr_allowed_while_delete_requires_admin_and_rate_limits(tmp_path: Path) -> None:
    db_url = _prepare_test_db(tmp_path)
    settings = _make_settings(tmp_path, db_url)
    app = create_app(settings)
    pdf_path = _make_sample_pdf(tmp_path / "guest_book.pdf", num_pages=1)

    with TestClient(app) as client:
        # SEC-07: health omits workspace_dir & API docs are disabled
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        hdata = health.json()
        assert "workspace_dir" not in hdata
        assert hdata["workspace"] == "ready"
        assert "X-Request-ID" in health.headers
        assert health.headers.get("X-Content-Type-Options") == "nosniff"
        assert client.get("/api/v1/docs").status_code == 404
        assert client.get("/api/v1/openapi.json").status_code == 404

        caps = client.get("/api/v1/capabilities")
        assert caps.status_code == 200
        cdata = caps.json()
        assert cdata["guest_ocr_enabled"] is True
        assert cdata["auth_enabled"] is False
        assert cdata["admin_delete_requires_auth"] is True
        assert cdata["book_delete_enabled"] is False

        # Guest can upload PDF and add custom word without Basic Auth
        with pdf_path.open("rb") as fh:
            imp = client.post(
                "/api/v1/books",
                data={"title": "Guest Telugu Book"},
                files={"file": ("guest_book.pdf", fh, "application/pdf")},
            )
        assert imp.status_code == 201, imp.text
        book_id = imp.json()["book_id"]

        cw = client.post(
            "/api/v1/dictionary/custom",
            json={"word": "తెలుగుబడి", "meaning_en": "Telugu school"},
        )
        assert cw.status_code == 201, cw.text
        custom_id = cw.json()["word_id"]

        # Guest cannot call destructive DELETE endpoints
        assert client.delete(f"/api/v1/books/{book_id}").status_code == 401
        assert client.delete(f"/api/v1/dictionary/custom/{custom_id}").status_code == 401

        # Wrong admin password gets 401 then hits 429 rate limit
        bad_headers = _basic_auth_header("admin", "wrong-pass")
        for _ in range(4):
            res = client.delete(f"/api/v1/books/{book_id}", headers=bad_headers)
            assert res.status_code == 401
        limited = client.delete(f"/api/v1/books/{book_id}", headers=bad_headers)
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    # Fresh app instance with valid admin credentials can delete
    app2 = create_app(_make_settings(tmp_path, db_url))
    with TestClient(app2) as client2:
        admin_headers = _basic_auth_header("admin", "admin-secret-password")
        del_cw = client2.delete(f"/api/v1/dictionary/custom/{custom_id}", headers=admin_headers)
        assert del_cw.status_code == 204
        del_book = client2.delete(f"/api/v1/books/{book_id}", headers=admin_headers)
        assert del_book.status_code == 204


def test_sec01_fail_closed_delete_and_csrf_and_upload_rate_limit(tmp_path: Path) -> None:
    db_url = _prepare_test_db(tmp_path)
    settings = _make_settings(
        tmp_path,
        db_url,
        admin_username=None,
        admin_password=None,
        rate_limit_uploads_per_10min=2,
    )
    app = create_app(settings)
    pdf_path = _make_sample_pdf(tmp_path / "rate_book.pdf", num_pages=1)

    with TestClient(app) as client:
        # CSRF check blocks mismatched Origin on state-changing requests
        csrf_bad = client.post(
            "/api/v1/dictionary/custom",
            headers={"Origin": "https://evil.example"},
            json={"word": "తెలుగు", "meaning_en": "Telugu"},
        )
        assert csrf_bad.status_code == 403
        assert csrf_bad.json()["error"]["code"] == "CSRF_ORIGIN_DENIED"

        # Fail-closed DELETE in proxy/network mode without admin credentials configured
        fail_closed = client.delete(f"/api/v1/books/{uuid4()}")
        assert fail_closed.status_code == 403
        assert fail_closed.json()["error"]["code"] == "ADMIN_AUTH_REQUIRED"

        # Upload rate limit enforced after 2 uploads
        for idx in range(2):
            p = _make_sample_pdf(tmp_path / f"u{idx}.pdf", width=590 + idx)
            with p.open("rb") as fh:
                r = client.post(
                    "/api/v1/books",
                    data={"title": f"Book {idx}"},
                    files={"file": (f"u{idx}.pdf", fh, "application/pdf")},
                )
            assert r.status_code == 201
        with pdf_path.open("rb") as fh:
            third = client.post(
                "/api/v1/books",
                data={"title": "Book 3"},
                files={"file": ("rate_book.pdf", fh, "application/pdf")},
            )
        assert third.status_code == 429
        assert third.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"


def test_sec02_streaming_upload_rejects_oversized_pdf_and_cleans_tmp(tmp_path: Path) -> None:
    db_url = _prepare_test_db(tmp_path)
    settings = _make_settings(tmp_path, db_url, max_upload_mb=1)
    app = create_app(settings)
    big_pdf_bytes = b"%PDF-1.4\n" + (b"0" * (1_200_000))

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/books",
            data={"title": "Too Big"},
            files={"file": ("huge.pdf", big_pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 413
        assert resp.json()["error"]["code"] == "PDF_TOO_LARGE"

        bad_sig = client.post(
            "/api/v1/books",
            data={"title": "Fake PDF"},
            files={"file": ("fake.pdf", b"NOT_A_PDF_HEADER", "application/pdf")},
        )
        assert bad_sig.status_code == 400
        assert bad_sig.json()["error"]["code"] == "INVALID_PDF_SIGNATURE"

    tmp_dir = settings.workspace_dir / "tmp"
    leftovers = list(tmp_dir.glob("*")) if tmp_dir.exists() else []
    assert leftovers == []


def test_sec04_encrypted_pdf_rejected_and_pixel_bomb_clamped(tmp_path: Path) -> None:
    db_url = _prepare_test_db(tmp_path)
    settings = _make_settings(tmp_path, db_url, max_render_pixels=1_000_000)
    app = create_app(settings)
    enc_pdf = _make_sample_pdf(tmp_path / "encrypted.pdf", user_pw="secret123")

    with TestClient(app) as client:
        with enc_pdf.open("rb") as fh:
            resp = client.post(
                "/api/v1/books",
                data={"title": "Encrypted Book"},
                files={"file": ("encrypted.pdf", fh, "application/pdf")},
            )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "ENCRYPTED_PDF_UNSUPPORTED"

    huge_rect = pymupdf.Rect(0, 0, 7200, 7200)
    w, h = bounded_render_dimensions(huge_rect, 300, max_pixels=25_000_000)
    assert w * h <= 25_000_000
    assert w > 0 and h > 0

    mat, eff_dpi, clamped = bounded_pixmap_matrix(huge_rect, 300, max_pixels=1_000_000)
    assert clamped is True
    assert eff_dpi < 300.0
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=7200, height=7200)
        pix = page.get_pixmap(matrix=mat, colorspace=pymupdf.csRGB, alpha=False)
        assert pix.width * pix.height <= 1_050_000
    finally:
        doc.close()


def test_sec08_schema_payload_bounds_reject_oversized_text(tmp_path: Path) -> None:
    db_url = _prepare_test_db(tmp_path)
    settings = _make_settings(tmp_path, db_url)
    app = create_app(settings)
    with TestClient(app) as client:
        res = client.post(
            f"/api/v1/ocr-blocks/{uuid4()}/edits",
            json={"edited_text": "అ" * 20_005},
        )
        assert res.status_code == 422
