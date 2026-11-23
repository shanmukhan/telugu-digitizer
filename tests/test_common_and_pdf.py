"""Unit tests for common safety helpers, PDF indexing, classification, and rasterization."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest
from PIL import Image, ImageDraw

from src.common.io import atomic_write_json, atomic_write_text, sanitize_id, validate_within_workspace
from src.pdf.rasterizer import render_pdf_pages, resolve_page_numbers


def _build_two_page_pdf(pdf_path: Path) -> None:
    """Create a 2-page PDF: page 1 scanned image, page 2 born-digital text."""
    img = Image.new("RGB", (600, 200), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 220, 140], outline="black", width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    p1 = doc.new_page(width=200, height=100)
    p1.insert_image(p1.rect, stream=buf.getvalue())

    p2 = doc.new_page(width=400, height=200)
    p2.insert_text((36, 60), "Digital born PDF text for classification verification.", fontsize=14)
    doc.save(pdf_path)
    doc.close()


def test_sanitize_id_and_workspace_validation(tmp_path: Path) -> None:
    assert sanitize_id("book_01-v2") == "book_01-v2"
    with pytest.raises(ValueError):
        sanitize_id("../escape")
    with pytest.raises(ValueError):
        sanitize_id("a/b")
    with pytest.raises(ValueError):
        sanitize_id("")

    inside = validate_within_workspace(tmp_path / "data" / "page-0001.png", tmp_path)
    assert inside == (tmp_path / "data" / "page-0001.png").resolve()

    with pytest.raises(ValueError):
        validate_within_workspace(tmp_path / ".." / "outside.txt", tmp_path)


def test_atomic_writes_preserve_utf8_telugu(tmp_path: Path) -> None:
    txt_file = tmp_path / "sample.txt"
    json_file = tmp_path / "sample.json"
    telugu_raw = "తెలుగు\u0c46\u0c56 పాఠ్యం\n"

    atomic_write_text(txt_file, telugu_raw)
    atomic_write_json(json_file, {"text": telugu_raw})

    assert txt_file.read_text(encoding="utf-8") == telugu_raw
    assert list(tmp_path.glob(".*.tmp")) == []


def test_resolve_page_numbers_validation() -> None:
    assert resolve_page_numbers(5, start_page=2, end_page=4) == [2, 3, 4]
    assert resolve_page_numbers(5, pages=[4, 1, 4]) == [1, 4]

    with pytest.raises(ValueError):
        resolve_page_numbers(0)
    with pytest.raises(ValueError):
        resolve_page_numbers(5, start_page=0, end_page=2)
    with pytest.raises(ValueError):
        resolve_page_numbers(5, start_page=4, end_page=6)
    with pytest.raises(ValueError):
        resolve_page_numbers(5, start_page=4, end_page=2)
    with pytest.raises(ValueError):
        resolve_page_numbers(5, pages=[6])


def test_render_pdf_pages_deterministic_and_classifies(tmp_path: Path) -> None:
    pdf_path = tmp_path / "two_page.pdf"
    _build_two_page_pdf(pdf_path)

    out1 = tmp_path / "pages1"
    out2 = tmp_path / "pages2"

    entries1 = render_pdf_pages(
        pdf_path=pdf_path,
        book_id="test_book",
        output_dir=out1,
        workspace_root=tmp_path,
        dpi=150,
    )
    entries2 = render_pdf_pages(
        pdf_path=pdf_path,
        book_id="test_book",
        output_dir=out2,
        workspace_root=tmp_path,
        dpi=150,
    )

    assert len(entries1) == 2
    assert [e.page_number for e in entries1] == [1, 2]
    assert [e.pdf_page_index for e in entries1] == [0, 1]
    assert entries1[0].page_kind == "scanned_image"
    assert entries1[1].page_kind == "digital_text"
    assert entries1[0].image_path.endswith("test_book/page-0001.png")
    assert entries1[1].image_path.endswith("test_book/page-0002.png")
    assert entries1[0].image_sha256 == entries2[0].image_sha256
    assert entries1[1].image_sha256 == entries2[1].image_sha256


def test_render_pdf_pages_per_page_failure_does_not_abort(tmp_path: Path) -> None:
    pdf_path = tmp_path / "two_page.pdf"
    _build_two_page_pdf(pdf_path)

    original_classify = __import__("src.pdf.rasterizer", fromlist=["classify_pdf_page"]).classify_pdf_page
    call_count = {"n": 0}

    def flaky_classify(page: pymupdf.Page) -> tuple[str, int, float]:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("Simulated page 1 failure")
        return original_classify(page)

    with patch("src.pdf.rasterizer.classify_pdf_page", side_effect=flaky_classify):
        entries = render_pdf_pages(
            pdf_path=pdf_path,
            book_id="flaky_book",
            output_dir=tmp_path / "pages",
            workspace_root=tmp_path,
            dpi=150,
        )

    assert len(entries) == 2
    assert entries[0].status == "failed"
    assert entries[0].error_type == "RuntimeError"
    assert entries[1].status == "rendered"
