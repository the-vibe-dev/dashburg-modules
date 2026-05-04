from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any


def _ensure_dir(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pad_file(path: Path, target_size_bytes: int | None = None) -> None:
    if not target_size_bytes or target_size_bytes <= 0:
        return
    cur = path.stat().st_size if path.exists() else 0
    if cur >= target_size_bytes:
        return
    with path.open("ab") as fh:
        fh.write(b"0" * (target_size_bytes - cur))


def create_test_asset(
    *,
    output_dir: str,
    kind: str,
    name: str,
    content: str | None = None,
    target_size_bytes: int | None = None,
    rows: int = 10,
) -> dict[str, Any]:
    root = _ensure_dir(output_dir)
    ext_map = {
        "text": ".txt",
        "csv": ".csv",
        "json": ".json",
        "pdf": ".pdf",
        "binary": ".bin",
        "image": ".png",
        "video": ".mp4",
    }
    suffix = ext_map.get(kind, ".dat")
    filename = f"{name}{suffix}" if not str(name).endswith(suffix) else name
    path = root / filename

    if kind == "text":
        path.write_text(content or "Dashburg WebAgent text fixture\n", encoding="utf-8")
    elif kind == "csv":
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["id", "name", "email"])
            for i in range(rows):
                writer.writerow([i + 1, f"User {i+1}", f"user{i+1}@example.test"])
    elif kind == "json":
        payload = {
            "fixture": True,
            "name": name,
            "records": [{"id": i + 1, "value": f"row-{i+1}"} for i in range(rows)],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    elif kind == "pdf":
        # Minimal PDF bytes; sufficient for upload smoke testing.
        pdf = b"%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
        path.write_bytes(pdf)
    elif kind == "binary":
        path.write_bytes(os.urandom(1024))
    elif kind == "image":
        # 1x1 transparent PNG
        path.write_bytes(
            bytes.fromhex(
                "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4890000000A49444154789C6360000002000154A24F5D0000000049454E44AE426082"
            )
        )
    elif kind == "video":
        # Placeholder binary clip when ffmpeg generation is unavailable.
        path.write_bytes(b"DASHBURG_FAKE_VIDEO_PLACEHOLDER")
    else:
        path.write_text(content or "generic fixture\n", encoding="utf-8")

    _pad_file(path, target_size_bytes)
    return {
        "ok": True,
        "kind": kind,
        "path": str(path),
        "name": path.name,
        "size_bytes": path.stat().st_size,
    }
