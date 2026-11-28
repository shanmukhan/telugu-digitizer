"""Tests for standalone Telugu Dictionary REST API, SQLite FTS5 search, spellcheck, and custom words."""

from __future__ import annotations

import os
from pathlib import Path

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


@pytest.fixture()
def dict_client(tmp_path: Path):
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
        db_url = f"sqlite:///{(tmp_path / 'test_dict.db').resolve()}"
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
        dictionary_db_path=(repo_root / "models" / "lexicon" / "telugu_dictionary.sqlite").resolve(),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


def test_standalone_dictionary_search_definitions_spellcheck_and_custom_words(dict_client: TestClient) -> None:
    # 1. Corpus stats
    stats = dict_client.get("/api/v1/dictionary/stats")
    assert stats.status_code == 200
    sdata = stats.json()
    assert sdata["available"] is True
    assert sdata["has_definitions_db"] is True
    assert sdata["total_words"] >= 180_000
    assert sdata["words_with_definitions"] >= 50_000
    assert sdata["total_definitions"] >= 80_000

    # 2. Exact Telugu lookup + definitions
    search_te = dict_client.get("/api/v1/dictionary/search", params={"q": "పుస్తకము"})
    assert search_te.status_code == 200
    te_data = search_te.json()
    assert te_data["detected_mode"] == "telugu"
    assert te_data["exact_match"] is True
    assert te_data["items"][0]["word"] == "పుస్తకము"
    assert len(te_data["items"][0]["definitions"]) >= 1

    # 3. English reverse search via FTS5
    search_en = dict_client.get("/api/v1/dictionary/search", params={"q": "lotus"})
    assert search_en.status_code == 200
    en_data = search_en.json()
    assert en_data["detected_mode"] == "english"
    assert len(en_data["items"]) >= 1

    # 4. Misspelled Telugu word returns 'did_you_mean' suggestions
    search_typo = dict_client.get("/api/v1/dictionary/search", params={"q": "అష్టాదశవర్ధనలు"})
    assert search_typo.status_code == 200
    typo_data = search_typo.json()
    assert typo_data["exact_match"] is False
    assert any(d["word"] == "అష్టాదశవర్ణనలు" for d in typo_data["did_you_mean"])

    # 5. Detailed word endpoint
    detail = dict_client.get("/api/v1/dictionary/word/వర్ణన")
    assert detail.status_code == 200
    ddata = detail.json()
    assert ddata["found"] is True
    assert ddata["is_valid_word"] is True
    assert len(ddata["definitions"]) >= 1

    # 6. Paragraph spellchecker
    chk = dict_client.post(
        "/api/v1/dictionary/check-text",
        json={"text": "ఆముక్తమాల్యద అష్టాదశవర్ధనలు తెలుగు పస్తకం"},
    )
    assert chk.status_code == 200
    cdata = chk.json()
    assert cdata["total_telugu_words"] == 4
    assert cdata["unknown_words_count"] == 2
    by_tok = {i["token"]: i for i in cdata["issues"]}
    assert by_tok["అష్టాదశవర్ధనలు"]["best_replacement"] == "అష్టాదశవర్ణనలు"
    assert by_tok["పస్తకం"]["best_replacement"] == "పుస్తకం"

    # 7. Custom words CRUD + immediate recognition in search & spellcheck
    rare_word = "ఖ్జటపనమ"
    chk_before = dict_client.post("/api/v1/dictionary/check-text", json={"text": rare_word}).json()
    assert chk_before["unknown_words_count"] == 1

    created = dict_client.post(
        "/api/v1/dictionary/custom",
        json={
            "word": rare_word,
            "translit": "lahariprabandhamu",
            "meaning_en": "Custom classical test term",
            "meaning_te": "ప్రత్యేక పదము",
            "notes": "Test note",
        },
    )
    assert created.status_code == 201
    word_id = created.json()["word_id"]

    # Immediately recognized in spellcheck & search!
    chk_after = dict_client.post("/api/v1/dictionary/check-text", json={"text": rare_word}).json()
    assert chk_after["unknown_words_count"] == 0

    search_custom = dict_client.get("/api/v1/dictionary/search", params={"q": rare_word}).json()
    assert search_custom["exact_match"] is True
    assert search_custom["items"][0]["is_custom"] is True

    listed = dict_client.get("/api/v1/dictionary/custom").json()["items"]
    assert any(item["word_id"] == word_id for item in listed)

    deleted = dict_client.delete(f"/api/v1/dictionary/custom/{word_id}")
    assert deleted.status_code == 204
    listed_after = dict_client.get("/api/v1/dictionary/custom").json()["items"]
    assert all(item["word_id"] != word_id for item in listed_after)
