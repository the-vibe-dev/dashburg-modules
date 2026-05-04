from __future__ import annotations

def monetization_score(cluster_label: str) -> float:
    label = cluster_label.lower()
    score = 5
    if any(k in label for k in ["business", "invoice", "client", "contract", "freelance", "crm"]):
        score += 3
    if any(k in label for k in ["reminder", "scheduler", "tracking", "maintenance"]):
        score += 1
    if any(k in label for k in ["fun", "meme", "joke"]):
        score -= 2
    score = max(1, min(10, score))
    return score / 10.0
