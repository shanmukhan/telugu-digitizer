"""Phase 4 tests for correction memory scope, context matching, conflicts, and governance."""

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
from sqlalchemy import text

from src.api.app import create_app
from src.core.config import AppSettings
from src.db.models import OCRBlock
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


def _build_pdf_with_text(line_text: str) -> bytes:
    font_path = _telugu_font_path()
    img = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 38)
    draw.text((40, 80), line_text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=216.0, height=62.4)
    page.insert_image(page.rect, stream=buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture()
def phase4_client(tmp_path: Path):
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


def test_phase4_scope_context_conflicts_and_governance(phase4_client) -> None:
    client, app, settings = phase4_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    # Upload two distinct books
    book_a_id = client.post(
        "/api/v1/books",
        files={"file": ("book_a.pdf", _build_pdf_with_text("పాఠశాల పరీక్ష 2026."), "application/pdf")},
        data={"title": "Book A"},
    ).json()["book_id"]

    book_b_id = client.post(
        "/api/v1/books",
        files={"file": ("book_b.pdf", _build_pdf_with_text("భాష మరియు లిపి 2026."), "application/pdf")},
        data={"title": "Book B"},
    ).json()["book_id"]

    # Run fast Tesseract baseline on both books
    for bid in (book_a_id, book_b_id):
        run = client.post(
            f"/api/v1/books/{bid}/ocr-runs",
            json={"engines": ["tesseract_tel_best"]},
        ).json()
        app.state.ocr_executor.wait_for_run(UUID(run["ocr_run_id"]), timeout=30.0)

    rev_a = client.get(f"/api/v1/books/{book_a_id}/pages/1/review").json()
    rev_b = client.get(f"/api/v1/books/{book_b_id}/pages/1/review").json()
    blk_a_id = rev_a["blocks"][0]["block_id"]
    blk_b_id = rev_b["blocks"][0]["block_id"]
    raw_b = rev_b["blocks"][0]["raw_text"]

    # Deterministic token anchor in Book B's OCR block so we test contextual suggestions safely
    with app.state.session_factory() as db:
        blk_a_row = db.get(OCRBlock, UUID(blk_a_id))
        blk_b_row = db.get(OCRBlock, UUID(blk_b_id))
        assert blk_a_row is not None and blk_b_row is not None
        blk_a_row.raw_text = "పాఠశాల పస్తకం బాగుంది"
        blk_b_row.raw_text = "పాఠశాల పస్తకం చదువు"
        db.commit()

    # 1. Save a book_only correction on Book A
    edit_book_only = client.post(
        f"/api/v1/ocr-blocks/{blk_a_id}/edits",
        json={
            "edited_text": "పాఠశాల పుస్తకం బాగుంది",
            "action": "corrected",
            "add_to_correction_memory": True,
            "memory_scope": "book_only",
            "correction_type": "vowel_sign",
        },
    )
    assert edit_book_only.status_code == 201
    cm_book_only_id = edit_book_only.json()["correction_memory_id"]
    assert cm_book_only_id is not None

    # Book B must NOT see Book A's book_only correction
    search_b_isolated = client.get(
        "/api/v1/corrections/search",
        params={"incorrect_text": "పస్తకం", "left_context": "పాఠశాల", "book_id": book_b_id},
    ).json()["items"]
    assert search_b_isolated == []

    # Book A DOES see its own book_only correction (single-side context -> medium; both sides -> strong)
    search_a_partial = client.get(
        "/api/v1/corrections/search",
        params={"incorrect_text": "పస్తకం", "left_context": "పాఠశాల", "book_id": book_a_id},
    ).json()["items"]
    assert len(search_a_partial) == 1
    assert search_a_partial[0]["corrected_text"] == "పుస్తకం"
    assert search_a_partial[0]["context_match"] == "medium"

    search_a_full = client.get(
        "/api/v1/corrections/search",
        params={
            "incorrect_text": "పస్తకం",
            "left_context": "పాఠశాల",
            "right_context": "బాగుంది",
            "book_id": book_a_id,
        },
    ).json()["items"]
    assert len(search_a_full) == 1
    assert search_a_full[0]["context_match"] == "strong"

    # 2. Save a global_suggestion with different corrected form -> conflict must coexist!
    edit_global = client.post(
        f"/api/v1/ocr-blocks/{blk_a_id}/edits",
        json={
            "edited_text": "పాఠశాల పత్రకం బాగుంది",
            "action": "corrected",
            "add_to_correction_memory": True,
            "memory_scope": "global_suggestion",
            "incorrect_span": "పస్తకం",
            "corrected_span": "పత్రకం",
        },
    )
    assert edit_global.status_code == 201
    cm_global_id = edit_global.json()["correction_memory_id"]

    # Book A sees both conflicting entries (book_only + global_suggestion)
    conflict_search = client.get(
        "/api/v1/corrections/search",
        params={"incorrect_text": "పస్తకం", "left_context": "పాఠశాల", "book_id": book_a_id},
    ).json()["items"]
    assert len(conflict_search) == 2
    assert all(item["has_conflict"] is True for item in conflict_search)

    # Book B sees only global_suggestion AND Book B's block text is NOT silently overwritten!
    rev_b_after = client.get(f"/api/v1/books/{book_b_id}/pages/1/review").json()
    blk_b_view = rev_b_after["blocks"][0]
    assert blk_b_view["current_text"] == "పాఠశాల పస్తకం చదువు"
    assert len(blk_b_view["suggestions"]) == 1
    assert blk_b_view["suggestions"][0]["correction_id"] == cm_global_id
    assert blk_b_view["suggestions"][0]["proposed_block_text"] == "పాఠశాల పత్రకం చదువు"

    # 3. Approve and Reject evidence counters are preserved
    approved = client.post(f"/api/v1/corrections/{cm_global_id}/approve").json()
    assert approved["approved_count"] == 2

    rejected = client.post(
        f"/api/v1/corrections/{cm_global_id}/reject",
        json={"disable": False},
    ).json()
    assert rejected["rejected_count"] == 1
    assert rejected["status"] == "active"

    # 4. Disabling hides from active search/suggestions while preserving audit record
    disabled = client.patch(
        f"/api/v1/corrections/{cm_global_id}/status",
        json={"status": "disabled"},
    ).json()
    assert disabled["status"] == "disabled"

    rev_b_disabled = client.get(f"/api/v1/books/{book_b_id}/pages/1/review").json()
    assert rev_b_disabled["blocks"][0]["suggestions"] == []

    all_records = client.get("/api/v1/corrections").json()["items"]
    assert any(r["correction_id"] == cm_global_id and r["rejected_count"] == 1 for r in all_records)
    _ = raw_b
