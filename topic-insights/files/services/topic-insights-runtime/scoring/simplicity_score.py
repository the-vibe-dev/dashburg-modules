from __future__ import annotations

def simplicity_score(cluster_label: str, rules: dict) -> float:
    # heuristic: detect complexity hints in label
    label = cluster_label.lower()
    score = 6  # base 1..10

    if any(k in label for k in ["hardware", "device", "sensor", "camera"]):
        score -= rules.get("hardware_required_penalty", 3)
    if any(k in label for k in ["marketplace", "community", "social network"]):
        score -= rules.get("network_effects_penalty", 2)
    if any(k in label for k in ["medical", "insurance", "legal", "tax"]):
        score -= rules.get("regulatory_risk_penalty", 2)

    if any(k in label for k in ["tracker", "reminder", "checklist", "calculator", "template"]):
        score += rules.get("single_purpose_bonus", 2)
    if any(k in label for k in ["api", "sync", "import"]):
        score += rules.get("api_leverage_bonus", 2)

    score = max(1, min(10, score))
    return score / 10.0
