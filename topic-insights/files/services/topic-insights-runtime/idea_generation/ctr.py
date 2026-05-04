from __future__ import annotations
import re

def ctr_heuristic(landing_text: str) -> float:
    """Estimate landing page CTR (0..1) from copy quality signals."""
    t = landing_text.strip()
    if not t:
        return 0.05
    # Basic signals
    words = re.findall(r"\w+", t)
    wcount = len(words)
    has_pricing = "pricing" in t.lower() or "$" in t
    has_cta = any(k in t.lower() for k in ["get started","try","sign up","start","join","free"])
    bullets = t.count("\n-") + t.count("•")
    # readability (lower grade => better)
    try:
        from textstat import textstat
        grade = textstat.flesch_kincaid_grade(t)
    except Exception:
        grade = 10.0
    grade_score = max(0.0, min(1.0, (12.0 - grade) / 12.0))
    length_score = 1.0 if 120 <= wcount <= 450 else (0.7 if 80 <= wcount <= 700 else 0.45)
    structure_score = min(1.0, 0.3 + 0.1*min(7, bullets))
    cta_score = 1.0 if has_cta else 0.5
    pricing_score = 1.0 if has_pricing else 0.6

    raw = 0.22*grade_score + 0.22*length_score + 0.22*structure_score + 0.18*cta_score + 0.16*pricing_score
    # map to plausible CTR range (2%..18%)
    ctr = 0.02 + raw * 0.16
    return float(max(0.01, min(0.25, ctr)))
