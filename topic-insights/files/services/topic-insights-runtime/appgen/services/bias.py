from __future__ import annotations
from pathlib import Path
from appgen.repo import latest_artifact

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def base_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def current_bias_block() -> str:
    art = latest_artifact("workflow_adjustment")
    if not art:
        return ""
    return art.get("content_text", "")


def with_bias(text: str) -> str:
    bias = current_bias_block().strip()
    if not bias:
        return text
    return text + "\n\n### WORKFLOW BIAS\n" + bias
