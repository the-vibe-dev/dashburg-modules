from __future__ import annotations
import json
from pathlib import Path
from appgen.config import load_config

TEXT_FIELDS = ("text", "body", "content", "summary", "title", "comment", "description")


def extract_from_json_folder(limit: int = 200) -> list[dict]:
    cfg = load_config()["appgen"]["pain_sources"]
    folder = Path(cfg.get("json_folder_path", "./data/pain_sources"))
    if not folder.exists():
        return []
    out: list[dict] = []
    for p in sorted(folder.glob("*")):
        if p.suffix.lower() not in (".json", ".jsonl"):
            continue
        if p.suffix.lower() == ".jsonl":
            lines = p.read_text(encoding="utf-8").splitlines()
            objs = [json.loads(x) for x in lines if x.strip()]
        else:
            raw = json.loads(p.read_text(encoding="utf-8"))
            objs = raw if isinstance(raw, list) else [raw]
        for i, obj in enumerate(objs):
            if isinstance(obj, dict):
                parts = [str(obj.get(k, "")).strip() for k in TEXT_FIELDS if obj.get(k)]
                text = "\n".join([x for x in parts if x])[:2000]
            else:
                text = str(obj)[:2000]
            if not text.strip():
                continue
            out.append({"source_type": "json_folder", "source_ref": f"json:{p.name}:{i}", "text": text})
            if len(out) >= limit:
                return out
    return out
