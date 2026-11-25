"""Phase 3 backend tests for side-by-side review payload, append-only edits, and status."""

from __future__ import annotations

import io
import os
from pathlib import Path
from uuid import UUID

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, text

from src.api.app import create_app
from src.core.config import AppSettings
from src.db.models import DocumentTextVersion, OCRBlock, ReviewEdit
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
    pytest.skip("No Telugu system font available.")
    return ""


def _build_fixture_pdf_bytes() -> bytes:
    font_path = _telugu_font_path()
    img = Image.new("RGB", (900, 330), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 38)
    draw.text((40, 40), "తెలుగు పుస్తక పరీక్ష", fill="black", font=font)
    draw.text((40, 160), "భాష మరియు లిపి 2026.", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    p1 = doc.new_page(width=216.0, height=79.2)
    p1.insert_image(p1.rect, stream=buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture()
def phase3_client(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    engine = build_engine(TEST_DB_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        engine.dispose()
        pytest.skip(f"PostgreSQL test DB unavailable: {exc}")

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


def test_phase3_review_edits_preserve_raw_ocr_and_approve_page(phase3_client) -> None:
    client, app, settings = phase3_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    pdf_bytes = _build_fixture_pdf_bytes()
    upload = client.post(
        "/api/v1/books",
        files={"file": ("review_sample.pdf", pdf_bytes, "application/pdf")},
        data={"title": "సమీక్ష పరీక్ష పుస్తకం"},
    )
    assert upload.status_code == 201
    book_id = upload.json()["book_id"]

    # PDF.js source stream endpoint returns original PDF bytes
    pdf_resp = client.get(f"/api/v1/books/{book_id}/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.content.startswith(b"%PDF-")

    run_resp = client.post(
        f"/api/v1/books/{book_id}/ocr-runs",
        json={"engines": ["paddle_ppocrv5_te", "tesseract_tel_best"]},
    )
    assert run_resp.status_code == 202
    for rid in run_resp.json()["ocr_run_ids"]:
        app.state.ocr_executor.wait_for_run(UUID(rid), timeout=120.0)

    runs_list = client.get(f"/api/v1/books/{book_id}/ocr-runs").json()["items"]
    assert len(runs_list) == 2

    review_resp = client.get(f"/api/v1/books/{book_id}/pages/1/review")
    assert review_resp.status_code == 200
    review = review_resp.json()
    assert review["primary_engine"] == "paddleocr"
    assert review["comparator_engine"] == "tesseract"
    assert len(review["blocks"]) >= 1

    first_block = review["blocks"][0]
    block_id = first_block["block_id"]
    original_raw = first_block["raw_text"]

    # Submit Telugu Unicode correction
    corrected_text = "తెలుగు పుస్తక పరీక్ష (ధృవీకరించబడింది)"
    edit1 = client.post(
        f"/api/v1/ocr-blocks/{block_id}/edits",
        json={
            "edited_text": corrected_text,
            "action": "corrected",
            "review_note": "Verified against page image",
        },
    )
    assert edit1.status_code == 201
    edit1_json = edit1.json()
    assert edit1_json["raw_text"] == original_raw
    assert edit1_json["current_text"] == corrected_text
    assert edit1_json["page_review_status"] == "in_review"

    # Undo/revert edit appends a second audit event without losing raw OCR
    edit2 = client.post(
        f"/api/v1/ocr-blocks/{block_id}/edits",
        json={"edited_text": original_raw, "action": "reverted", "review_note": "Undo"},
    )
    assert edit2.status_code == 201
    assert edit2.json()["previous_text"] == corrected_text

    # Re-apply final correction
    edit3 = client.post(
        f"/api/v1/ocr-blocks/{block_id}/edits",
        json={"edited_text": corrected_text, "action": "corrected"},
    )
    assert edit3.status_code == 201

    # Verify DB invariants: raw_text untouched + 3 append-only ReviewEdit rows
    with app.state.session_factory() as db:
        blk_row = db.get(OCRBlock, UUID(block_id))
        assert blk_row is not None
        assert blk_row.raw_text == original_raw
        history = list(
            db.scalars(select(ReviewEdit).where(ReviewEdit.ocr_block_id == UUID(block_id))).all()
        )
        assert len(history) == 3

    # Approve page and confirm DocumentTextVersion transitions to 'approved'
    approve_resp = client.patch(
        f"/api/v1/books/{book_id}/pages/1/review-status",
        json={"review_status": "approved", "primary_run_id": review["primary_run_id"]},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["review_status"] == "approved"

    with app.state.session_factory() as db:
        ver = db.scalars(
            select(DocumentTextVersion).where(DocumentTextVersion.book_id == UUID(book_id))
        ).first()
        assert ver is not None
        assert ver.origin == "human_approved"
        assert ver.status == "approved"

    # Refetching review payload reflects persisted human edit & approved status
    review_after = client.get(f"/api/v1/books/{book_id}/pages/1/review").json()
    assert review_after["review_status"] == "approved"
    assert review_after["blocks"][0]["raw_text"] == original_raw
    assert review_after["blocks"][0]["current_text"] == corrected_text
    assert review_after["blocks"][0]["is_edited"] is True


def test_phase3_review_prefers_populated_run_over_empty_partial_paddle_run(phase3_client) -> None:
    """When a 0-page partial PaddleOCR run coexists with a completed Tesseract run, pick Tesseract."""
    client, app, settings = phase3_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    pdf_bytes = _build_fixture_pdf_bytes()
    book_id = client.post(
        "/api/v1/books",
        files={"file": ("fallback_sample.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Fallback Engine Priority Test"},
    ).json()["book_id"]

    # Complete Tesseract run first
    tess_resp = client.post(
        f"/api/v1/books/{book_id}/ocr-runs",
        json={"engines": ["tesseract_tel_best"]},
    ).json()
    tess_run_id = tess_resp["ocr_run_id"]
    app.state.ocr_executor.wait_for_run(UUID(tess_run_id), timeout=30.0)

    # Create a 0-progress partial PaddleOCR run record directly (simulating a crash before page 1 completed)
    from src.db.models import ModelRegistry, OCRRun, ProcessingJob

    with app.state.session_factory() as db:
        paddle_model = ModelRegistry(
            engine_name="paddleocr",
            engine_version="3.7.0",
            model_family="PP-OCRv5",
            model_id="PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
        )
        db.add(paddle_model)
        db.flush()
        paddle_job = ProcessingJob(
            book_id=UUID(book_id),
            job_type="ocr:paddle_ppocrv5_te",
            status="partial",
            progress_current=0,
            progress_total=1,
            error_details={},
        )
        db.add(paddle_job)
        db.flush()
        db.add(
            OCRRun(
                book_id=UUID(book_id),
                model_registry_id=paddle_model.id,
                processing_job_id=paddle_job.id,
                status="partial",
                idempotency_key="empty-partial-paddle-test",
                error_summary="Interrupted before completion; ready to resume.",
                config={"engine": "paddle_ppocrv5_te", "start_page": 1, "end_page": 1},
            )
        )
        db.commit()

    review = client.get(f"/api/v1/books/{book_id}/pages/1/review").json()
    assert review["primary_run_id"] == tess_run_id
    assert review["primary_engine"] == "tesseract"
    assert len(review["blocks"]) >= 1

    # Export without explicit primary_run_id also selects the completed Tesseract run instead of empty partial Paddle
    exp = client.post(
        f"/api/v1/books/{book_id}/exports",
        json={"format": "txt", "layout_mode": "page_preserving", "text_version": "raw_ocr"},
    )
    assert exp.status_code == 201
    dl = client.get(exp.json()["download_url"])
    assert dl.status_code == 200
    assert review["blocks"][0]["raw_text"] in dl.content.decode("utf-8")
