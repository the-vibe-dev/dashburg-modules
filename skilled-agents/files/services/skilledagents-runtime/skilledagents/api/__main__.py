from __future__ import annotations

import os

import uvicorn

from skilledagents.api.app import app


def main() -> None:
    host = os.getenv("SKILLEDAGENTS_HOST", "0.0.0.0")
    port = int(os.getenv("SKILLEDAGENTS_PORT", "8787"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
