from __future__ import annotations
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

CONFIG_PATH = Path("./data/config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "appgen": {
        "enabled": True,
        "pain_sources": {
            "oie_db_path_candidates": ["./oie.db", "./data/oie.db", "/mnt/data/oie.db"],
            "json_folder_path": "./data/pain_sources",
        },
        "llm": {
            "default_provider": "local_stub",
            "default_model": "local-stub-v1",
            "strong_provider": "openai",
            "strong_model": "gpt-5",
            "use_strong_model_for_plan": False,
            "use_strong_model_for_final_review": False,
            "use_strong_model_for_validation": False,
            "use_strong_model_for_meta_analysis": False,
            "max_calls_per_day": 200,
            "max_calls_per_idea": 6,
            "max_output_tokens_per_call": 2500,
            "daily_cost_budget_usd": 2.00,
            "per_idea_cost_budget_usd": 0.15,
            "cache_enabled": True,
            "cache_ttl_hours": 168,
        },
        "workflow": {
            "ideas_per_generate": 5,
            "high_score_threshold": 8.2,
            "auto_followups_for_missed": True,
            "followup_ideas_per_cluster": 2,
            "allow_stub_persistence": False,
            "dedupe_window_days": 180,
            "min_distinct_categories": 3,
            "min_distinct_pain_themes": 3,
        },
        "export": {"appcreator_out_dir": "./data/appcreator_inbox"},
        "events": {"enable_sse": True},
    }
}


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(dst)
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        return deepcopy(DEFAULT_CONFIG)
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    merged = _deep_merge(DEFAULT_CONFIG, raw)
    if merged != raw:
        CONFIG_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_CONFIG, cfg)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return merged
