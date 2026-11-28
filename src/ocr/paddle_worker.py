"""Process-isolated PaddleOCR worker & proxy for per-page timeouts and crash containment.

Running PaddlePaddle/PaddleOCR in a persistent child process ensures:
1. Model weights stay warm across pages of multi-hundred-page books.
2. Per-page hard timeouts kill stuck C++/inference calls cleanly.
3. Native C++/OpenBLAS segfaults or OOMs on a bad scan cannot crash the FastAPI studio.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from src.ocr.base import OCRProvider


def _build_worker_env(cpu_threads: int | None) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    if cpu_threads is not None:
        env.setdefault("PADDLE_PDX_CPU_NUM_THREADS", str(cpu_threads))
        env.setdefault("OMP_NUM_THREADS", str(cpu_threads))
        env.setdefault("OPENBLAS_NUM_THREADS", str(cpu_threads))
    return env


def _worker_loop(args: argparse.Namespace) -> int:
    # Ensure environment defaults are applied before any paddle/paddlex import.
    if args.disable_model_source_check:
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    if args.cpu_threads is not None:
        os.environ.setdefault("PADDLE_PDX_CPU_NUM_THREADS", str(args.cpu_threads))

    from src.ocr.paddle_provider import PaddleOCRProvider

    provider = PaddleOCRProvider(
        lang=args.lang,
        ocr_version=args.ocr_version,
        device=args.device,
        use_doc_orientation_classify=args.use_doc_orientation_classify,
        use_doc_unwarping=args.use_doc_unwarping,
        use_textline_orientation=args.use_textline_orientation,
        disable_model_source_check=args.disable_model_source_check,
        cpu_threads=args.cpu_threads,
        text_det_limit_side_len=args.text_det_limit_side_len,
    )

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            if cmd == "shutdown":
                sys.stdout.write(json.dumps({"ok": True}) + "\n")
                sys.stdout.flush()
                return 0
            if cmd == "meta":
                with contextlib.redirect_stdout(sys.stderr):
                    if req.get("warmup"):
                        provider.ensure_loaded()
                    meta = provider.provider_metadata()
                sys.stdout.write(json.dumps({"ok": True, "meta": meta}, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            elif cmd == "recognize":
                img_path = str(req["image_path"])
                with contextlib.redirect_stdout(sys.stderr):
                    res = provider.recognize(img_path)
                sys.stdout.write(json.dumps({"ok": True, "result": res}, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            else:
                sys.stdout.write(json.dumps({"ok": False, "error_type": "ValueError", "error": f"Unknown cmd: {cmd!r}"}) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            sys.stdout.write(
                json.dumps(
                    {
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Isolated PaddleOCR JSON worker process")
    parser.add_argument("--lang", default="te")
    parser.add_argument("--ocr-version", default="PP-OCRv5")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--use-doc-orientation-classify", action="store_true")
    parser.add_argument("--use-doc-unwarping", action="store_true")
    parser.add_argument("--use-textline-orientation", action="store_true")
    parser.add_argument("--disable-model-source-check", action="store_true", default=True)
    parser.add_argument("--cpu-threads", type=int, default=None)
    parser.add_argument("--text-det-limit-side-len", type=int, default=None)
    args = parser.parse_args(argv)
    return _worker_loop(args)


class IsolatedPaddleOCRProvider(OCRProvider):
    """Subprocess-isolated PaddleOCRProvider wrapper supporting hard per-page timeouts."""

    engine_name = "paddleocr"

    def __init__(
        self,
        *,
        lang: str = "te",
        ocr_version: str = "PP-OCRv5",
        device: str = "cpu",
        use_doc_orientation_classify: bool = False,
        use_doc_unwarping: bool = False,
        use_textline_orientation: bool = False,
        disable_model_source_check: bool = True,
        cpu_threads: int | None = None,
        text_det_limit_side_len: int | None = None,
        timeout_sec: float = 180.0,
    ) -> None:
        from src.ocr.paddle_provider import PaddleOCRProvider

        # Validate constructor invariants eagerly via lightweight un-loaded config check.
        self._inproc_config = PaddleOCRProvider(
            lang=lang,
            ocr_version=ocr_version,
            device=device,
            use_doc_orientation_classify=use_doc_orientation_classify,
            use_doc_unwarping=use_doc_unwarping,
            use_textline_orientation=use_textline_orientation,
            disable_model_source_check=disable_model_source_check,
            cpu_threads=cpu_threads,
            text_det_limit_side_len=text_det_limit_side_len,
        )
        self.timeout_sec = max(5.0, float(timeout_sec))
        self._repo_root = Path(__file__).resolve().parents[2]
        self._proc: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | None] | None = None
        self._stderr_tail: list[str] = []
        self._io_lock = threading.Lock()
        self._cached_meta: dict[str, Any] = self._inproc_config.provider_metadata()

    def _spawn_locked(self) -> None:
        self._kill_locked()
        cmd = [
            sys.executable,
            "-u",
            "-m",
            "src.ocr.paddle_worker",
            "--lang",
            self._inproc_config.lang,
            "--ocr-version",
            self._inproc_config.ocr_version,
            "--device",
            self._inproc_config.device,
        ]
        if self._inproc_config.use_doc_orientation_classify:
            cmd.append("--use-doc-orientation-classify")
        if self._inproc_config.use_doc_unwarping:
            cmd.append("--use-doc-unwarping")
        if self._inproc_config.use_textline_orientation:
            cmd.append("--use-textline-orientation")
        if self._inproc_config.cpu_threads is not None:
            cmd.extend(["--cpu-threads", str(self._inproc_config.cpu_threads)])
        if self._inproc_config.text_det_limit_side_len is not None:
            cmd.extend(["--text-det-limit-side-len", str(self._inproc_config.text_det_limit_side_len)])

        env = _build_worker_env(self._inproc_config.cpu_threads)
        existing_pp = env.get("PYTHONPATH", "")
        repo_str = str(self._repo_root)
        if repo_str not in existing_pp.split(os.pathsep):
            env["PYTHONPATH"] = f"{repo_str}{os.pathsep}{existing_pp}" if existing_pp else repo_str

        proc = subprocess.Popen(
            cmd,
            cwd=repo_str,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        q: queue.Queue[str | None] = queue.Queue()
        stderr_tail: list[str] = []

        def _stdout_reader() -> None:
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    q.put(line)
            finally:
                q.put(None)

        def _stderr_reader() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_tail.append(line.rstrip())
                if len(stderr_tail) > 25:
                    del stderr_tail[0]

        threading.Thread(target=_stdout_reader, daemon=True, name="paddle-worker-stdout").start()
        threading.Thread(target=_stderr_reader, daemon=True, name="paddle-worker-stderr").start()
        self._proc = proc
        self._stdout_queue = q
        self._stderr_tail = stderr_tail

    def _kill_locked(self) -> None:
        proc = self._proc
        self._proc = None
        self._stdout_queue = None
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=3.0)
        except Exception:
            pass

    def _rpc_locked(self, payload: dict[str, Any], *, timeout_sec: float) -> dict[str, Any]:
        if self._proc is None or self._proc.poll() is not None:
            self._spawn_locked()
        assert self._proc is not None and self._proc.stdin is not None and self._stdout_queue is not None
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except OSError as exc:
            self._kill_locked()
            raise RuntimeError(f"PaddleOCR worker pipe failed: {exc}") from exc

        deadline = time.monotonic() + timeout_sec
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._kill_locked()
                raise TimeoutError(
                    f"PaddleOCR worker timed out after {int(timeout_sec)}s; terminated and will respawn cleanly."
                )
            try:
                line = self._stdout_queue.get(timeout=remaining)
            except queue.Empty:
                self._kill_locked()
                raise TimeoutError(
                    f"PaddleOCR worker timed out after {int(timeout_sec)}s; terminated and will respawn cleanly."
                )
            if line is None:
                rc = self._proc.poll() if self._proc else -1
                tail = " | ".join(self._stderr_tail[-5:])
                self._kill_locked()
                detail = f" ({tail})" if tail else ""
                raise RuntimeError(f"PaddleOCR worker exited unexpectedly (rc={rc}){detail}.")
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            resp = json.loads(stripped)
            if not resp.get("ok"):
                err_type = resp.get("error_type", "RuntimeError")
                err_msg = resp.get("error", "Unknown PaddleOCR worker error")
                if err_type == "FileNotFoundError":
                    raise FileNotFoundError(err_msg)
                raise RuntimeError(f"{err_type}: {err_msg}")
            return resp

    def provider_metadata(self) -> dict[str, Any]:
        return dict(self._cached_meta)

    def recognize(self, image_path: str | Path) -> dict[str, Any]:
        img = Path(image_path)
        if not img.is_file():
            raise FileNotFoundError(f"OCR input image not found: {img}")
        with self._io_lock:
            resp = self._rpc_locked(
                {"cmd": "recognize", "image_path": str(img.resolve())},
                timeout_sec=self.timeout_sec,
            )
            result = resp["result"]
            # Refresh metadata cache once model weights/checksums have loaded.
            if self._cached_meta.get("cold_start_ms") is None and result.get("cold_start_ms"):
                try:
                    meta_resp = self._rpc_locked({"cmd": "meta", "warmup": False}, timeout_sec=15.0)
                    self._cached_meta = meta_resp["meta"]
                except Exception:
                    pass
            return result

    def close(self) -> None:
        with self._io_lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    if self._proc.stdin is not None:
                        self._proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                        self._proc.stdin.flush()
                    self._proc.wait(timeout=2.0)
                except Exception:
                    pass
            self._kill_locked()


if __name__ == "__main__":
    raise SystemExit(main())
