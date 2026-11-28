#!/usr/bin/env python3
"""Manage a local project-scoped PostgreSQL 18 instance (no Docker required)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _pg_bin(name: str) -> str:
    bin_path = _repo_root() / ".tools" / "postgres" / "bin" / name
    if not bin_path.is_file():
        raise FileNotFoundError(f"PostgreSQL binary not found: {bin_path}")
    return str(bin_path)


def init_and_start(
    pgdata: Path,
    port: int,
    *,
    auth_method: str = "trust",
    superuser_password: str | None = None,
) -> None:
    pgdata.parent.mkdir(parents=True, exist_ok=True)
    log_file = pgdata.parent / "postgres.log"

    if not (pgdata / "PG_VERSION").is_file():
        init_cmd = [_pg_bin("initdb"), "-D", str(pgdata), "-U", "postgres", f"--auth={auth_method}", "--encoding=UTF8"]
        pwfile_path: Path | None = None
        if superuser_password:
            pwfile_path = pgdata.parent / ".pg_init_pw"
            pwfile_path.write_text(superuser_password + "\n", encoding="utf-8")
            os.chmod(pwfile_path, 0o600)
            init_cmd.extend(["--pwfile", str(pwfile_path)])
        try:
            subprocess.run(init_cmd, check=True)
        finally:
            if pwfile_path is not None and pwfile_path.exists():
                pwfile_path.unlink()
        conf = pgdata / "postgresql.conf"
        with conf.open("a", encoding="utf-8") as handle:
            handle.write(f"\nlisten_addresses = '127.0.0.1'\nport = {port}\nunix_socket_directories = '{pgdata.parent}'\n")

    status = subprocess.run([_pg_bin("pg_ctl"), "-D", str(pgdata), "status"], capture_output=True)
    if status.returncode != 0:
        subprocess.run(
            [_pg_bin("pg_ctl"), "-D", str(pgdata), "-l", str(log_file), "-o", f"-p {port}", "start"],
            check=True,
        )

    # Ensure role and database exist idempotently.
    env = {**os.environ, "PGHOST": "127.0.0.1", "PGPORT": str(port)}
    if superuser_password and "PGPASSWORD" not in env:
        env["PGPASSWORD"] = superuser_password
    role_exists = subprocess.run(
        [_pg_bin("psql"), "-U", "postgres", "-d", "postgres", "-tAc", "SELECT 1 FROM pg_roles WHERE rolname='telugu_digitizer';"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    ).stdout.strip()
    if role_exists != "1":
        subprocess.run(
            [_pg_bin("psql"), "-U", "postgres", "-d", "postgres", "-c", "CREATE ROLE telugu_digitizer WITH LOGIN PASSWORD 'telugu_digitizer';"],
            env=env,
            check=True,
        )

    for db_name in ("telugu_digitizer", "telugu_digitizer_test"):
        db_exists = subprocess.run(
            [_pg_bin("psql"), "-U", "postgres", "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{db_name}';"],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        ).stdout.strip()
        if db_exists != "1":
            subprocess.run(
                [_pg_bin("psql"), "-U", "postgres", "-d", "postgres", "-c", f"CREATE DATABASE {db_name} OWNER telugu_digitizer;"],
                env=env,
                check=True,
            )


def stop(pgdata: Path) -> None:
    if (pgdata / "PG_VERSION").is_file():
        subprocess.run([_pg_bin("pg_ctl"), "-D", str(pgdata), "stop", "-m", "fast"], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start or stop local PostgreSQL for development/tests.")
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--pgdata", type=Path, default=_repo_root() / ".tools" / "pgdata")
    parser.add_argument("--auth", choices=["trust", "scram-sha-256"], default="trust")
    parser.add_argument("--superuser-password", default=None)
    args = parser.parse_args()

    if args.action == "start":
        init_and_start(
            args.pgdata,
            args.port,
            auth_method=args.auth,
            superuser_password=args.superuser_password,
        )
        print(f"PostgreSQL running on 127.0.0.1:{args.port} (data={args.pgdata})")
    elif args.action == "stop":
        stop(args.pgdata)
        print("PostgreSQL stopped.")
    else:
        proc = subprocess.run([_pg_bin("pg_ctl"), "-D", str(args.pgdata), "status"], check=False)
        return proc.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
