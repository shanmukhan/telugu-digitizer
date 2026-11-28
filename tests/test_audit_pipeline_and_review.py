"""Regression tests for ARCH-01, ARCH-02, PERF-01, PERF-02, PERF-04, PERF-06, OCR-01..05, and TEST-01."""

from __future__ import annotations

import os
import subprocess
import threading
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.compiler import compiles

from src.api.app import create_app
from src.common.cache_state import bump_sentence_context_epoch
from src.core.config import AppSettings
from src.db.models import Base, BookPage, DocumentExport, OCRBlock, OCRRun
from src.db.session import build_engine, build_session_factory
from src.evaluation.metrics import aggregate_metrics
from src.ocr.base import OCRProvider
from src.ocr.layout import order_ocr_blocks_geometrically
from src.ocr.tesseract_provider import TesseractOCRProvider
from src.services.correction_service import find_block_suggestions_from_index
from src.services.export_service import create_book_export
from src.services.lexicon_service import (
    SentenceContextModel,
    TeluguLexicon,
    _autocorrect_single_block,
    build_sentence_context_model,
)
from src.services.review_service import batch_save_and_approve_page, get_page_review_payload

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


def _prepare_db_and_settings(tmp_path: Path, **overrides) -> tuple[str, AppSettings]:
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
        db_url = TEST_DB_URL
    else:
        db_url = f"sqlite:///{(tmp_path / 'audit_pipeline.db').resolve()}"
        sq_engine = create_engine(db_url)
        Base.metadata.create_all(sq_engine)
        sq_engine.dispose()

    defaults = dict(
        database_url=db_url,
        workspace_dir=(tmp_path / "workspace").resolve(),
        tessdata_dir=(repo_root / "models" / "tesseract" / "tessdata").resolve(),
        tesseract_cmd=None,
        api_host="127.0.0.1",
        api_port=8000,
        max_upload_mb=50,
        max_pdf_pages=200,
        default_render_dpi=300,
        paddle_device="cpu",
        allow_guest_ocr=True,
        enable_paddle_ocr=False,
        prewarm_lexicon=False,
    )
    defaults.update(overrides)
    return db_url, AppSettings(**defaults)


