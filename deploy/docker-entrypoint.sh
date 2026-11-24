#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
import os
import sys
import time
import psycopg

raw_url = os.environ.get("DATABASE_URL", "")
if not raw_url:
    sys.exit(0)
dsn = raw_url.replace("postgresql+psycopg://", "postgresql://", 1)

for attempt in range(1, 31):
    try:
        with psycopg.connect(dsn, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        print(f"PostgreSQL reachable (attempt {attempt}).")
        break
    except Exception as exc:
        if attempt == 30:
            print(f"PostgreSQL unreachable after 30 attempts: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(1)
PY

alembic upgrade head
exec python scripts/run_api.py
