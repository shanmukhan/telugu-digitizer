"""Tests for Telugu lexicon auto-correction, sentence context disambiguation, noise guard, and batch-save."""

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
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.compiler import compiles

from src.api.app import create_app
from src.core.config import AppSettings
from src.db.models import Base, BookPage, ModelRegistry, OCRBlock, OCRRun
from src.db.session import build_engine
from src.services.correction_service import extract_word_level_corrections, is_safe_auto_memory_rule
from src.services.lexicon_service import (
    SentenceContextModel,
    TeluguLexicon,
    _autocorrect_single_block,
    get_telugu_lexicon,
)
from src.services.ocr_service import ALLOWED_PREPROCESSING_PROFILES, OCRJobExecutor

@compiles(postgresql.JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@compiles(postgresql.UUID, "sqlite")
def _compile_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(36)"

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://telugu_digitizer:telugu_digitizer@127.0.0.1:5432/telugu_digitizer_test",
)


def test_noise_guard_and_word_level_extraction() -> None:
    """Real line edit 'గ అష్టాదశవర్ధనలు - ర్మ' -> 'అష్టాదశవర్ణనలు - 43' keeps Telugu fix and drops digit noise."""
    pairs = extract_word_level_corrections("గ అష్టాదశవర్ధనలు - ర్మ", "అష్టాదశవర్ణనలు - 43")
    safe = [(inc, cor) for inc, cor, _, _ in pairs if is_safe_auto_memory_rule(inc, cor)[0]]
    skipped = [(inc, cor) for inc, cor, _, _ in pairs if not is_safe_auto_memory_rule(inc, cor)[0]]
    assert ("అష్టాదశవర్ధనలు", "అష్టాదశవర్ణనలు") in safe
    assert ("ర్మ", "43") in skipped

    assert is_safe_auto_memory_rule("పస్తకం", "పుస్తకం") == (True, None)
    assert is_safe_auto_memory_rule("ర్మ", "43")[0] is False
    assert is_safe_auto_memory_rule("12", "43")[0] is False
    assert is_safe_auto_memory_rule("ఒక రెండు మూడు నాలుగు", "ఐదు ఆరు ఏడు ఎనిమిది")[0] is False


def test_real_telugu_lexicon_ocr_confusions_and_compounds() -> None:
    """Built local Telugu lexicon fixes real OCR errors while leaving valid classical words untouched."""
    lex = get_telugu_lexicon()
    assert len(lex.words) >= 100_000

    # Valid classical literary book title must remain untouched
    assert lex.is_known_word("ఆముక్తమాల్యద") is True
    assert lex.suggest_word("ఆముక్తమాల్యద") is None

    # Compound OCR confusion from Amuktamalyada screenshot (ధ -> ణ)
    prop_compound = lex.suggest_word("అష్టాదశవర్ధనలు")
    assert prop_compound is not None
    assert prop_compound["replacement"] == "అష్టాదశవర్ణనలు"
    assert prop_compound["confidence"] >= 0.85

    # Missing vowel sign (పస్తకం -> పుస్తకం)
    prop_matra = lex.suggest_word("పస్తకం")
    assert prop_matra is not None
    assert prop_matra["replacement"] == "పుస్తకం"

    # Dropped rakara-vattu + బ↔భ + గ↔థ heading error: '(పగమబాగం- 1' -> 'ప్రథమభాగం- 1'
    prop_vattu = lex.suggest_word("పగమబాగం")
    assert prop_vattu is not None
    assert prop_vattu["replacement"] == "ప్రథమభాగం"

    fixed_line, line_changes = _autocorrect_single_block(
        block_text="(పగమబాగం- 1",
        book_id=UUID("00000000-0000-0000-0000-000000000001"),
        by_incorrect={},
        books_by_pair={},
        lexicon=lex,
        context_model=None,
        use_correction_memory=False,
        use_dictionary=True,
        use_sentence_context=False,
        min_confidence=0.78,
    )
    assert fixed_line == "ప్రథమభాగం- 1"
    assert len(line_changes) == 1
    assert line_changes[0]["confidence"] >= 0.90

    # Short unmatched leading '(' + unknown Telugu word (e.g., '(పజా' -> 'ప్రజా')
    short_line, short_changes = _autocorrect_single_block(
        block_text="(పజా పాలన",
        book_id=UUID("00000000-0000-0000-0000-000000000001"),
        by_incorrect={},
        books_by_pair={},
        lexicon=lex,
        context_model=None,
        use_correction_memory=False,
        use_dictionary=True,
        use_sentence_context=False,
        min_confidence=0.78,
    )
    assert short_line == "ప్రజా పాలన"
    assert len(short_changes) == 1

    # Balanced parentheses around a valid word must NEVER be stripped
    balanced_line, balanced_changes = _autocorrect_single_block(
        block_text="(ప్రథమభాగం) - 1",
        book_id=UUID("00000000-0000-0000-0000-000000000001"),
        by_incorrect={},
        books_by_pair={},
        lexicon=lex,
        context_model=None,
        use_correction_memory=False,
        use_dictionary=True,
        use_sentence_context=False,
        min_confidence=0.78,
    )
    assert balanced_line == "(ప్రథమభాగం) - 1"
    assert balanced_changes == []


