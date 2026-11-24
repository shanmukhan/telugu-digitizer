"""Phase 5 tests for editable-flow DOCX, page-preserving DOCX, UTF-8 TXT, and manifests."""

from __future__ import annotations

import io
import os
from pathlib import Path
from uuid import UUID

import docx
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
    pytest.skip("No Telugu system font available.")
    return ""


def _build_two_page_scanned_pdf() -> bytes:
    font_path = _telugu_font_path()
    doc = pymupdf.open()
    for line in ("తెలుగు మొదటి పుట", "తెలుగు రెండవ పుట"):
        img = Image.new("RGB", (900, 260), "white")
        draw = ImageDraw.Draw(img)
        font = ImageFont.truetype(font_path, 38)
        draw.text((40, 80), line, fill="black", font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page = doc.new_page(width=216.0, height=62.4)
        page.insert_image(page.rect, stream=buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture()
def phase5_client(tmp_path: Path):
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


def test_phase5_docx_and_txt_exports_and_validation(phase5_client) -> None:
    client, app, settings = phase5_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    pdf_bytes = _build_two_page_scanned_pdf()
    book_id = client.post(
        "/api/v1/books",
        files={"file": ("export_book.pdf", pdf_bytes, "application/pdf")},
        data={"title": "తెలుగు ఎగుమతి పుస్తకం", "author": "Author Name"},
    ).json()["book_id"]

    run_resp = client.post(
        f"/api/v1/books/{book_id}/ocr-runs",
        json={"engines": ["tesseract_tel_best"]},
    ).json()
    app.state.ocr_executor.wait_for_run(UUID(run_resp["ocr_run_id"]), timeout=30.0)

    rev_p1 = client.get(f"/api/v1/books/{book_id}/pages/1/review").json()
    rev_p2 = client.get(f"/api/v1/books/{book_id}/pages/2/review").json()
    raw_p1 = rev_p1["blocks"][0]["raw_text"]

    # Human-correct page 1 and approve both pages
    edited_p1 = "తెలుగు మొదటి పుట (ధృవీకరించబడింది)"
    edited_p2 = "తెలుగు రెండవ పుట (ధృవీకరించబడింది)"
    client.post(
        f"/api/v1/ocr-blocks/{rev_p1['blocks'][0]['block_id']}/edits",
        json={"edited_text": edited_p1, "action": "corrected"},
    )
    client.post(
        f"/api/v1/ocr-blocks/{rev_p2['blocks'][0]['block_id']}/edits",
        json={"edited_text": edited_p2, "action": "corrected"},
    )
    client.patch(
        f"/api/v1/books/{book_id}/pages/1/review-status",
        json={"review_status": "approved", "primary_run_id": rev_p1["primary_run_id"]},
    )
    client.patch(
        f"/api/v1/books/{book_id}/pages/2/review-status",
        json={"review_status": "approved", "primary_run_id": rev_p2["primary_run_id"]},
    )

    # 1. Page-preserving DOCX (human_approved)
    exp_pp = client.post(
        f"/api/v1/books/{book_id}/exports",
        json={
            "format": "docx",
            "layout_mode": "page_preserving",
            "text_version": "human_approved",
            "font_family": "Noto Serif Telugu",
            "include_page_numbers": True,
        },
    )
    assert exp_pp.status_code == 201
    pp_meta = exp_pp.json()
    assert pp_meta["is_fully_reviewed"] is True
    assert pp_meta["validation"]["passed"] is True
    assert pp_meta["validation"]["page_breaks_verified"] == 1
    assert pp_meta["filename"].endswith("_page-preserving.docx")

    pp_dl = client.get(pp_meta["download_url"])
    assert pp_dl.status_code == 200
    reopened_pp = docx.Document(io.BytesIO(pp_dl.content))
    pp_texts = [p.text for p in reopened_pp.paragraphs if p.text.strip()]
    assert edited_p1 in pp_texts
    assert edited_p2 in pp_texts
    assert len(reopened_pp.element.body.xpath(".//w:br[@w:type='page']")) == 1

    # 2. Editable-flow DOCX (human_approved + TOC)
    exp_ef = client.post(
        f"/api/v1/books/{book_id}/exports",
        json={
            "format": "docx",
            "layout_mode": "editable_flow",
            "text_version": "human_approved",
            "include_table_of_contents": True,
        },
    )
    assert exp_ef.status_code == 201
    ef_meta = exp_ef.json()
    assert ef_meta["filename"].endswith("_editable-flow.docx")
    ef_dl = client.get(ef_meta["download_url"])
    assert ef_dl.status_code == 200
    reopened_ef = docx.Document(io.BytesIO(ef_dl.content))
    assert reopened_ef.core_properties.title == "తెలుగు ఎగుమతి పుస్తకం"
    assert reopened_ef.core_properties.author == "Author Name"
    ef_texts = [p.text for p in reopened_ef.paragraphs if p.text.strip()]
    assert edited_p1 in ef_texts
    assert edited_p2 in ef_texts

    # 3. Raw OCR DOCX keeps original raw text and labels as unreviewed
    exp_raw = client.post(
        f"/api/v1/books/{book_id}/exports",
        json={
            "format": "docx",
            "layout_mode": "editable_flow",
            "text_version": "raw_ocr",
        },
    )
    assert exp_raw.status_code == 201
    raw_meta = exp_raw.json()
    assert raw_meta["is_fully_reviewed"] is False
    reopened_raw = docx.Document(io.BytesIO(client.get(raw_meta["download_url"]).content))
    raw_texts = [p.text for p in reopened_raw.paragraphs if p.text.strip()]
    assert any("UNREVIEWED MACHINE OCR OUTPUT" in t for t in raw_texts)
    assert raw_p1 in raw_texts
    assert edited_p1 not in raw_texts

    # 4. UTF-8 TXT export preserves form-feed page delimiter & omits metadata/confidences
    exp_txt = client.post(
        f"/api/v1/books/{book_id}/exports",
        json={"format": "txt", "layout_mode": "page_preserving", "text_version": "human_approved"},
    )
    assert exp_txt.status_code == 201
    txt_meta = exp_txt.json()
    txt_dl = client.get(txt_meta["download_url"])
    assert txt_dl.status_code == 200
    txt_body = txt_dl.content.decode("utf-8")
    assert "\f" in txt_body
    assert edited_p1 in txt_body and edited_p2 in txt_body

    # 5. Export manifest sidecar & list endpoints
    manifest_resp = client.get(txt_meta["manifest_url"])
    assert manifest_resp.status_code == 200
    manifest_json = manifest_resp.json()
    assert manifest_json["included_pages"] == [1, 2]
    assert manifest_json["reviewed_pages"] == [1, 2]
    assert manifest_json["validation"]["passed"] is True

    list_resp = client.get(f"/api/v1/books/{book_id}/exports")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["items"]) == 4

    meta_resp = client.get(f"/api/v1/exports/{pp_meta['export_id']}")
    assert meta_resp.status_code == 200
    assert meta_resp.json()["export_id"] == pp_meta["export_id"]


def test_phase5_export_rejected_when_no_ocr_run_exists(phase5_client) -> None:
    """Exporting a scanned book before running any OCR must return 409 NO_OCR_RUN_AVAILABLE."""
    import io

    import pymupdf
    from PIL import Image

    client = phase5_client[0] if isinstance(phase5_client, tuple) else phase5_client

    img = Image.new("RGB", (400, 200), "white")
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=200.0, height=100.0)
    page.insert_image(page.rect, stream=img_buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()

    upload_resp = client.post(
        "/api/v1/books",
        files={"file": ("no_ocr_yet.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Unprocessed Scanned Book"},
    )
    assert upload_resp.status_code == 201
    book_id = upload_resp.json()["book_id"]

    for text_version in ("raw_ocr", "human_approved"):
        export_resp = client.post(
            f"/api/v1/books/{book_id}/exports",
            json={
                "format": "docx",
                "layout_mode": "page_preserving",
                "text_version": text_version,
                "font_family": "Noto Serif Telugu",
                "include_page_numbers": True,
            },
        )
        assert export_resp.status_code == 409
        body = export_resp.json()
        assert body["error"]["code"] == "NO_OCR_RUN_AVAILABLE"
