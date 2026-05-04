from __future__ import annotations

from datetime import datetime, timezone

import httpx

from trend_harvester.config import Settings
from trend_harvester.services.http_utils import TTLCache, with_retries


class RedditConnector:
    def __init__(self, settings: Settings, cache: TTLCache | None = None):
        self.settings = settings
        self.cache = cache or TTLCache(ttl_seconds=180)

    async def fetch(self, subreddits: list[str], per_subreddit_limit: int) -> list[dict]:
        out: list[dict] = []
        for sub in subreddits:
            cache_key = f"reddit:{sub}:{per_subreddit_limit}"
            payload = self.cache.get(cache_key) if self.settings.enable_source_cache else None
            if payload is None:
                payload = await self._request(sub, per_subreddit_limit)
                if self.settings.enable_source_cache:
                    self.cache.set(cache_key, payload)

            for child in payload.get("data", {}).get("children", []):
                post = child.get("data", {})
                post_id = post.get("id")
                if not post_id:
                    continue
                permalink = post.get("permalink", "")
                out.append(
                    {
                        "source": "reddit",
                        "source_id": post_id,
                        "title": post.get("title", ""),
                        "url": f"https://www.reddit.com{permalink}",
                        "published_at": datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc),
                        "raw_json": {
                            "subreddit": post.get("subreddit"),
                            "score": post.get("score"),
                            "num_comments": post.get("num_comments"),
                            "upvote_ratio": post.get("upvote_ratio"),
                        },
                        "metrics": {
                            "score": post.get("score"),
                            "num_comments": post.get("num_comments"),
                            "upvote_ratio": post.get("upvote_ratio"),
                        },
                    }
                )
        return out

    async def _request(self, subreddit: str, limit: int) -> dict:
        async def _do_request() -> dict:
            headers = {"User-Agent": self.settings.reddit_user_agent}
            url = f"https://www.reddit.com/r/{subreddit}/top.json"
            params = {"t": "day", "limit": min(limit, 100)}
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds, headers=headers) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()

        return await with_retries(_do_request, self.settings.retries, self.settings.backoff_base_seconds)
