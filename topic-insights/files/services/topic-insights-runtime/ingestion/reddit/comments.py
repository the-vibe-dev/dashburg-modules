from __future__ import annotations
from datetime import datetime, timezone
import hashlib
from typing import Iterable
import logging
from ingestion.common.http import get
from storage.models import RawPost

def _flatten_comments(children: list, out: list[dict], depth: int = 0, max_depth: int = 4) -> None:
    if depth > max_depth:
        return
    for c in children or []:
        kind = c.get("kind")
        data = c.get("data", {}) if isinstance(c, dict) else {}
        if kind == "t1":  # comment
            body = data.get("body") or ""
            if body and body not in ("[deleted]", "[removed]"):
                out.append({
                    "id": data.get("id"),
                    "author": data.get("author"),
                    "created_utc": data.get("created_utc"),
                    "body": body,
                    "score": data.get("score", 0),
                    "permalink": data.get("permalink", ""),
                })
            # replies
            replies = data.get("replies")
            if isinstance(replies, dict):
                _flatten_comments(replies.get("data", {}).get("children", []), out, depth+1, max_depth=max_depth)
        elif kind == "more":
            # ignore "more" for MVP
            continue

def reddit_fetch_comments(post_fullname_or_id: str, limit: int = 80) -> list[RawPost]:
    # post_fullname_or_id expects base36 id (e.g., "abc123") or fullname "t3_abc123"
    log = logging.getLogger(__name__)
    pid = post_fullname_or_id.replace("t3_", "")
    log.info("reddit_comments_fetch post_id=%s limit=%s", pid, limit)
    url = f"https://www.reddit.com/comments/{pid}.json"
    params = {"limit": min(limit, 500), "sort": "top"}
    r = get(url, params=params, limiter_name="reddit")
    data = r.json()
    out_items: list[dict] = []
    # data[1] is comments listing
    if isinstance(data, list) and len(data) >= 2:
        comments = data[1].get("data", {}).get("children", [])
        _flatten_comments(comments, out_items, depth=0)
    posts: list[RawPost] = []
    for c in out_items:
        cid = c.get("id") or hashlib.sha1((c.get("permalink","")+c.get("body","")).encode()).hexdigest()
        permalink = c.get("permalink","")
        full_url = "https://www.reddit.com" + permalink if permalink.startswith("/") else permalink
        created = c.get("created_utc")
        ts = datetime.fromtimestamp(created, tz=timezone.utc) if created else datetime.now(tz=timezone.utc)
        engagement = int(max(0, c.get("score", 0)))
        text = c.get("body","").strip()
        if not text:
            continue
        posts.append(RawPost(
            id=f"reddit_comment:{cid}",
            source="reddit_comment",
            url=full_url,
            author=c.get("author"),
            timestamp=ts.replace(tzinfo=None),
            text=text[:20000],
            engagement_score=engagement,
            metadata_={"parent_post_id": f"reddit:{pid}"}
        ))
    log.info("reddit_comments_done post_id=%s count=%s", pid, len(posts))
    return posts
