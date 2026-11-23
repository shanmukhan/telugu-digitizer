"""Tesseract 5 Telugu (tessdata_best LSTM) adapter."""

from __future__ import annotations

import csv
import io
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from src.common.io import sha256_file
from src.common.manifest import resolve_tesseract_command
from src.ocr.base import OCRProvider


def parse_tesseract_tsv(tsv_text: str) -> list[dict[str, Any]]:
    """Parse Tesseract TSV output into ordered text-line blocks with bounding boxes."""
    lines_by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t", quoting=csv.QUOTE_NONE)

    for row in reader:
        if row.get("level") != "5":
            continue
        word_text = row.get("text") or ""
        if not word_text.strip():
            continue
        key = (
            str(row.get("page_num", "1")),
            str(row.get("block_num", "0")),
            str(row.get("par_num", "0")),
            str(row.get("line_num", "0")),
        )
        left = int(row.get("left", 0))
        top = int(row.get("top", 0))
        width = int(row.get("width", 0))
        height = int(row.get("height", 0))
        try:
            conf_val = float(row.get("conf", -1))
        except (TypeError, ValueError):
            conf_val = -1.0

        lines_by_key.setdefault(key, []).append(
            {
                "text": word_text,
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "conf": conf_val if conf_val >= 0 else None,
            }
        )

    blocks: list[dict[str, Any]] = []
    for block_idx, words in enumerate(lines_by_key.values()):
        x1 = min(w["left"] for w in words)
        y1 = min(w["top"] for w in words)
        x2 = max(w["right"] for w in words)
        y2 = max(w["bottom"] for w in words)
        confs = [w["conf"] for w in words if w["conf"] is not None]
        mean_conf = round(sum(confs) / len(confs), 4) if confs else None
        polygon = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        blocks.append(
            {
                "block_index": block_idx,
                "block_type": "text_line",
                "text": " ".join(w["text"] for w in words),
                "confidence": mean_conf,
                "polygon": polygon,
                "bbox": [x1, y1, x2, y2],
                "reading_order": block_idx,
            }
        )
    return blocks


class TesseractOCRProvider(OCRProvider):
    """Tesseract 5 LSTM provider configured for Telugu tessdata_best."""

    engine_name = "tesseract"

    def __init__(
        self,
        tessdata_dir: Path | str = Path("models/tesseract/tessdata"),
        lang: str = "tel",
        oem: int = 1,
        psm: int = 6,
        tesseract_cmd: str | None = None,
    ) -> None:
        if lang != "tel":
            raise ValueError(f"Phase 1 requires Tesseract Telugu lang='tel', got {lang!r}.")
        if oem != 1:
            raise ValueError(f"Phase 1 requires Tesseract LSTM engine --oem 1, got {oem}.")

        self.tessdata_dir = Path(tessdata_dir)
        self.traineddata_path = self.tessdata_dir / f"{lang}.traineddata"
        if not self.traineddata_path.is_file():
            raise FileNotFoundError(
                f"Missing Tesseract traineddata file: {self.traineddata_path}. "
                "Download official tessdata_best/tel.traineddata first."
            )

        self.lang = lang
        self.oem = oem
        self.psm = int(psm)
        self.tesseract_cmd = resolve_tesseract_command(tesseract_cmd)
        self.traineddata_sha256 = sha256_file(self.traineddata_path)
        self._version_str = self._read_version()

    def _read_version(self) -> str:
        proc = subprocess.run([self.tesseract_cmd, "--version"], capture_output=True, check=True)
        lines = proc.stdout.decode("utf-8", errors="replace").splitlines()
        return lines[0].strip() if lines else "unknown"

    def provider_metadata(self) -> dict[str, Any]:
        return {
            "engine": self.engine_name,
            "engine_version": self._version_str,
            "model_id": f"tesseract:{self.lang}:tessdata_best:oem{self.oem}:psm{self.psm}",
            "traineddata_path": str(self.traineddata_path),
            "traineddata_sha256": self.traineddata_sha256,
            "cold_start_ms": None,
            "config": {
                "lang": self.lang,
                "oem": self.oem,
                "psm": self.psm,
                "tessdata_dir": str(self.tessdata_dir),
                "traineddata_sha256": self.traineddata_sha256,
            },
        }

    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        """Run Tesseract CLI on one PNG image, capturing verbatim TXT and TSV."""
        img = Path(image_path)
        if not img.is_file():
            raise FileNotFoundError(f"OCR input image not found: {img}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_base = Path(tmp_dir) / "tesseract_out"
            cmd = [
                self.tesseract_cmd,
                str(img),
                str(out_base),
                "-l",
                self.lang,
                "--oem",
                str(self.oem),
                "--psm",
                str(self.psm),
                "--tessdata-dir",
                str(self.tessdata_dir),
                "-c",
                "tessedit_create_tsv=1",
                "-c",
                "tessedit_create_txt=1",
            ]
            t0 = time.perf_counter()
            proc = subprocess.run(cmd, capture_output=True)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)

            if proc.returncode != 0:
                stderr_msg = proc.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Tesseract failed (rc={proc.returncode}): {stderr_msg}")

            raw_txt = (out_base.with_suffix(".txt")).read_text(encoding="utf-8", errors="replace")
            raw_tsv = (out_base.with_suffix(".tsv")).read_text(encoding="utf-8", errors="replace")

        blocks = parse_tesseract_tsv(raw_tsv)
        # Preserve raw Tesseract output verbatim (strip only trailing form-feed / final newline).
        page_text = raw_txt.rstrip("\f").rstrip("\r\n")
        meta = self.provider_metadata()

        return {
            "engine": self.engine_name,
            "engine_version": meta["engine_version"],
            "model_id": meta["model_id"],
            "config": meta["config"],
            "elapsed_ms": elapsed_ms,
            "cold_start_ms": None,
            "text": page_text,
            "blocks": blocks,
            "raw_payload": {
                "format": "tesseract_txt_tsv",
                "traineddata_sha256": self.traineddata_sha256,
                "txt": raw_txt,
                "tsv": raw_tsv,
            },
        }
