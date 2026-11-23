#!/usr/bin/env python3
"""Run the Phase 2 FastAPI server bound strictly to localhost by default."""

from __future__ import annotations

import uvicorn

from src.api.app import create_app
from src.core.config import AppSettings


def main() -> None:
    settings = AppSettings.from_env()
    app = create_app(settings)
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
