from __future__ import annotations
from dataclasses import dataclass
from core.config import settings

@dataclass
class DemandResult:
    demand_score: float  # 0..1
    summary: dict

def demand_proxy(keyword: str) -> DemandResult:
    """Google Trends demand proxy using pytrends. Best-effort; returns 0 score on failure."""
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=360)
        pytrends.build_payload([keyword], cat=0, timeframe=settings.google_trends_timeframe, geo=settings.google_trends_geo, gprop="")
        df = pytrends.interest_over_time()
        if df is None or df.empty:
            return DemandResult(0.0, {"reason": "no_data"})
        series = df[keyword]
        avg = float(series.mean())
        last = float(series.iloc[-1])
        first = float(series.iloc[0])
        growth = 0.0
        if first > 0:
            growth = (last - first) / first
        # normalize average interest 0..100 => 0..1
        avg_norm = max(0.0, min(1.0, avg / 100.0))
        growth_norm = max(0.0, min(1.0, (growth + 1.0) / 2.0))  # -1..+1 mapped to 0..1
        score = 0.75 * avg_norm + 0.25 * growth_norm
        return DemandResult(score, {"avg": avg, "first": first, "last": last, "growth": growth, "geo": settings.google_trends_geo, "timeframe": settings.google_trends_timeframe})
    except Exception as e:
        return DemandResult(0.0, {"reason": "error", "error": str(e)[:200]})
