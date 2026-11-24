"""Phase 2 integration tests against real PostgreSQL, Alembic schema, and FastAPI."""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path
from uuid import UUID

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import text

from src.api.app import create_app
from src.core.config import AppSettings
from src.db.session import build_engine

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://telugu_digitizer:telugu_digitizer@127.0.0.1:5432/telugu_digitizer_test",
)


def _telugu_font_path() -> str:
    for candidate in (
        "/System/Library/Fonts/KohinoorTelugu.ttc",
        "/System/Library/Fonts/Supplemental/Telugu MN.ttc",
        "/System/Library/Fonts/Supplemental/Telugu Sangam MN.ttc",
    ):
        if Path(candidate).is_file():
            return candidate
    pytest.skip("No Telugu system font available for Phase 2 integration test.")
    return ""


def _build_mixed_fixture_pdf() -> bytes:
    """Build a 2-page PDF: p1 scanned Telugu image (900x330 at 300 DPI), p2 born-digital text."""
    font_path = _telugu_font_path()
    img = Image.new("RGB", (900, 330), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 38)
    draw.text((40, 40), "తెలుగు పుస్తక పరీక్ష", fill="black", font=font)
    draw.text((40, 160), "భాష మరియు లిపి 2026.", fill="black", font=font)
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")

    doc = pymupdf.open()
    p1 = doc.new_page(width=216.0, height=79.2)
    p1.insert_image(p1.rect, stream=img_buf.getvalue())
    p2 = doc.new_page(width=400.0, height=200.0)
    p2.insert_text((36, 70), "Digital born page for Phase 2 separation test.", fontsize=14)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture()
def phase2_client(tmp_path: Path):
    """Prepare a clean PostgreSQL test DB via Alembic and yield a TestClient."""
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
            api_host="127.0.0.1",
            api_port=8000,
            max_upload_mb=50,
            max_pdf_pages=200,
            default_render_dpi=300,
            paddle_device="cpu",
        )
        app = create_app(settings)
        with TestClient(app) as client:
            yield client, app, settings
    finally:
        os.environ.pop("DATABASE_URL", None)


def test_phase2_health_and_validation_errors(phase2_client) -> None:
    client, _app, _settings = phase2_client

    health = client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["database"] == "connected"

    bad_upload = client.post(
        "/api/v1/books",
        files={"file": ("not_a_pdf.txt", b"hello world", "text/plain")},
        data={"title": "Invalid Upload"},
    )
    assert bad_upload.status_code == 400
    body = bad_upload.json()
    assert body["error"]["code"] == "INVALID_PDF_SIGNATURE"


