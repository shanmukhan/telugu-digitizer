#!/usr/bin/env python3
"""Run the Phase 2 FastAPI server bound strictly to localhost by default."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import uvicorn

from src.api.app import create_app
from src.core.config import AppSettings


def _ensure_local_postgres(settings: AppSettings) -> None:
    """Start the project-local PostgreSQL cluster when targeting localhost:5432 and stopped."""
    db_url = settings.database_url.replace("+psycopg", "")
    parsed = urlparse(db_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 5432
    if host not in {"127.0.0.1", "localhost"} or port != 5432:
        return

    try:
        with socket.create_connection((host, port), timeout=0.5):
            return
    except OSError:
        pass

    repo_root = Path(__file__).resolve().parents[1]
    pg_ctl = repo_root / ".tools" / "postgres" / "bin" / "pg_ctl"
    pgdata = repo_root / ".tools" / "pgdata"
    manage_script = repo_root / "scripts" / "manage_local_pg.py"
    if pg_ctl.is_file() and (pgdata / "PG_VERSION").is_file() and manage_script.is_file():
        print("PostgreSQL is not running on 127.0.0.1:5432; starting project-local cluster...")
        subprocess.run([sys.executable, str(manage_script), "start"], check=True)
    else:
        print(
            f"Warning: PostgreSQL is not accepting connections on {host}:{port}. "
            "Start PostgreSQL first (e.g. `.venv/bin/python scripts/manage_local_pg.py start` "
            "or `docker compose up -d postgres`).",
            file=sys.stderr,
        )


def main() -> None:
    settings = AppSettings.from_env()
    _ensure_local_postgres(settings)
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        proxy_headers=settings.proxy_headers,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
