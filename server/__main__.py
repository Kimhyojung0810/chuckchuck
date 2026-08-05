"""
서버 실행 진입점입니다.

    python -m server
"""

from __future__ import annotations

import logging
import os

import uvicorn

from chuckchuck import settings


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )

    host = os.environ.get("SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("SERVER_PORT", "8000") or 8000)

    print(f"척척발표 API (rough) → http://{host}:{port}/", flush=True)
    print(f"  docs: http://{host}:{port}/docs", flush=True)
    print(f"  MOCK_EXTERNAL_APIS={settings.mock_external}", flush=True)
    print(settings.masked(), flush=True)

    uvicorn.run("server.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