def test_phase2_upload_ocr_idempotency_resume_and_delete(phase2_client) -> None:
    client, app, settings = phase2_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    pdf_bytes = _build_mixed_fixture_pdf()

    # 1. Upload PDF (with path traversal filename to verify sanitization)
    upload_res = client.post(
        "/api/v1/books",
        files={"file": ("../../evil/sample.pdf", pdf_bytes, "application/pdf")},
        data={"title": "తెలుగు పరీక్ష పుస్తకం", "author": "Test Author", "training_consent": "false"},
    )
    assert upload_res.status_code == 201
    uploaded = upload_res.json()
    book_id = uploaded["book_id"]
    assert uploaded["page_count"] == 2
    assert uploaded["duplicate"] is False

    # Source PDF must be read-only on disk
    source_pdf_path = settings.workspace_dir / "originals" / book_id / "source.pdf"
    assert source_pdf_path.is_file()
    mode = stat.S_IMODE(source_pdf_path.stat().st_mode)
    assert mode & 0o222 == 0

    # 2. Duplicate SHA-256 upload returns existing book idempotently
    dup_res = client.post(
        "/api/v1/books",
        files={"file": ("sample_copy.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Duplicate Attempt"},
    )
    assert dup_res.status_code == 201
    assert dup_res.json()["book_id"] == book_id
    assert dup_res.json()["duplicate"] is True

    # 3. Inspect book & pages (digital vs scanned separation)
    book_meta = client.get(f"/api/v1/books/{book_id}").json()
    assert book_meta["original_filename"] == "sample.pdf"
    assert book_meta["scanned_pages_count"] == 1
    assert book_meta["digital_text_pages_count"] == 1

    pages_res = client.get(f"/api/v1/books/{book_id}/pages").json()
    assert pages_res["items"][0]["page_kind"] == "scanned_image"
    assert pages_res["items"][1]["page_kind"] == "digital_text"

    img_res = client.get(f"/api/v1/books/{book_id}/pages/1/image")
    assert img_res.status_code == 200
    assert img_res.content.startswith(b"\x89PNG")
    assert "max-age=" in img_res.headers.get("cache-control", "")
    img_etag = img_res.headers.get("etag")
    assert img_etag
    cached_img_res = client.get(
        f"/api/v1/books/{book_id}/pages/1/image",
        headers={"If-None-Match": img_etag},
    )
    assert cached_img_res.status_code == 304

    digital_res = client.get(f"/api/v1/books/{book_id}/pages/2/digital-text")
    assert digital_res.status_code == 200
    assert "Digital born page" in digital_res.json()["text"]

    no_digital = client.get(f"/api/v1/books/{book_id}/pages/1/digital-text")
    assert no_digital.status_code == 409
    assert no_digital.json()["error"]["code"] == "NO_DIGITAL_TEXT"

    # 4. Run OCR (only page 1 scanned_image should be processed; page 2 digital_text excluded)
    run_res = client.post(
        f"/api/v1/books/{book_id}/ocr-runs",
        json={
            "engines": ["paddle_ppocrv5_te", "tesseract_tel_best"],
            "render_dpi": 300,
            "preprocessing_profile": "none",
            "force_rerun": False,
        },
    )
    assert run_res.status_code == 202
    run_body = run_res.json()
    assert run_body["pages_total"] == 1
    assert len(run_body["ocr_run_ids"]) == 2

    for rid in run_body["ocr_run_ids"]:
        app.state.ocr_executor.wait_for_run(UUID(rid), timeout=120.0)
        status_res = client.get(f"/api/v1/ocr-runs/{rid}")
        assert status_res.status_code == 200
        status_json = status_res.json()
        assert status_json["status"] == "completed"
        assert status_json["progress_current"] == 1
        assert status_json["progress_total"] == 1

        page_ocr = client.get(f"/api/v1/ocr-runs/{rid}/pages/1")
        assert page_ocr.status_code == 200
        ocr_json = page_ocr.json()
        assert len(ocr_json["blocks"]) >= 1
        assert ocr_json["blocks"][0]["text"]  # non-empty raw OCR text preserved

    # 5. Idempotent re-submission without force_rerun reuses existing runs
    reuse_res = client.post(
        f"/api/v1/books/{book_id}/ocr-runs",
        json={
            "engines": ["paddle_ppocrv5_te", "tesseract_tel_best"],
            "render_dpi": 300,
            "preprocessing_profile": "none",
            "force_rerun": False,
        },
    )
    assert reuse_res.status_code == 202
    assert reuse_res.json()["reused_existing"] is True
    assert reuse_res.json()["ocr_run_ids"] == run_body["ocr_run_ids"]

    # 6. Delete book cleans up DB and read-only storage files
    del_res = client.delete(f"/api/v1/books/{book_id}")
    assert del_res.status_code == 204
    assert not (settings.workspace_dir / "originals" / book_id).exists()
    assert not (settings.workspace_dir / "pages" / book_id).exists()
    assert not (settings.workspace_dir / "ocr" / book_id).exists()
    assert client.get(f"/api/v1/books/{book_id}").status_code == 404


def test_phase2_resume_partial_ocr_run_skips_completed_pages(phase2_client) -> None:
    """Verify interrupted/partial runs resume cleanly without duplicating existing ocr_blocks."""
    client, app, settings = phase2_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    # Build a 2-page scanned PDF.
    font_path = _telugu_font_path()
    img = Image.new("RGB", (900, 330), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 38)
    draw.text((40, 80), "తెలుగు పునఃప్రారంభ పరీక్ష", fill="black", font=font)
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")

    doc = pymupdf.open()
    for _ in range(2):
        page = doc.new_page(width=216.0, height=79.2)
        page.insert_image(page.rect, stream=img_buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()

    upload_res = client.post(
        "/api/v1/books",
        files={"file": ("resume_test.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Resume Test Book"},
    )
    assert upload_res.status_code == 201
    book_id = upload_res.json()["book_id"]

    # Run Tesseract on page 1 only, then expand config to page 1..2 and mark partial to simulate crash.
    run_res = client.post(
        f"/api/v1/books/{book_id}/ocr-runs",
        json={"engines": ["tesseract_tel_best"], "page_range": {"start": 1, "end": 1}},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["ocr_run_id"]
    app.state.ocr_executor.wait_for_run(UUID(run_id), timeout=30.0)

    from src.db.models import OCRBlock, OCRRun
    with app.state.session_factory() as db:
        ocr_run = db.get(OCRRun, UUID(run_id))
        assert ocr_run is not None
        cfg = dict(ocr_run.config)
        cfg["end_page"] = 2
        ocr_run.config = cfg
        ocr_run.status = "partial"
        db.commit()

    resume_res = client.post(f"/api/v1/ocr-runs/{run_id}/resume")
    assert resume_res.status_code == 202
    app.state.ocr_executor.wait_for_run(UUID(run_id), timeout=30.0)

    final_status = client.get(f"/api/v1/ocr-runs/{run_id}").json()
    assert final_status["status"] == "completed"
    assert final_status["progress_current"] == 2
    assert final_status["progress_total"] == 2

    p1_blocks = client.get(f"/api/v1/ocr-runs/{run_id}/pages/1").json()["blocks"]
    p2_blocks = client.get(f"/api/v1/ocr-runs/{run_id}/pages/2").json()["blocks"]
    assert len(p1_blocks) >= 1
    assert len(p2_blocks) >= 1
