from __future__ import annotations
from datetime import datetime
import hashlib
from ingestion.common.http import get
import logging
from core.config import settings
from storage.models import RawPost

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

def fetch_video_comments(video_id: str, max_comments: int = 50) -> list[RawPost]:
    if not settings.youtube_api_key:
        raise RuntimeError("YOUTUBE_API_KEY not set")
    log = logging.getLogger(__name__)
    log.info("youtube_comments_fetch video_id=%s max_comments=%s", video_id, max_comments)
    out: list[RawPost] = []
    page_token = None
    fetched = 0
    while fetched < max_comments:
        params = {
            "key": settings.youtube_api_key,
            "part": "snippet",
            "videoId": video_id,
            "maxResults": min(100, max_comments - fetched),
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token
        r = get(f"{YOUTUBE_API}/commentThreads", params=params, timeout=30.0, limiter_name="youtube")
        data = r.json()
        items = data.get("items", [])
        for it in items:
            sn = (it.get("snippet", {}) or {}).get("topLevelComment", {}).get("snippet", {}) or {}
            text = (sn.get("textDisplay") or "").strip()
            if not text:
                continue
            author = sn.get("authorDisplayName")
            published = sn.get("publishedAt")
            ts = datetime.utcnow()
            if published:
                try:
                    ts = datetime.fromisoformat(published.replace("Z","+00:00")).replace(tzinfo=None)
                except Exception:
                    ts = datetime.utcnow()
            cid = it.get("id") or hashlib.sha1((video_id+text).encode()).hexdigest()
            out.append(RawPost(
                id=f"youtube_comment:{cid}",
                source="youtube_comment",
                url=f"https://www.youtube.com/watch?v={video_id}&lc={cid}",
                author=author,
                timestamp=ts,
                text=text[:20000],
                engagement_score=int(sn.get("likeCount") or 0),
                metadata_={"video_id": video_id}
            ))
            fetched += 1
            if fetched >= max_comments:
                break
        page_token = data.get("nextPageToken")
        if not page_token or fetched >= max_comments:
            break
    log.info("youtube_comments_done video_id=%s count=%s", video_id, len(out))
    return out
