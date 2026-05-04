from __future__ import annotations
from dataclasses import dataclass
from math import log1p

def normalize_engagement(x: float) -> float:
    # soft log scaling
    return min(1.0, log1p(max(0.0, x)) / log1p(500.0))

def pain_score(normalized_engagement: float, intensity: float, frequency: float, workaround: bool, weights: dict) -> float:
    return (
        weights["engagement"] * normalized_engagement
        + weights["intensity"] * intensity
        + weights["frequency"] * frequency
        + weights["workaround_bonus"] * (1.0 if workaround else 0.0)
    )

def competition_penalty(competitor_count: float, seo_saturation: float, funding_signal: float, weights: dict) -> float:
    return (
        weights["competitor_count"] * competitor_count
        + weights["seo_saturation"] * seo_saturation
        + weights["funding_signal"] * funding_signal
    )

def final_opportunity(pain: float, simplicity: float, monetization: float, comp_pen: float, weights: dict) -> float:
    # pain/simplicity/monetization assumed 0..1, comp_pen 0..1
    score = (weights["pain"] * pain) + (weights["simplicity"] * simplicity) + (weights["monetization"] * monetization) - (weights["competition_penalty"] * comp_pen)
    return max(0.0, min(1.0, score))
