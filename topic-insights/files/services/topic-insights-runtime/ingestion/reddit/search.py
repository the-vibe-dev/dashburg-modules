from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from typing import List
import logging
from ingestion.common.http import get
from storage.models import RawPost

def reddit_search(query: str, limit: int = 50) -> list[RawPost]:
    # Public endpoint; may require good UA and small pacing.
    log = logging.getLogger(__name__)
    log.info("reddit_search query=%s limit=%s", query, limit)
    url = "https://www.reddit.com/search.json"
    params = {"q": query, "limit": min(limit, 100), "sort": "relevance", "t": "year"}
    r = get(url, params=params, limiter_name="reddit")
    data = r.json()
    out: list[RawPost] = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        post_id = d.get("id") or hashlib.sha1((d.get("permalink","")+d.get("title","")).encode()).hexdigest()
        permalink = d.get("permalink", "")
        full_url = "https://www.reddit.com" + permalink if permalink.startswith("/") else (d.get("url") or "")
        title = d.get("title") or ""
        selftext = d.get("selftext") or ""
        text = (title + "\n\n" + selftext).strip()
        created = d.get("created_utc")
        ts = datetime.fromtimestamp(created, tz=timezone.utc) if created else datetime.now(tz=timezone.utc)
        engagement = int((d.get("score") or 0) + (d.get("num_comments") or 0))
        author = d.get("author")
        out.append(RawPost(
            id=f"reddit:{post_id}",
            source="reddit",
            url=full_url,
            author=author,
            timestamp=ts.replace(tzinfo=None),
            text=text[:20000],
            engagement_score=engagement,
            metadata_={"subreddit": d.get("subreddit"), "score": d.get("score"), "num_comments": d.get("num_comments")}
        ))
    log.info("reddit_search_done count=%s", len(out))
    return out
