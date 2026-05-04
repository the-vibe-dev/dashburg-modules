from __future__ import annotations
from dataclasses import dataclass

def simulate_pricing(idea_name: str, cluster_label: str, monetization_score_1_10: float) -> dict:
    label = cluster_label.lower()
    b2b = any(k in label for k in ["business","invoice","client","crm","contract","agency","vendor","sales"])
    # choose base tiers
    if b2b:
        tiers = [{"name":"Starter","price_monthly":19},{"name":"Pro","price_monthly":49},{"name":"Team","price_monthly":99}]
        visitors = 1200
        conv = 0.02 + (monetization_score_1_10/10.0)*0.01
        churn = 0.06
    else:
        tiers = [{"name":"Basic","price_monthly":5},{"name":"Plus","price_monthly":9},{"name":"Pro","price_monthly":15}]
        visitors = 2500
        conv = 0.01 + (monetization_score_1_10/10.0)*0.008
        churn = 0.08
    # scenarios
    def mrr(v, c, price):
        subs = v * c
        return subs * price
    mid_price = tiers[1]["price_monthly"]
    scenarios = {
        "conservative": {"visitors_mo": int(visitors*0.6), "conversion": round(conv*0.7,4), "mrr": round(mrr(visitors*0.6, conv*0.7, mid_price),2)},
        "base": {"visitors_mo": int(visitors), "conversion": round(conv,4), "mrr": round(mrr(visitors, conv, mid_price),2)},
        "optimistic": {"visitors_mo": int(visitors*1.8), "conversion": round(conv*1.4,4), "mrr": round(mrr(visitors*1.8, conv*1.4, mid_price),2)},
    }
    return {
        "model": "subscription",
        "b2b": b2b,
        "tiers": tiers,
        "assumptions": {"visitors_mo": visitors, "conversion": round(conv,4), "churn": churn},
        "scenarios": scenarios,
        "notes": "Heuristic pricing + simple MRR projection; validate with landing tests."
    }