def test_textured_bold_preprocessing_profile_generates_clean_png(tmp_path: Path) -> None:
    """textured_bold profile is registered and outputs a valid derived PNG without mutating source."""
    assert "textured_bold" in ALLOWED_PREPROCESSING_PROFILES
    from src.core.storage import LocalFilesystemStorage

    storage = LocalFilesystemStorage(tmp_path)
    img = Image.new("RGB", (320, 120), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 30, 280, 90], fill="black")
    # Simulate white halftone stippling inside bold strokes
    for x in range(44, 276, 6):
        draw.point((x, 60), fill="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    src_key = "pages/test/page-0001.png"
    src_path = storage.write_bytes(src_key, buf.getvalue(), read_only=False)

    executor = OCRJobExecutor(
        session_factory=None,  # type: ignore[arg-type]
        storage=storage,
        settings=None,  # type: ignore[arg-type]
    )
    try:
        out_path, out_key, _sha, out_w, out_h = executor._apply_preprocessing_profile(
            img_path=src_path,
            img_key=src_key,
            img_sha="dummy",
            img_w=320,
            img_h=120,
            book_id=UUID("00000000-0000-0000-0000-000000000002"),
            page_number=1,
            render_dpi=300,
            profile="textured_bold",
        )
        assert out_path.is_file()
        assert "pre-textured_bold-dpi-300" in out_key
        assert out_w == 320 and out_h == 120
    finally:
        executor.shutdown(wait=False)


def test_sentence_bigram_context_disambiguates_candidates() -> None:
    """When two lexicon candidates are equidistant, sentence/bigram context selects the natural sentence word."""
    lex = TeluguLexicon(
        entries=[
            ("వనం", 100, "L"),
            ("ధనం", 100, "L"),
            ("మంచి", 500, "L"),
            ("రాజు", 500, "L"),
        ]
    )
    # Without context, 'భనం' is visually close to 'ధనం' (tight pair భ↔ధ) vs 'వనం'.
    # Test an exact tie: two equally weighted words 'పటము' and 'వటము' (ప↔వ) for OCR typo 'హటము'
    tie_lex = TeluguLexicon(
        entries=[
            ("పటము", 200, "L"),
            ("వటము", 200, "L"),
            ("మర్రి", 300, "L"),
            ("చిత్ర", 300, "L"),
        ]
    )
    assert tie_lex.suggest_word("హటము") is None  # Ambiguous tie skipped without context

    ctx = SentenceContextModel()
    ctx.add_sentence("చిత్ర పటము బాగుంది", same_book=True, weight=3)
    prop = tie_lex.suggest_word("హటము", prev_word="చిత్ర", context=ctx, use_sentence_context=True)
    assert prop is not None
    assert prop["replacement"] == "పటము"
    assert prop["source"] == "sentence_context"


def _minimal_pdf_bytes() -> bytes:
    img = Image.new("RGB", (600, 180), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 580, 160], outline="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=200.0, height=60.0)
    page.insert_image(page.rect, stream=buf.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture()
def autocorrect_client(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    use_postgres = False
    engine = build_engine(TEST_DB_URL)
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
        db_url = TEST_DB_URL
        try:
            command.upgrade(alembic_cfg, "head")
        finally:
            os.environ.pop("DATABASE_URL", None)
    else:
        db_url = f"sqlite:///{(tmp_path / 'test_autocorrect.db').resolve()}"
        sq_engine = create_engine(db_url)
        Base.metadata.create_all(sq_engine)
        sq_engine.dispose()

    settings = AppSettings(
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
        lexicon_path=(repo_root / "models" / "lexicon" / "telugu_lexicon.tsv.gz").resolve(),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client, app, settings


def test_page_autocorrect_and_batch_save_approve_api(autocorrect_client) -> None:
    client, app, _settings = autocorrect_client

    upload = client.post(
        "/api/v1/books",
        files={"file": ("sample.pdf", _minimal_pdf_bytes(), "application/pdf")},
        data={"title": "ఆముక్తమాల్యద పరీక్ష"},
    )
    assert upload.status_code == 201
    book_id = UUID(upload.json()["book_id"])

    # Seed one completed OCR run with 3 realistic blocks directly in DB (fast, deterministic)
    with app.state.session_factory() as db:
        page = db.query(BookPage).filter(BookPage.book_id == book_id, BookPage.page_number == 1).one()
        model = ModelRegistry(
            engine_name="tesseract",
            model_id="tesseract-5-tel-best",
        )
        db.add(model)
        db.flush()
        run = OCRRun(book_id=book_id, model_registry_id=model.id, status="completed", config={})
        db.add(run)
        db.flush()

        b1 = OCRBlock(
            ocr_run_id=run.id,
            book_page_id=page.id,
            block_index=0,
            reading_order=0,
            block_type="text_line",
            raw_text="అష్టాదశవర్ధనలు - ర్మ",
            normalized_text="అష్టాదశవర్ధనలు - ర్మ",
            confidence=65.0,
        )
        b2 = OCRBlock(
            ocr_run_id=run.id,
            book_page_id=page.id,
            block_index=1,
            reading_order=1,
            block_type="text_line",
            raw_text="తెలుగు పస్తకం",
            normalized_text="తెలుగు పస్తకం",
            confidence=72.0,
        )
        b3 = OCRBlock(
            ocr_run_id=run.id,
            book_page_id=page.id,
            block_index=2,
            reading_order=2,
            block_type="text_line",
            raw_text="ఆముక్తమాల్యద",
            normalized_text="ఆముక్తమాల్యద",
            confidence=94.0,
        )
        db.add_all([b1, b2, b3])
        db.commit()
        run_id, b1_id, b2_id, b3_id = str(run.id), str(b1.id), str(b2.id), str(b3.id)

    # 1. Opt-in Auto-Correct Page returns proposals without mutating DB
    ac_resp = client.post(
        f"/api/v1/books/{book_id}/pages/1/autocorrect",
        json={"primary_run_id": run_id, "use_correction_memory": True, "use_dictionary": True},
    )
    assert ac_resp.status_code == 200
    ac_data = ac_resp.json()
    assert ac_data["lexicon_word_count"] >= 100_000
    assert ac_data["total_blocks_scanned"] == 3
    assert ac_data["changed_blocks_count"] == 2
    by_id = {b["block_id"]: b for b in ac_data["blocks"]}
    assert by_id[b1_id]["proposed_text"] == "అష్టాదశవర్ణనలు - ర్మ"
    assert by_id[b2_id]["proposed_text"] == "తెలుగు పుస్తకం"
    assert b3_id not in by_id  # Valid classical word untouched

    # Verify raw_text & current_text were NOT mutated by /autocorrect
    rev_before = client.get(f"/api/v1/books/{book_id}/pages/1/review").json()
    assert rev_before["review_status"] == "not_started"
    assert rev_before["blocks"][0]["current_text"] == "అష్టాదశవర్ధనలు - ర్మ"

    # 2. Batch Save & Approve Page atomically saves both edited lines (plus human page-number fix '- 43'),
    # filters 'ర్మ -> 43' from correction_memory, records Telugu fixes to memory, and approves b3 + page!
    batch_resp = client.post(
        f"/api/v1/books/{book_id}/pages/1/batch-save",
        json={
            "primary_run_id": run_id,
            "edits": [
                {
                    "block_id": b1_id,
                    "edited_text": "అష్టాదశవర్ణనలు - 43",
                    "add_to_correction_memory": True,
                    "memory_scope": "book_only",
                },
                {
                    "block_id": b2_id,
                    "edited_text": "తెలుగు పుస్తకం",
                    "add_to_correction_memory": True,
                    "memory_scope": "book_only",
                },
            ],
            "approve_remaining_blocks": True,
            "mark_page_approved": True,
        },
    )
    assert batch_resp.status_code == 200
    batch_data = batch_resp.json()
    assert batch_data["saved_edits_count"] == 2
    assert batch_data["approved_blocks_count"] == 1
    assert batch_data["correction_memory_created_count"] == 2
    assert batch_data["correction_memory_skipped_noise_count"] == 1
    assert batch_data["page_review_status"] == "approved"

    # Verify DB state: immutable raw_text preserved, current_text updated, b3 approved, page approved
    rev_after = client.get(f"/api/v1/books/{book_id}/pages/1/review").json()
    assert rev_after["review_status"] == "approved"
    assert rev_after["blocks"][0]["raw_text"] == "అష్టాదశవర్ధనలు - ర్మ"
    assert rev_after["blocks"][0]["current_text"] == "అష్టాదశవర్ణనలు - 43"
    assert rev_after["blocks"][1]["current_text"] == "తెలుగు పుస్తకం"
    assert rev_after["blocks"][2]["latest_action"] == "approved"

    # Verify correction_memory contains clean Telugu rules only (NOT 'ర్మ -> 43')
    mem_items = client.get("/api/v1/corrections", params={"book_id": str(book_id)}).json()["items"]
    pairs = {(m["incorrect_text"], m["corrected_text"]) for m in mem_items}
    assert ("అష్టాదశవర్ధనలు", "అష్టాదశవర్ణనలు") in pairs
    assert ("పస్తకం", "పుస్తకం") in pairs
    assert ("ర్మ", "43") not in pairs


def test_large_pdf_import_uses_lazy_page_rendering_on_demand(autocorrect_client) -> None:
    """Books with >10 pages skip synchronous full rasterization during upload and render pages lazily on demand."""
    client, _app, settings = autocorrect_client

    doc = pymupdf.open()
    for i in range(15):
        page = doc.new_page(width=200.0, height=120.0)
        page.insert_text((20, 60), f"Page {i + 1}")
    pdf_bytes = doc.tobytes()
    doc.close()

    upload = client.post(
        "/api/v1/books",
        files={"file": ("large_book.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Large Book Lazy Test"},
    )
    assert upload.status_code == 201
    book_id = upload.json()["book_id"]
    assert upload.json()["page_count"] == 15

    pages_dir = settings.workspace_dir / "pages" / book_id
    # Page 1 is pre-rendered; page 12 is deferred until requested (prevents 502 proxy timeout on 400+ page books).
    assert (pages_dir / "page-0001.png").is_file()
    assert not (pages_dir / "page-0012.png").is_file()

    pages_list = client.get(f"/api/v1/books/{book_id}/pages").json()["items"]
    assert len(pages_list) == 15
    assert all(p["has_image"] is True for p in pages_list)

    # Requesting page 12 image lazily renders & caches page-0012.png on demand.
    img_resp = client.get(f"/api/v1/books/{book_id}/pages/12/image")
    assert img_resp.status_code == 200
    assert img_resp.headers["content-type"] == "image/png"
    assert img_resp.content.startswith(b"\x89PNG")
    assert (pages_dir / "page-0012.png").is_file()