def _make_mixed_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    try:
        # Page 1: pure digital text (>120 chars, no images)
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text(
            (50, 72),
            "Digital Born Page Content For Export And Editing Verification. " * 4,
            fontsize=11,
        )
        # Page 2: scanned image page
        p2 = doc.new_page(width=595, height=842)
        img = Image.new("RGB", (400, 200), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle((20, 20, 380, 70), outline="black", width=2)
        img_path = path.parent / "scan_tmp.png"
        img.save(img_path)
        p2.insert_image(pymupdf.Rect(20, 20, 420, 220), filename=str(img_path))
        doc.save(str(path))
    finally:
        doc.close()
    return path


class _MockTesseractProvider(OCRProvider):
    engine_name = "tesseract"

    def __init__(self, *, blocks: list[dict] | None = None, started: threading.Event | None = None, release: threading.Event | None = None):
        self._blocks = blocks or [
            {
                "block_index": 0,
                "reading_order": 0,
                "block_type": "line",
                "text": "అమ్మ నాన్న",
                "confidence": 88.5,
                "bbox": [20.0, 40.0, 220.0, 80.0],
                "polygon": [[20.0, 40.0], [220.0, 40.0], [220.0, 80.0], [20.0, 80.0]],
            }
        ]
        self._started = started
        self._release = release

    def provider_metadata(self) -> dict:
        return {
            "engine": "tesseract",
            "engine_version": "5.5.4",
            "model_id": "tesseract-5-tel-best",
            "model_version_or_checksum": "test-sha",
            "config": {"psm": 6},
        }

    def recognize(self, image_path: str | Path) -> dict:
        _ = image_path
        if self._started is not None:
            self._started.set()
        if self._release is not None:
            self._release.wait(timeout=5.0)
        text_joined = "\n".join(b["text"] for b in self._blocks)
        return {
            "engine": "tesseract",
            "engine_version": "5.5.4",
            "model_id": "tesseract-5-tel-best",
            "config": {"psm": 6},
            "elapsed_ms": 12.0,
            "cold_start_ms": None,
            "text": text_joined,
            "blocks": list(self._blocks),
            "raw_payload": {"txt": text_joined, "tsv": ""},
        }


def test_arch01_digital_text_patch_and_manual_bbox_review(tmp_path: Path, monkeypatch) -> None:
    _, settings = _prepare_db_and_settings(tmp_path)
    pdf_path = _make_mixed_pdf(tmp_path / "mixed.pdf")
    monkeypatch.setattr(
        "src.services.ocr_service.build_ocr_provider",
        lambda canonical_engine, _settings, tesseract_psm=6: _MockTesseractProvider(),
    )

    app = create_app(settings)
    with TestClient(app) as client:
        with pdf_path.open("rb") as fh:
            imp = client.post(
                "/api/v1/books",
                data={"title": "Mixed Digital & Scanned Book"},
                files={"file": ("mixed.pdf", fh, "application/pdf")},
            )
        assert imp.status_code == 201, imp.text
        book_id = imp.json()["book_id"]

        # ARCH-01(a): PATCH /digital-text with { "text": ... } updates page and status
        patch_res = client.patch(
            f"/api/v1/books/{book_id}/pages/1/digital-text",
            json={"text": "డిజిటల్ పేజీ సవరణ"},
        )
        assert patch_res.status_code == 200, patch_res.text
        pdata = patch_res.json()
        assert pdata["text"] == "డిజిటల్ పేజీ సవరణ"
        assert pdata["review_status"] == "in_review"

        # Start mock OCR run on page 2
        run_res = client.post(
            f"/api/v1/books/{book_id}/ocr-runs",
            json={"engines": ["tesseract"]},
        )
        assert run_res.status_code == 202, run_res.text
        run_id = str(run_res.json()["ocr_run_id"])
        app.state.ocr_executor.wait_for_run(uuid.UUID(run_id), timeout=10.0)

        # ARCH-01(b): POST /blocks accepts bbox & primary_run_id and appears in review payload
        blk_res = client.post(
            f"/api/v1/books/{book_id}/pages/2/blocks",
            json={
                "text": "అధ్యాయం ఒకటి",
                "block_role": "heading_1",
                "bbox": [12.0, 95.0, 240.0, 130.0],
                "primary_run_id": run_id,
            },
        )
        assert blk_res.status_code == 201, blk_res.text
        bdata = blk_res.json()
        assert bdata["ocr_run_id"] == run_id

        rev = client.get(f"/api/v1/books/{book_id}/pages/2/review")
        assert rev.status_code == 200
        blocks = rev.json()["blocks"]
        assert any(b["block_id"] == bdata["block_id"] and b["bbox"] == [12.0, 95.0, 240.0, 130.0] for b in blocks)


def test_arch02_and_perf04_delete_cleanup_and_duplicate_run_guards(tmp_path: Path, monkeypatch) -> None:
    _, settings = _prepare_db_and_settings(tmp_path)
    pdf_path = _make_mixed_pdf(tmp_path / "guard.pdf")
    started = threading.Event()
    release = threading.Event()
    monkeypatch.setattr(
        "src.services.ocr_service.build_ocr_provider",
        lambda canonical_engine, _settings, tesseract_psm=6: _MockTesseractProvider(started=started, release=release),
    )

    app = create_app(settings)
    with TestClient(app) as client:
        with pdf_path.open("rb") as fh:
            book_id = client.post(
                "/api/v1/books",
                data={"title": "Concurrency Guard Book"},
                files={"file": ("guard.pdf", fh, "application/pdf")},
            ).json()["book_id"]

        crop_dir = settings.workspace_dir / "training_crops" / book_id
        crop_dir.mkdir(parents=True, exist_ok=True)
        (crop_dir / "sample.png").write_bytes(b"png")

        first = client.post(
            f"/api/v1/books/{book_id}/ocr-runs",
            json={"engines": ["tesseract"], "force_rerun": True},
        )
        assert first.status_code == 202
        run_id = str(first.json()["ocr_run_id"])
        assert started.wait(timeout=5.0)

        # Duplicate OCR start while active must reuse active run instead of spawning a second worker
        dup = client.post(
            f"/api/v1/books/{book_id}/ocr-runs",
            json={"engines": ["tesseract"], "force_rerun": True},
        )
        assert dup.status_code == 202
        assert str(dup.json()["ocr_run_id"]) == run_id

        # Resuming an actively running run is idempotent and does not spawn a duplicate worker
        res_running = client.post(f"/api/v1/ocr-runs/{run_id}/resume")
        assert res_running.status_code == 202
        assert str(res_running.json()["ocr_run_id"]) == run_id
        assert res_running.json()["status"] in ("running", "queued")

        # Cancelling while running + deleting book cleanly cleans training_crops
        cancel_res = client.post(f"/api/v1/ocr-runs/{run_id}/cancel")
        assert cancel_res.status_code == 200
        release.set()
        app.state.ocr_executor.wait_for_run(uuid.UUID(run_id), timeout=5.0)

        del_res = client.delete(f"/api/v1/books/{book_id}")
        assert del_res.status_code == 204
        assert not crop_dir.exists()


def test_perf06_tesseract_timeout_raises_clean_runtime_error(tmp_path: Path, monkeypatch) -> None:
    tess_dir = tmp_path / "tessdata"
    tess_dir.mkdir()
    (tess_dir / "tel.traineddata").write_bytes(b"stub")
    img_path = tmp_path / "page.png"
    Image.new("RGB", (60, 40), "white").save(img_path)

    provider = TesseractOCRProvider(
        tessdata_dir=tess_dir,
        tesseract_cmd="echo",
        timeout_sec=1.0,
    )

    def _raise_timeout(*args, **kwargs):
        _ = (args, kwargs)
        raise subprocess.TimeoutExpired(cmd="tesseract", timeout=1.0)

    monkeypatch.setattr("src.ocr.tesseract_provider.subprocess.run", _raise_timeout)
    with pytest.raises(TimeoutError, match="timed out"):
        provider.recognize(img_path)


def test_perf01_perf02_and_ocr05_sql_budget_cache_and_bbox_comparator(tmp_path: Path, monkeypatch) -> None:
    db_url, settings = _prepare_db_and_settings(tmp_path)
    pdf_path = _make_mixed_pdf(tmp_path / "perf.pdf")
    many_blocks = [
        {
            "block_index": i,
            "reading_order": i,
            "block_type": "line",
            "text": f"పదము {i}",
            "confidence": 92.0,
            "bbox": [20.0, 20.0 + i * 35.0, 240.0, 48.0 + i * 35.0],
            "polygon": [
                [20.0, 20.0 + i * 35.0],
                [240.0, 20.0 + i * 35.0],
                [240.0, 48.0 + i * 35.0],
                [20.0, 48.0 + i * 35.0],
            ],
        }
        for i in range(10)
    ]
    monkeypatch.setattr(
        "src.services.ocr_service.build_ocr_provider",
        lambda canonical_engine, _settings, tesseract_psm=6: _MockTesseractProvider(blocks=many_blocks),
    )

    app = create_app(settings)
    with TestClient(app) as client:
        with pdf_path.open("rb") as fh:
            book_id = client.post(
                "/api/v1/books",
                data={"title": "Perf & Export Book"},
                files={"file": ("perf.pdf", fh, "application/pdf")},
            ).json()["book_id"]

        run_resp = client.post(f"/api/v1/books/{book_id}/ocr-runs", json={"engines": ["tesseract"]})
        assert run_resp.status_code == 202
        app.state.ocr_executor.wait_for_run(uuid.UUID(str(run_resp.json()["ocr_run_id"])), timeout=10.0)

        engine = build_engine(db_url)
        session_factory = build_session_factory(engine)
        try:
            with session_factory() as db:
                book_uuid = uuid.UUID(book_id)
                # PERF-01: context cache returns identical object until epoch bumps
                m1 = build_sentence_context_model(db=db, book_id=book_uuid, use_cache=True)
                m2 = build_sentence_context_model(db=db, book_id=book_uuid, use_cache=True)
                assert m1 is m2
                bump_sentence_context_epoch()
                m3 = build_sentence_context_model(db=db, book_id=book_uuid, use_cache=True)
                assert m3 is not m1

                # PERF-02: batch_save_and_approve_page executes in bounded O(1) SQL queries (<=25)
                rev_before = get_page_review_payload(db=db, book_id=book_uuid, page_number=2)
                edits = [
                    {
                        "block_id": b["block_id"],
                        "edited_text": f"సవరణ {idx}",
                        "action": "corrected",
                        "block_role": "verse" if idx == 0 else ("heading_1" if idx == 1 else "paragraph"),
                        "add_to_correction_memory": False,
                    }
                    for idx, b in enumerate(rev_before["blocks"])
                ]
                query_count = 0

                def _count_sql(*args):
                    _ = args
                    nonlocal query_count
                    query_count += 1

                event.listen(engine, "before_cursor_execute", _count_sql)
                try:
                    batch_save_and_approve_page(
                        db=db,
                        storage=None,
                        book_id=book_uuid,
                        page_number=2,
                        edits=edits,
                        approve_remaining_blocks=True,
                        mark_page_approved=True,
                    )
                finally:
                    event.remove(engine, "before_cursor_execute", _count_sql)
                assert query_count <= 25, f"Expected <=25 SQL statements, got {query_count}"

                # OCR-05: non-overlapping comparator block does NOT blindly match by block_index
                page2 = db.scalars(select(BookPage).where(BookPage.book_id == book_uuid, BookPage.page_number == 2)).one()
                comp_run = OCRRun(book_id=book_uuid, status="completed", idempotency_key="comp-run")
                db.add(comp_run)
                db.flush()
                db.add(
                    OCRBlock(
                        ocr_run_id=comp_run.id,
                        book_page_id=page2.id,
                        block_index=0,
                        reading_order=0,
                        block_type="line",
                        raw_text="పూర్తిగా వేరే లైన్",
                        normalized_text="పూర్తిగా వేరే లైన్",
                        confidence=90.0,
                        polygon=[[20.0, 700.0], [250.0, 700.0], [250.0, 740.0], [20.0, 740.0]],
                    )
                )
                db.commit()

                rev_comp = get_page_review_payload(
                    db=db,
                    book_id=book_uuid,
                    page_number=2,
                    primary_run_id=rev_before["primary_run_id"],
                    comparator_run_id=comp_run.id,
                )
                assert rev_comp["blocks"][0]["comparator_text"] is None
                assert rev_comp["blocks"][0]["disagreement_flag"] is False

                # OCR-03: inject XML-illegal control chars (\x01, \x0b, \x0c) allowed by PG, verify DOCX export strips & sets TeluguVerse + w:cs
                batch_save_and_approve_page(
                    db=db,
                    storage=None,
                    book_id=book_uuid,
                    page_number=2,
                    edits=[
                        {
                            "block_id": rev_before["blocks"][2]["block_id"],
                            "edited_text": "\x01\x0b\x0cఅమ్మ\t\nనాన్న",
                            "action": "corrected",
                            "block_role": "paragraph",
                            "add_to_correction_memory": False,
                        }
                    ],
                )
                storage = app.state.storage
                export_rec = create_book_export(
                    db=db,
                    storage=storage,
                    book_id=book_uuid,
                    export_format="docx",
                    text_version="human_approved",
                )
                docx_file = settings.workspace_dir / export_rec.storage_key
                assert docx_file.is_file()
                with zipfile.ZipFile(docx_file, "r") as zf:
                    doc_xml = zf.read("word/document.xml").decode("utf-8")
                    ET.fromstring(doc_xml)
                    assert "TeluguVerse" in doc_xml
                    assert 'w:cs="Noto Serif Telugu"' in doc_xml
                    assert 'w:bidi="te-IN"' in doc_xml
                    assert "అమ్మ" in doc_xml and "నాన్న" in doc_xml
        finally:
            engine.dispose()


def test_ocr01_layout_single_and_two_column_reading_order() -> None:
    single = order_ocr_blocks_geometrically(
        [
            {"text": "line 3", "bbox": [40, 200, 400, 230]},
            {"text": "line 1", "bbox": [40, 20, 400, 50]},
            {"text": "line 2", "bbox": [40, 110, 400, 140]},
        ]
    )
    assert [b["text"] for b in single] == ["line 1", "line 2", "line 3"]
    assert [b["reading_order"] for b in single] == [0, 1, 2]

    two_col = order_ocr_blocks_geometrically(
        [
            {"text": "R1", "bbox": [480, 30, 820, 65]},
            {"text": "L2", "bbox": [40, 120, 380, 155]},
            {"text": "R2", "bbox": [480, 120, 820, 155]},
            {"text": "L1", "bbox": [40, 30, 380, 65]},
            {"text": "L3", "bbox": [40, 210, 380, 245]},
            {"text": "R3", "bbox": [480, 210, 820, 245]},
        ]
    )
    assert [b["text"] for b in two_col] == ["L1", "L2", "L3", "R1", "R2", "R3"]


def test_ocr02_telugu_joiners_preservation_and_newline_retention() -> None:
    lex = TeluguLexicon(
        entries=[
            ("పూచెన్", 500, "dict"),
            ("తెలుగు", 5000, "dict"),
            ("పుస్తకం", 4000, "dict"),
        ]
    )
    # Valid classical nakara-pollu should remain known
    assert lex.is_known_word("పూచెన్")
    # Spurious ZWNJ inside తెలుగు repairs cleanly to తెలుగు
    repaired = lex.suggest_word("తెలు\u200cగు", min_confidence=0.7)
    assert repaired is not None
    assert repaired["replacement"] == "తెలుగు"

    # Autocorrect and correction memory preserve intra-block newlines
    class _Mem:
        id = uuid.uuid4()
        book_id = None
        scope = "global_suggestion"
        status = "active"
        correction_type = "ocr_substitution"
        incorrect_text = "పస్తకం"
        corrected_text = "పుస్తకం"
        left_context = None
        right_context = None
        usage_count = 3
        approved_count = 3
        rejected_count = 0
        confidence = 0.99

    fixed, _changes = _autocorrect_single_block(
        block_text="తెలు\u200cగు\nపస్తకం",
        book_id=uuid.uuid4(),
        by_incorrect={"పస్తకం": [_Mem()]},
        books_by_pair={("పస్తకం", "పుస్తకం"): {uuid.uuid4()}},
        lexicon=lex,
        context_model=SentenceContextModel(),
        use_correction_memory=True,
        use_dictionary=True,
        use_sentence_context=True,
        min_confidence=0.7,
    )
    assert fixed == "తెలుగు\nపుస్తకం"

    sugs = find_block_suggestions_from_index(
        by_incorrect={"పస్తకం": [_Mem()]},
        books_by_pair={("పస్తకం", "పుస్తకం"): {uuid.uuid4()}},
        block_text="లైన్\nపస్తకం",
        book_id=uuid.uuid4(),
    )
    assert len(sugs) == 1
    assert sugs[0]["corrected_text"] == "పుస్తకం"


def test_test01_aggregate_metrics_computes_p95_sec_per_page() -> None:
    rows = [
        {
            "status": "completed",
            "scored": True,
            "elapsed_ms": ms,
            "raw_edits": 0,
            "raw_ref_chars": 10,
            "nfc_edits": 0,
            "nfc_ref_chars": 10,
            "ws_nfc_edits": 0,
            "ws_nfc_ref_chars": 10,
            "word_edits": 0,
            "ref_words": 2,
            "grapheme_edits": 0,
            "ref_graphemes": 5,
            "exact_line_matches": 1,
            "ref_lines": 1,
        }
        for ms in (1000.0, 2000.0, 3000.0, 4000.0, 10000.0)
    ]
    agg = aggregate_metrics(rows)
    assert agg["mean_sec_per_page"] == 4.0
    assert agg["median_sec_per_page"] == 3.0
    assert agg["p95_sec_per_page"] == 8.8
