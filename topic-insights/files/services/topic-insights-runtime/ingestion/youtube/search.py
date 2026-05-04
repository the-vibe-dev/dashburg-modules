from __future__ import annotations
from datetime import datetime
import hashlib
import logging
from storage.models import RawPost
from core.config import settings
from core.http_client import get_shared_async_client, run_async

def youtube_search(query: str, limit: int = 20, region: str = "US") -> list[RawPost]:
    """Optional: uses youtubesearchpython (scrapes YouTube search)."""
    log = logging.getLogger(__name__)
    log.info("youtube_search query=%s limit=%s region=%s", query, limit, region)
    if settings.youtube_api_key:
        try:
            return _youtube_search_api(query, limit=limit, region=region)
        except Exception as e:
            log.warning("youtube_search_api_failed fallback_scrape error=%s", e)
    try:
        from youtubesearchpython import VideosSearch
    except Exception as e:
        raise RuntimeError("YouTube search requires `youtubesearchpython`. Install it separately if needed.") from e

    vs = VideosSearch(query, limit=min(limit, settings.youtube_search_max_results), region=region)
    results = vs.result().get("result", [])
    out: list[RawPost] = []
    for r in results:
        url = r.get("link") or ""
        title = r.get("title") or ""
        desc = r.get("descriptionSnippet")
        if isinstance(desc, list):
            desc = " ".join([x.get("text","") for x in desc])
        desc = desc or ""
        # No comments without API; still useful for pain signals via descriptions/titles
        combined = (title + "\n\n" + desc).strip()
        hid = hashlib.sha1((url + title).encode()).hexdigest()
        out.append(RawPost(
            id=f"youtube:{hid}",
            source="youtube",
            url=url,
            author=(r.get("channel", {}) or {}).get("name"),
            timestamp=datetime.utcnow(),
            text=combined[:20000],
            engagement_score=int(r.get("viewCount", {}).get("text","0").split()[0].replace(",","") or 0) if r.get("viewCount") else 0,
            metadata_={"duration": r.get("duration"), "publishedTime": r.get("publishedTime"), "video_id": (r.get("id") or r.get("link", "").split("v=")[-1].split("&")[0])}
        ))
    log.info("youtube_search_done count=%s", len(out))
    return out

def _youtube_search_api(query: str, limit: int, region: str) -> list[RawPost]:
    async def _call():
        client = await get_shared_async_client()
        params = {
            "key": settings.youtube_api_key,
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(limit, settings.youtube_search_max_results),
            "regionCode": region,
        }
        r = await client.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=20.0)
        r.raise_for_status()
        return r.json()
    data = run_async(_call())
    items = data.get("items", []) or []
    out: list[RawPost] = []
    for r in items:
        vid = (r.get("id") or {}).get("videoId") or ""
        snippet = r.get("snippet") or {}
        title = snippet.get("title") or ""
        desc = snippet.get("description") or ""
        url = f"https://www.youtube.com/watch?v={vid}"
        combined = (title + "\n\n" + desc).strip()
        hid = hashlib.sha1((url + title).encode()).hexdigest()
        out.append(RawPost(
            id=f"youtube:{hid}",
            source="youtube",
            url=url,
            author=(snippet.get("channelTitle") or ""),
            timestamp=datetime.utcnow(),
            text=combined[:20000],
            engagement_score=0,
            metadata_={"duration": None, "publishedTime": snippet.get("publishedAt"), "video_id": vid},
        ))
    return out
