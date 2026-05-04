from __future__ import annotations
import yaml
from pathlib import Path

def load_scoring_config(path: str = "scoring_config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        # allow running from package root
        p = Path(__file__).resolve().parents[1] / "scoring_config.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))
