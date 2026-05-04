from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs
import re
from ingestion.web.router import search as web_router_search
from core.http_client import get_shared_async_client, run_async
from core.config import settings

@dataclass
class AppScanResult:
    apps: list[dict]

def _extract_play_id(url: str) -> str | None:
    try:
        q = parse_qs(urlparse(url).query)
        return (q.get("id") or [None])[0]
    except Exception:
        return None

def _extract_apple_id(url: str) -> str | None:
    m = re.search(r"/id(\d+)", url)
    return m.group(1) if m else None

def _fetch_play_reviews(app_id: str, max_reviews: int) -> list[dict]:
    try:
        from google_play_scraper import reviews, Sort
        res, _ = reviews(app_id, lang="en", country="us", sort=Sort.NEWEST, count=max_reviews)
        out = []
        for r in res:
            out.append({"rating": r.get("score"), "text": (r.get("content") or "")[:1200], "at": str(r.get("at") or ""), "source": "google_play"})
        return out
    except Exception:
        return []

def _fetch_apple_reviews(app_id: str, max_reviews: int) -> list[dict]:
    # iTunes RSS (best-effort)
    url = f"https://itunes.apple.com/rss/customerreviews/id={app_id}/sortBy=mostRecent/json"
    try:
        async def _get():
            client = await get_shared_async_client()
            r = await client.get(url, timeout=20.0, follow_redirects=True)
            if r.status_code != 200:
                return None
            return r.json()
        data = run_async(_get())
        if data is None:
            return []
        entries = (data.get("feed", {}) or {}).get("entry", []) or []
        out = []
        for e in entries[1:]:  # first entry is app meta
            rating = None
            try:
                rating = int((((e.get("im:rating") or {}) ).get("label")) )
            except Exception:
                rating = None
            text = ""
            try:
                text = (e.get("content") or {}).get("label") or ""
            except Exception:
                text = ""
            out.append({"rating": rating, "text": text[:1200], "at": str((e.get("updated") or {}).get("label") or ""), "source": "apple"})
            if len(out) >= max_reviews:
                break
        return out
    except Exception:
        return []

def scan_appstore(cluster_label: str) -> AppScanResult:
    if not settings.appstore_scan_enabled:
        return AppScanResult(apps=[])
    q = f"{cluster_label} app"
    results = run_async(web_router_search(query=q, limit=max(10, settings.appstore_max_apps * 3)))
    apps=[]
    for r in results:
        url = r.url if hasattr(r, "url") else (r.get("href") or r.get("url") or "")
        dom = urlparse(url).netloc.lower()
        title = getattr(r, "title", "") or ""
        if "play.google.com" in dom and "store/apps/details" in url:
            pid = _extract_play_id(url)
            if not pid:
                continue
            reviews = _fetch_play_reviews(pid, settings.appstore_max_reviews)
            apps.append({"store":"google_play","app_id":pid,"url":url,"title":title,"reviews":reviews})
        elif "apps.apple.com" in dom:
            aid = _extract_apple_id(url)
            if not aid:
                continue
            reviews = _fetch_apple_reviews(aid, settings.appstore_max_reviews)
            apps.append({"store":"apple","app_id":aid,"url":url,"title":title,"reviews":reviews})
        if len(apps) >= settings.appstore_max_apps:
            break
    return AppScanResult(apps=apps)
