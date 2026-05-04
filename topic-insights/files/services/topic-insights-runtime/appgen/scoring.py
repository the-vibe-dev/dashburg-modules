from __future__ import annotations
from typing import Any

SCORE_KEYS = [
    "pain_score",
    "market_score",
    "monetization_score",
    "complexity_score",
    "distribution_score",
    "ai_leverage_score",
]


def clamp_0_10(v: float) -> float:
    return max(0.0, min(10.0, float(v)))


def compute_overall(scores: dict[str, Any]) -> float:
    pain = clamp_0_10(scores["pain_score"])
    market = clamp_0_10(scores["market_score"])
    monetization = clamp_0_10(scores["monetization_score"])
    complexity = clamp_0_10(scores["complexity_score"])
    distribution = clamp_0_10(scores["distribution_score"])
    ai_lev = clamp_0_10(scores["ai_leverage_score"])
    overall = 0.22 * pain + 0.22 * market + 0.16 * monetization + 0.12 * distribution + 0.12 * ai_lev + 0.16 * (10 - complexity)
    return round(clamp_0_10(overall), 3)


def normalize_scores(scores: dict[str, Any] | None) -> tuple[dict[str, float] | None, bool]:
    if not scores:
        return None, True
    out: dict[str, float] = {}
    for k in SCORE_KEYS:
        if scores.get(k) is None:
            return None, True
        try:
            v = float(scores[k])
        except Exception:
            return None, True
        if v < 0 or v > 10:
            return None, True
        out[k] = round(v, 3)
    out["overall_score"] = compute_overall(out)
    return out, False
