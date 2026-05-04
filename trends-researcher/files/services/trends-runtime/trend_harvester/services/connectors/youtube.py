from __future__ import annotations

from datetime import datetime

import httpx

from trend_harvester.config import Settings
from trend_harvester.schemas import YOUTUBE_CATEGORY_MAP
from trend_harvester.services.http_utils import TTLCache, with_retries


class YouTubeConnector:
    def __init__(self, settings: Settings, cache: TTLCache | None = None):
        self.settings = settings
        self.cache = cache or TTLCache(ttl_seconds=300)

    async def fetch(self, region: str, categories: list[str], limit: int, search_queries: list[str] | None = None) -> list[dict]:
        if not self.settings.youtube_api_key:
            return []

        out: list[dict] = []
        per_category = max(limit // max(len(categories), 1), 1)
        for category in categories:
            if len(out) >= limit:
                break
            cat_id = YOUTUBE_CATEGORY_MAP.get(category, category)
            page_token = None
            while len(out) < limit:
                params = {
                    "part": "snippet,statistics",
                    "chart": "mostPopular",
                    "regionCode": region,
                    "videoCategoryId": cat_id,
                    "maxResults": min(50, per_category),
                    "key": self.settings.youtube_api_key,
                }
                if page_token:
                    params["pageToken"] = page_token

                cache_key = f"yt:{region}:{cat_id}:{page_token}:{params['maxResults']}"
                payload = self.cache.get(cache_key) if self.settings.enable_source_cache else None
                if payload is None:
                    payload = await self._request(params)
                    if self.settings.enable_source_cache:
                        self.cache.set(cache_key, payload)

                items = payload.get("items", [])
                for item in items:
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    video_id = item.get("id")
                    if not video_id:
                        continue
                    out.append(
                        {
                            "source": "youtube",
                            "source_id": video_id,
                            "title": snippet.get("title", ""),
                            "url": f"https://www.youtube.com/watch?v={video_id}",
                            "published_at": _parse_datetime(snippet.get("publishedAt")),
                            "raw_json": {
                                "channel_title": snippet.get("channelTitle"),
                                "statistics": {
                                    "view_count": stats.get("viewCount"),
                                    "like_count": stats.get("likeCount"),
                                    "comment_count": stats.get("commentCount"),
                                },
                            },
                            "metrics": {
                                "view_count": stats.get("viewCount"),
                                "like_count": stats.get("likeCount"),
                                "comment_count": stats.get("commentCount"),
                            },
                        }
                    )
                    if len(out) >= limit:
                        break

                page_token = payload.get("nextPageToken")
                if not page_token or not items:
                    break
        if search_queries:
            remaining = max(limit - len(out), 0)
            if remaining > 0:
                out.extend(await self._search(region=region, queries=search_queries, limit=remaining))
        return out[:limit]

    async def _search(self, region: str, queries: list[str], limit: int) -> list[dict]:
        out: list[dict] = []
        for query in dict.fromkeys(q.strip() for q in queries if q and q.strip()):
            if len(out) >= limit:
                break
            params = {
                "part": "snippet",
                "q": query,
                "regionCode": region,
                "maxResults": min(10, max(limit - len(out), 1)),
                "order": "date",
                "type": "video",
                "videoDuration": "short",
                "key": self.settings.youtube_api_key,
            }
            cache_key = f"yt-search:{region}:{query}:{params['maxResults']}"
            payload = self.cache.get(cache_key) if self.settings.enable_source_cache else None
            if payload is None:
                payload = await self._search_request(params)
                if self.settings.enable_source_cache:
                    self.cache.set(cache_key, payload)
            search_items = payload.get("items", [])
            video_ids = [((item.get("id") or {}).get("videoId")) for item in search_items]
            video_ids = [video_id for video_id in video_ids if video_id]
            stats_map = await self._fetch_video_details(video_ids)
            for item in search_items:
                snippet = item.get("snippet", {})
                video_id = ((item.get("id") or {}).get("videoId")) or ""
                if not video_id:
                    continue
                stats = stats_map.get(video_id, {})
                out.append(
                    {
                        "source": "youtube",
                        "source_id": video_id,
                        "title": snippet.get("title", ""),
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "published_at": _parse_datetime(snippet.get("publishedAt")),
                        "raw_json": {
                            "channel_title": snippet.get("channelTitle"),
                            "search_query": query,
                            "statistics": {
                                "view_count": stats.get("viewCount"),
                                "like_count": stats.get("likeCount"),
                                "comment_count": stats.get("commentCount"),
                            },
                        },
                        "metrics": {
                            "view_count": stats.get("viewCount"),
                            "like_count": stats.get("likeCount"),
                            "comment_count": stats.get("commentCount"),
                        },
                    }
                )
                if len(out) >= limit:
                    break
        return out[:limit]

    async def _search_request(self, params: dict) -> dict:
        async def _do_request() -> dict:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.get("https://www.googleapis.com/youtube/v3/search", params=params)
                response.raise_for_status()
                return response.json()

        return await with_retries(_do_request, self.settings.retries, self.settings.backoff_base_seconds)

    async def _fetch_video_details(self, video_ids: list[str]) -> dict[str, dict]:
        if not video_ids:
            return {}
        params = {
            "part": "statistics",
            "id": ",".join(video_ids[:50]),
            "maxResults": min(len(video_ids), 50),
            "key": self.settings.youtube_api_key,
        }
        cache_key = f"yt-details:{params['id']}"
        payload = self.cache.get(cache_key) if self.settings.enable_source_cache else None
        if payload is None:
            payload = await self._request(params)
            if self.settings.enable_source_cache:
                self.cache.set(cache_key, payload)
        out: dict[str, dict] = {}
        for item in payload.get("items", []):
            video_id = item.get("id")
            if not video_id:
                continue
            out[str(video_id)] = item.get("statistics", {}) if isinstance(item.get("statistics"), dict) else {}
        return out

    async def _request(self, params: dict) -> dict:
        async def _do_request() -> dict:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.get("https://www.googleapis.com/youtube/v3/videos", params=params)
                response.raise_for_status()
                return response.json()

        return await with_retries(_do_request, self.settings.retries, self.settings.backoff_base_seconds)


def _parse_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
