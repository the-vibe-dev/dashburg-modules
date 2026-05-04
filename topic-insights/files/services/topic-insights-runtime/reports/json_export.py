from __future__ import annotations
import json
from storage.models import PainCluster, Idea

def export_json(clusters: list[PainCluster], ideas: list[Idea]) -> dict:
    return {
        "clusters": [c.model_dump() for c in clusters],
        "ideas": [i.model_dump() for i in ideas],
    }

def write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
