from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse
from core.config import settings
from ingestion.web.router import search as web_router_search
from core.http_client import run_async

APP_STORE_HINTS = ("apps.apple.com", "play.google.com", "chrome.google.com", "microsoftedge.microsoft.com")
BIG_SAAS_HINTS = ("zapier.com", "notion.so", "airtable.com", "asana.com", "trello.com", "monday.com")

@dataclass
class CompetitionSignals:
    competitor_count_norm: float
    seo_saturation_norm: float
    funding_signal_norm: float
    app_store_presence: float
    big_saas_presence: float

def scan_competition(cluster_label: str, n: int | None = None) -> CompetitionSignals:
    if not settings.competition_scan_enabled:
        return CompetitionSignals(0.0, 0.0, 0.0, 0.0, 0.0)
    n = n or settings.competition_scan_results
    q1 = f"{cluster_label} app"
    q2 = f"best {cluster_label} app"
    results = []
    try:
        results.extend(run_async(web_router_search(query=q1, limit=n)))
        results.extend(run_async(web_router_search(query=q2, limit=max(5, n//2))))
    except Exception:
        results = []
    domains = set()
    app_store = 0
    big_saas = 0
    reviewish = 0
    for r in results:
        url = r.url if hasattr(r, "url") else (r.get("href") or r.get("url") or "")
        dom = urlparse(url).netloc.lower()
        if dom:
            domains.add(dom)
        if any(h in dom for h in APP_STORE_HINTS):
            app_store += 1
        if any(h in dom for h in BIG_SAAS_HINTS):
            big_saas += 1
        title = (getattr(r, "title", "") or "").lower()
        body = (getattr(r, "snippet", "") or "").lower()
        if any(k in title or k in body for k in ("best", "top", "review", "alternatives", "vs")):
            reviewish += 1

    competitor_count_norm = min(1.0, len(domains) / max(1.0, float(n)))
    seo_saturation_norm = min(1.0, reviewish / max(1.0, float(len(results))))
    # MVP: funding signal unknown; keep 0
    return CompetitionSignals(
        competitor_count_norm=competitor_count_norm,
        seo_saturation_norm=seo_saturation_norm,
        funding_signal_norm=0.0,
        app_store_presence=min(1.0, app_store / max(1.0, float(len(results)))),
        big_saas_presence=min(1.0, big_saas / max(1.0, float(len(results)))),
    )
