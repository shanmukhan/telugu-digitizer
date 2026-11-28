"""Tests for OCR Calibration (with PDF starting page), word-level Correction Memory, safety guards, and book state."""

from __future__ import annotations

import io
import os
import time
import uuid
from pathlib import Path

import pymupdf
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, text

from src.api.app import create_app
from src.core.config import AppSettings
from src.db.models import Book, BookPage, CorrectionMemory, OCRBlock, OCRRun, ReviewEdit
from src.db.session import build_engine
from src.services.calibration_service import (
    apply_learned_corrections_to_page_blocks,
    extract_recurring_char_patterns,
)
from src.services.correction_service import (
    classify_unit_type,
    compute_reliability_score,
    extract_word_level_corrections,
)
from src.services.lexicon_service import TeluguLexicon

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


def _build_multipage_scanned_pdf(page_texts: list[str]) -> bytes:
    font_path = _telugu_font_path()
    font = ImageFont.truetype(font_path, 38)
    doc = pymupdf.open()
    for line_text in page_texts:
        img = Image.new("RGB", (900, 220), "white")
        draw = ImageDraw.Draw(img)
        draw.text((40, 75), line_text, fill="black", font=font)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page = doc.new_page(width=216.0, height=52.8)
        page.insert_image(page.rect, stream=buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


@pytest.fixture()
def cal_client(tmp_path: Path):
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


def _wait_for_run(client: TestClient, run_id: str, timeout_sec: float = 30.0) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        st = client.get(f"/api/v1/ocr-runs/{run_id}").json()
        if st["status"] in ("completed", "partial", "failed"):
            return st
        time.sleep(0.15)
    raise AssertionError(f"OCR run {run_id} did not finish within {timeout_sec}s")


# ---------------------------------------------------------------------------
# Pure unit tests: word-level extraction, reliability, char patterns
# ---------------------------------------------------------------------------


def test_word_level_extraction_splits_adjacent_edits_instead_of_sentences() -> None:
    # Two adjacent misspelled words edited in one line should produce TWO word-level pairs, not a phrase/sentence.
    pairs = extract_word_level_corrections(
        "మలయకూట పబ్లీషన్ హ్రౌదరాబాదు - 57",
        "మలయకూట పబ్లికేషన్స్ హైదరాబాదు - 57",
    )
    extracted = [(inc, cor) for inc, cor, _, _ in pairs]
    assert ("పబ్లీషన్", "పబ్లికేషన్స్") in extracted
    assert ("హ్రౌదరాబాదు", "హైదరాబాదు") in extracted
    assert all(" " not in inc for inc, _ in extracted)

    # Shared trailing hyphen stripped while keeping leading '(' OCR error artifact.
    pairs_heading = extract_word_level_corrections("(పగమబాగం- 1", "ప్రథమభాగం- 1")
    assert [(inc, cor) for inc, cor, _, _ in pairs_heading] == [("(పగమబాగం", "ప్రథమభాగం")]

    # Genuine word-boundary merge stays a compact phrase rule.
    pairs_merge = extract_word_level_corrections("ఇది పుస్త కం మంచిది", "ఇది పుస్తకం మంచిది")
    assert [(inc, cor) for inc, cor, _, _ in pairs_merge] == [("పుస్త కం", "పుస్తకం")]
    assert classify_unit_type("పుస్త కం", "పుస్తకం") == "phrase"
    assert classify_unit_type("పబ్లీషన్", "పబ్లికేషన్స్") == "word"


def test_reliability_score_and_recurring_char_pattern_extraction() -> None:
    single_score = compute_reliability_score(1, 0, has_conflict=False)
    repeated_score = compute_reliability_score(4, 0, has_conflict=False)
    conflicted_score = compute_reliability_score(2, 0, has_conflict=True)
    rejected_score = compute_reliability_score(1, 2, has_conflict=False)

    assert repeated_score > single_score
    assert conflicted_score < single_score
    assert rejected_score < 0.5

    patterns = extract_recurring_char_patterns(
        [
            ("బాగం", "భాగం"),
            ("బాష", "భాష"),
            ("బారతం", "భారతం"),
        ],
        min_distinct_words=2,
    )
    assert patterns
    assert patterns[0]["from_seq"] == "బ"
    assert patterns[0]["to_seq"] == "భ"
    assert patterns[0]["occurrences"] == 3


# ---------------------------------------------------------------------------
# Integration tests: Calibration with starting PDF page + auto-apply + safety
# ---------------------------------------------------------------------------


def test_calibration_custom_start_page_5_and_10_pages_and_validation(cal_client) -> None:
    client, app, settings = cal_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    # Build a 12-page PDF: pages 1-2 front matter, pages 3-12 Telugu body.
    pdf_bytes = _build_multipage_scanned_pdf(
        [f"తెలుగు పుస్తకం పుట {i}" for i in range(1, 13)]
    )
    upload = client.post(
        "/api/v1/books",
        files={"file": ("cal_book.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Calibration Test Book"},
    )
    assert upload.status_code == 201
    book_id = upload.json()["book_id"]

    # Validation checks: invalid starting page & range exceeding total pages.
    bad_start = client.post(
        f"/api/v1/books/{book_id}/calibration/start",
        json={"start_page": 15, "calibration_page_count": 5, "engines": ["tesseract_tel_best"]},
    )
    assert bad_start.status_code == 400
    assert bad_start.json()["error"]["code"] == "INVALID_CALIBRATION_START_PAGE"

    bad_range = client.post(
        f"/api/v1/books/{book_id}/calibration/start",
        json={"start_page": 10, "calibration_page_count": 5, "engines": ["tesseract_tel_best"]},
    )
    assert bad_range.status_code == 400
    assert bad_range.json()["error"]["code"] == "CALIBRATION_RANGE_EXCEEDS_BOOK"

    # Case A: Start 5-page calibration beginning at PDF page 3 -> processes ONLY PDF pages 3..7.
    cal5 = client.post(
        f"/api/v1/books/{book_id}/calibration/start",
        json={
            "start_page": 3,
            "calibration_page_count": 5,
            "engines": ["tesseract_tel_best"],
        },
    )
    assert cal5.status_code == 202
    cal5_body = cal5.json()
    assert cal5_body["pages_total"] == 5
    assert cal5_body["calibration"]["calibration_start_page"] == 3
    assert cal5_body["calibration"]["calibration_page_count"] == 5
    assert cal5_body["calibration"]["calibration_range_end"] == 7
    assert cal5_body["calibration"]["skipped_front_pages_count"] == 2
    assert cal5_body["calibration"]["remaining_start_page"] == 8
    assert cal5_body["calibration"]["remaining_end_page"] == 12
    assert cal5_body["calibration"]["remaining_pages_count"] == 5

    run_status = _wait_for_run(client, cal5_body["ocr_run_id"])
    assert run_status["status"] == "completed"

    # Verify front-matter pages 1-2 and remaining pages 8-12 were NOT processed yet.
    with app.state.session_factory() as db:
        ocred_page_nums = sorted(
            db.scalars(
                select(BookPage.page_number)
                .join(OCRBlock, OCRBlock.book_page_id == BookPage.id)
                .where(BookPage.book_id == uuid.UUID(book_id))
                .distinct()
            ).all()
        )
    assert all(3 <= p <= 7 for p in ocred_page_nums)
    assert 1 not in ocred_page_nums and 2 not in ocred_page_nums
    assert 8 not in ocred_page_nums and 12 not in ocred_page_nums

    # Verify book state moved to calibration_review.
    cal_status = client.get(f"/api/v1/books/{book_id}/calibration").json()
    assert cal_status["processing_state"] == "calibration_review"

    # Case B: Upload a second 12-page book and verify 10 calibration pages starting at page 2 (PDF 2..11).
    pdf_bytes_b = _build_multipage_scanned_pdf(
        [f"ఆంధ్ర భాషా గ్రంథము {i}" for i in range(1, 13)]
    )
    book_b_id = client.post(
        "/api/v1/books",
        files={"file": ("cal_book_10.pdf", pdf_bytes_b, "application/pdf")},
        data={"title": "Calibration 10 Pages Book"},
    ).json()["book_id"]

    cal10 = client.post(
        f"/api/v1/books/{book_b_id}/calibration/start",
        json={
            "start_page": 2,
            "calibration_page_count": 10,
            "engines": ["tesseract_tel_best"],
        },
    )
    assert cal10.status_code == 202
    assert cal10.json()["pages_total"] == 10
    assert cal10.json()["calibration"]["calibration_range_end"] == 11
    assert cal10.json()["calibration"]["remaining_pages_count"] == 1
    _wait_for_run(client, cal10.json()["ocr_run_id"])


def test_calibration_learns_word_corrections_applies_safely_and_supports_revert_reject(cal_client) -> None:
    client, app, settings = cal_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    # 4-page scanned book: page 1 front matter, pages 2-3 calibration, page 4 remaining.
    pdf_bytes = _build_multipage_scanned_pdf(
        [
            "ముఖచిత్రం",
            "పాఠశాల పరీక్ష",
            "పాఠశాల పరీక్ష",
            "పాఠశాల పరీక్ష",
        ]
    )
    book_id = client.post(
        "/api/v1/books",
        files={"file": ("learn_book.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Learning Book"},
    ).json()["book_id"]

    # Step 1: Run calibration on PDF pages 2..3 (skipping front matter page 1).
    start_res = client.post(
        f"/api/v1/books/{book_id}/calibration/start",
        json={"start_page": 2, "calibration_page_count": 2, "engines": ["tesseract_tel_best"]},
    )
    assert start_res.status_code == 202
    _wait_for_run(client, start_res.json()["ocr_run_id"])

    # Step 2: Review PDF page 2 and introduce a deterministic word-level correction.
    review_p2 = client.get(f"/api/v1/books/{book_id}/pages/2/review").json()
    assert review_p2["blocks"]
    blk_p2 = review_p2["blocks"][0]
    first_raw_word = blk_p2["raw_text"].strip().split()[0]
    corrected_word = "విద్యాలయం"
    edited_p2_text = blk_p2["raw_text"].replace(first_raw_word, corrected_word, 1)

    edit_res = client.post(
        f"/api/v1/ocr-blocks/{blk_p2['block_id']}/edits",
        json={
            "edited_text": edited_p2_text,
            "action": "corrected",
            "add_to_correction_memory": True,
            "memory_scope": "book_only",
        },
    )
    assert edit_res.status_code == 201
    created_cm_id = edit_res.json()["correction_memory_id"]
    assert created_cm_id is not None

    # Reinforce evidence on page 3 as well (so approved_count >= 2 even if token is a valid word).
    review_p3 = client.get(f"/api/v1/books/{book_id}/pages/3/review").json()
    blk_p3 = review_p3["blocks"][0]
    edited_p3_text = blk_p3["raw_text"].replace(first_raw_word, corrected_word, 1)
    client.post(
        f"/api/v1/ocr-blocks/{blk_p3['block_id']}/edits",
        json={
            "edited_text": edited_p3_text,
            "action": "corrected",
            "add_to_correction_memory": True,
            "memory_scope": "book_only",
        },
    )

    # Complete calibration and inspect summary.
    comp = client.post(f"/api/v1/books/{book_id}/calibration/complete")
    assert comp.status_code == 200
    assert comp.json()["processing_state"] == "calibration_completed"
    assert comp.json()["learned_word_rules_count"] >= 1

    # Step 3: Process remaining pages (ONLY PDF page 4; page 1 untouched, pages 2-3 not reprocessed).
    rem_res = client.post(
        f"/api/v1/books/{book_id}/calibration/process-remaining",
        json={"engines": ["tesseract_tel_best"], "apply_calibration_corrections": True},
    )
    assert rem_res.status_code == 202
    assert rem_res.json()["pages_total"] == 1
    rem_status = _wait_for_run(client, rem_res.json()["ocr_run_id"])
    assert rem_status["status"] == "completed"

    # Verify PDF page 1 remained untouched.
    review_p1 = client.get(f"/api/v1/books/{book_id}/pages/1/review").json()
    assert review_p1["blocks"] == []

    # Verify PDF page 4 had the calibration correction auto-applied while raw_text is untouched!
    review_p4 = client.get(f"/api/v1/books/{book_id}/pages/4/review").json()
    assert review_p4["blocks"]
    blk_p4 = review_p4["blocks"][0]
    assert first_raw_word in blk_p4["raw_text"]
    assert corrected_word in blk_p4["current_text"]
    assert blk_p4["latest_action"] == "auto_applied"
    assert blk_p4["auto_applied_flag"] is True
    assert len(blk_p4["auto_applied_rules"]) >= 1

    # Step 4: Revert the auto-applied correction and reject the rule -> restores raw OCR + increments rejected_count.
    revert_res = client.post(
        f"/api/v1/ocr-blocks/{blk_p4['block_id']}/edits",
        json={
            "edited_text": blk_p4["raw_text"],
            "action": "reverted",
            "reject_auto_applied_rules": True,
        },
    )
    assert revert_res.status_code == 201
    assert revert_res.json()["current_text"] == blk_p4["raw_text"]

    cm_list = client.get(f"/api/v1/corrections?book_id={book_id}").json()
    assert cm_list["total_count"] >= 1
    matching = [c for c in cm_list["items"] if c["correction_id"] == created_cm_id]
    assert matching and matching[0]["rejected_count"] >= 1
    assert matching[0]["source_page_number"] == 2
    assert matching[0]["unit_type"] == "word"

    # Step 5: Test Correction Memory edit, book-state pause, and delete endpoints.
    patch_cm = client.patch(
        f"/api/v1/corrections/{created_cm_id}",
        json={"corrected_text": "మహావిద్యాలయం", "scope": "global_suggestion"},
    )
    assert patch_cm.status_code == 200
    assert patch_cm.json()["corrected_text"] == "మహావిద్యాలయం"
    assert patch_cm.json()["scope"] == "global_suggestion"

    pause_res = client.patch(
        f"/api/v1/books/{book_id}/state",
        json={"processing_state": "paused"},
    )
    assert pause_res.status_code == 200
    assert pause_res.json()["processing_state"] == "paused"

    # Confirm switching/pausing preserved book OCR blocks and review history.
    book_summary = client.get(f"/api/v1/books/{book_id}").json()
    assert book_summary["processing_state"] == "paused"
    assert book_summary["calibration_start_page"] == 2

    del_cm = client.delete(f"/api/v1/corrections/{created_cm_id}")
    assert del_cm.status_code == 204


def test_auto_apply_safety_guards_valid_words_and_contextual_conflicts(cal_client) -> None:
    """Verify auto-application never blindly overwrites valid words or unresolved conflicts,
    and resolves conflicts cleanly when surrounding context matches."""
    _client, app, _settings = cal_client
    with app.state.session_factory() as db:
        book = Book(
            title="Safety Guard Book",
            original_filename="safety.pdf",
            source_storage_key="originals/safety/source.pdf",
            source_sha256="a" * 64,
            page_count=1,
            language_code="te",
        )
        db.add(book)
        db.flush()
        page = BookPage(book_id=book.id, page_number=1, page_kind="scanned_image")
        db.add(page)
        db.flush()
        run = OCRRun(book_id=book.id, status="completed", config={"start_page": 1, "end_page": 1})
        db.add(run)
        db.flush()

        # Rule pair 1 (CONFLICT): OCR word "పదం" -> "పద్యం" after "తెలుగు", OR "పాదం" after "కవి".
        db.add(
            CorrectionMemory(
                language_code="te",
                incorrect_text="పదం",
                normalized_incorrect="పదం",
                corrected_text="పద్యం",
                left_context="తెలుగు",
                scope="book_only",
                book_id=book.id,
                status="active",
                approved_count=2,
                rejected_count=0,
            )
        )
        db.add(
            CorrectionMemory(
                language_code="te",
                incorrect_text="పదం",
                normalized_incorrect="పదం",
                corrected_text="పాదం",
                left_context="కవి",
                scope="book_only",
                book_id=book.id,
                status="active",
                approved_count=2,
                rejected_count=0,
            )
        )
        # Rule 2 (SINGLE-APPROVAL GLOBAL): should NOT auto-apply on another book with approved_count=1.
        other_book = Book(
            title="Other Book",
            original_filename="other.pdf",
            source_storage_key="originals/other/source.pdf",
            source_sha256="b" * 64,
            page_count=1,
            language_code="te",
        )
        db.add(other_book)
        db.flush()
        db.add(
            CorrectionMemory(
                language_code="te",
                incorrect_text="తప్పుపదం",
                normalized_incorrect="తప్పుపదం",
                corrected_text="సరైనపదం",
                scope="global_suggestion",
                book_id=other_book.id,
                status="active",
                approved_count=1,
                rejected_count=0,
            )
        )

        # Blocks on page:
        # B0: strong left context "తెలుగు" -> conflict resolves to "పద్యం"
        # B1: ambiguous context "కొత్త" -> conflict MUST NOT auto-apply
        # B2: single-approval global rule from another book -> MUST NOT auto-apply
        b0 = OCRBlock(ocr_run_id=run.id, book_page_id=page.id, block_index=0, raw_text="తెలుగు పదం బాగుంది")
        b1 = OCRBlock(ocr_run_id=run.id, book_page_id=page.id, block_index=1, raw_text="కొత్త పదం బాగుంది")
        b2 = OCRBlock(ocr_run_id=run.id, book_page_id=page.id, block_index=2, raw_text="ఇది తప్పుపదం")
        db.add_all([b0, b1, b2])
        db.commit()

        applied = apply_learned_corrections_to_page_blocks(
            db=db,
            book=book,
            page=page,
            blocks=[b0, b1, b2],
            lexicon_path=None,
        )
        db.commit()

        assert applied == 1
        edits_b0 = list(db.scalars(select(ReviewEdit).where(ReviewEdit.ocr_block_id == b0.id)).all())
        edits_b1 = list(db.scalars(select(ReviewEdit).where(ReviewEdit.ocr_block_id == b1.id)).all())
        edits_b2 = list(db.scalars(select(ReviewEdit).where(ReviewEdit.ocr_block_id == b2.id)).all())
        assert len(edits_b0) == 1
        assert edits_b0[0].action == "auto_applied"
        assert edits_b0[0].edited_text == "తెలుగు పద్యం బాగుంది"
        assert b0.raw_text == "తెలుగు పదం బాగుంది"
        assert edits_b1 == []
        assert edits_b2 == []


def test_normalize_legacy_phrases_batch_reapply_and_visual_training_export(cal_client) -> None:
    """Verify legacy multi-word cleanup, batch re-apply on unreviewed pages, and visual fine-tuning ZIP export."""
    import zipfile

    client, app, settings = cal_client
    if not (settings.tessdata_dir / "tel.traineddata").is_file():
        pytest.skip("tel.traineddata missing.")

    # 1. Seed legacy multi-word and trailing-punctuation rules and normalize them.
    with app.state.session_factory() as db:
        db.add_all(
            [
                CorrectionMemory(
                    language_code="te",
                    incorrect_text="పబ్లీషన్ హ్రౌదరాబాదు",
                    normalized_incorrect="పబ్లీషన్ హ్రౌదరాబాదు",
                    corrected_text="పబ్లికేషన్స్ హైదరాబాదు",
                    unit_type="phrase",
                    scope="global_suggestion",
                    status="active",
                    approved_count=2,
                    rejected_count=0,
                ),
                CorrectionMemory(
                    language_code="te",
                    incorrect_text="(పగమబాగం-",
                    normalized_incorrect="పగమబాగం",
                    corrected_text="ప్రథమభాగం-",
                    unit_type="word",
                    scope="global_suggestion",
                    status="active",
                    approved_count=1,
                    rejected_count=0,
                ),
                CorrectionMemory(
                    language_code="te",
                    incorrect_text="పుస్త కం",
                    normalized_incorrect="పుస్త కం",
                    corrected_text="పుస్తకం",
                    unit_type="phrase",
                    scope="global_suggestion",
                    status="active",
                    approved_count=1,
                    rejected_count=0,
                ),
            ]
        )
        db.commit()

    norm_res = client.post("/api/v1/corrections/normalize-legacy")
    assert norm_res.status_code == 200
    norm_body = norm_res.json()
    assert norm_body["split_legacy_rows"] == 1
    assert norm_body["created_word_rules"] == 2
    assert norm_body["cleaned_punct_rows"] == 1

    all_cm = client.get("/api/v1/corrections").json()["items"]
    pairs = {(c["incorrect_text"], c["corrected_text"]): c["unit_type"] for c in all_cm}
    assert pairs[("పబ్లీషన్", "పబ్లికేషన్స్")] == "word"
    assert pairs[("హ్రౌదరాబాదు", "హైదరాబాదు")] == "word"
    assert pairs[("(పగమబాగం", "ప్రథమభాగం")] == "word"
    assert pairs[("పుస్త కం", "పుస్తకం")] == "phrase"
    assert ("పబ్లీషన్ హ్రౌదరాబాదు", "పబ్లికేషన్స్ హైదరాబాదు") not in pairs

    # 2. Upload 3-page scanned book, OCR all 3 pages, approve page 1, keep pages 2-3 unreviewed.
    pdf_bytes = _build_multipage_scanned_pdf(
        [
            "పాఠశాల పరీక్ష",
            "పాఠశాల పరీక్ష",
            "పాఠశాల పరీక్ష",
        ]
    )
    book_id = client.post(
        "/api/v1/books",
        files={"file": ("reapply_train.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Reapply And Train Book"},
    ).json()["book_id"]

    run_res = client.post(
        f"/api/v1/books/{book_id}/ocr-runs",
        json={"engines": ["tesseract_tel_best"]},
    ).json()
    _wait_for_run(client, run_res["ocr_run_id"])

    # Edit & approve page 1 (creates a book_only word rule + marks page 1 approved).
    rev1 = client.get(f"/api/v1/books/{book_id}/pages/1/review").json()
    blk1 = rev1["blocks"][0]
    first_word = blk1["raw_text"].strip().split()[0]
    replacement_word = "కళాశాల"
    edited1 = blk1["raw_text"].replace(first_word, replacement_word, 1)

    client.post(
        f"/api/v1/ocr-blocks/{blk1['block_id']}/edits",
        json={
            "edited_text": edited1,
            "action": "corrected",
            "add_to_correction_memory": True,
            "memory_scope": "book_only",
        },
    )
    # Reinforce evidence to approved_count=2 so valid-word guard also allows safe auto-apply.
    client.post(
        f"/api/v1/ocr-blocks/{blk1['block_id']}/edits",
        json={
            "edited_text": edited1,
            "action": "approved",
        },
    )
    with app.state.session_factory() as db:
        for cm in db.scalars(select(CorrectionMemory).where(CorrectionMemory.book_id == uuid.UUID(book_id))).all():
            cm.approved_count = 2
        db.commit()

    client.patch(
        f"/api/v1/books/{book_id}/pages/1/review-status",
        json={"review_status": "approved"},
    )

    # Batch re-apply learned rules to unreviewed pages (pages 2 & 3 only; page 1 untouched).
    reapply = client.post(f"/api/v1/books/{book_id}/calibration/reapply-unreviewed")
    assert reapply.status_code == 200
    reapply_body = reapply.json()
    assert reapply_body["pages_scanned"] == 2
    assert reapply_body["pages_updated"] == 2
    assert reapply_body["blocks_updated"] == 2

    rev2 = client.get(f"/api/v1/books/{book_id}/pages/2/review").json()
    assert replacement_word in rev2["blocks"][0]["current_text"]
    assert rev2["blocks"][0]["latest_action"] == "auto_applied"
    assert first_word in rev2["blocks"][0]["raw_text"]

    # Idempotent: running re-apply again with no new rules makes 0 redundant updates.
    reapply_again = client.post(f"/api/v1/books/{book_id}/calibration/reapply-unreviewed").json()
    assert reapply_again["blocks_updated"] == 0

    # 3. Enable training consent retroactively -> harvests verified crops from page 1 -> export ZIP bundle!
    consent_res = client.post(
        f"/api/v1/books/{book_id}/training-consent",
        json={"training_consent": True, "harvest_existing": True},
    )
    assert consent_res.status_code == 200
    assert consent_res.json()["training_consent"] is True
    assert consent_res.json()["harvested_crops_count"] >= 1
    assert consent_res.json()["total_book_samples"] >= 1

    summary = client.get(f"/api/v1/training/summary?book_id={book_id}").json()
    assert summary["total_verified_samples"] >= 1
    assert summary["selected_book_consent"] is True

    exp = client.post("/api/v1/training/export", json={"book_id": book_id})
    assert exp.status_code == 201
    exp_body = exp.json()
    assert exp_body["total_samples"] >= 1
    assert exp_body["download_url"].startswith("/api/v1/training/exports/")

    dl = client.get(exp_body["download_url"])
    assert dl.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
        names = set(zf.namelist())
        assert "paddleocr/train_list.txt" in names
        assert "paddleocr/val_list.txt" in names
        assert "paddleocr/rec_te_ppocrv5_finetune.yml" in names
        assert "manifest.json" in names
        assert any(n.startswith("tesseract/ground-truth/") and n.endswith(".gt.txt") for n in names)

