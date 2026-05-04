from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote_plus, unquote_plus, urlparse

import httpx

from trend_harvester.config import Settings
from trend_harvester.services.http_utils import TTLCache, with_retries

_STOP_TERMS = {
    "about",
    "privacy",
    "help",
    "terms",
    "jobs",
    "developers",
    "settings",
    "download",
    "login",
    "sign up",
    "home",
    "explore",
}


class XTrendsConnector:
    def __init__(self, settings: Settings, cache: TTLCache | None = None):
        self.settings = settings
        self.cache = cache or TTLCache(ttl_seconds=120)
        raw = (self.settings.x_trends_base_urls or "").strip()
        configured = [x.strip().rstrip("/") for x in raw.split(",") if x.strip()]
        self.base_urls = configured or [
            "https://nitter.net",
            "https://nitter.poast.org",
            "https://nitter.privacydev.net",
        ]

    async def fetch(self, region: str, limit: int, *, seed_queries: list[str] | None = None) -> list[dict]:
        cache_key = f"x:{region}:{limit}"
        payload = self.cache.get(cache_key) if self.settings.enable_source_cache else None
        if payload is None:
            try:
                payload = await self._request(region)
            except Exception:
                payload = ""
            if self.settings.enable_source_cache:
                self.cache.set(cache_key, payload)

        parsed = self._parse_nitter_explore(payload, limit)
        if parsed:
            return parsed[:limit]

        trends24_html = ""
        try:
            trends24_html = await self._request_trends24(region)
        except Exception:
            trends24_html = ""
        parsed_trends24 = self._parse_trends24(trends24_html, limit)
        if parsed_trends24:
            return parsed_trends24[:limit]

        seeds = [q.strip() for q in (seed_queries or []) if isinstance(q, str) and q.strip()]
        return self._seed_fallback(seeds, limit)

    async def _request(self, region: str) -> str:
        # region currently reserved for future locale-aware endpoint selection
        _ = region

        async def _do_request() -> str:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                last_exc: Exception | None = None
                for base in self.base_urls:
                    url = f"{base}/explore"
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        body = response.text.strip()
                        if body:
                            return body
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                if last_exc is not None:
                    raise last_exc
                return ""

        return await with_retries(_do_request, self.settings.retries, self.settings.backoff_base_seconds)

    async def _request_trends24(self, region: str) -> str:
        region_slug = _region_to_trends24_slug(region)
        urls = [f"https://trends24.in/{region_slug}/", "https://trends24.in/"]

        async def _do_request() -> str:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds, follow_redirects=True) as client:
                last_exc: Exception | None = None
                for url in urls:
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        body = response.text.strip()
                        if body:
                            return body
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                if last_exc is not None:
                    raise last_exc
                return ""

        return await with_retries(_do_request, self.settings.retries, self.settings.backoff_base_seconds)

    @staticmethod
    def _parse_nitter_explore(html: str, limit: int) -> list[dict]:
        if not html.strip():
            return []
        out: list[dict] = []
        seen: set[str] = set()
        rank = 1

        # Nitter explore contains trend links like /search?q=<term>
        for match in re.finditer(r'href="/search\?q=([^"#]+)"[^>]*>([^<]+)</a>', html, flags=re.IGNORECASE):
            query_enc = (match.group(1) or "").strip()
            label = (match.group(2) or "").strip()
            query = unquote_plus(query_enc).strip()
            text = label or query
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                continue
            if len(text) > 120:
                continue
            if text.lower() in _STOP_TERMS:
                continue
            if not any(ch.isalnum() for ch in text):
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "source": "x",
                    "source_id": f"{text}:{rank}",
                    "title": text,
                    "url": f"https://x.com/search?q={quote_plus(query or text)}&src=trend_click&f=live",
                    "published_at": datetime.now(timezone.utc),
                    "raw_json": {"rank": rank, "query": query or text},
                    "metrics": {"rank": rank},
                }
            )
            rank += 1
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _seed_fallback(seed_queries: list[str], limit: int) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        rank = 1
        for item in seed_queries:
            text = re.sub(r"\s+", " ", item).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "source": "x",
                    "source_id": f"{text}:{rank}",
                    "title": text,
                    "url": f"https://x.com/search?q={quote_plus(text)}&src=typed_query&f=live",
                    "published_at": datetime.now(timezone.utc),
                    "raw_json": {"rank": rank, "seed": True},
                    "metrics": {"rank": rank},
                }
            )
            rank += 1
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _parse_trends24(html: str, limit: int) -> list[dict]:
        if not html.strip():
            return []
        out: list[dict] = []
        seen: set[str] = set()
        rank = 1
        for tag, label in re.findall(
            r'(<a[^>]*class\s*=\s*(?:\"[^\"]*trend-link[^\"]*\"|\'[^\']*trend-link[^\']*\'|[^\s>]*trend-link[^\s>]*)[^>]*>)([^<]+)</a>',
            html,
            flags=re.IGNORECASE,
        ):
            href_match = re.search(r'href=\"([^\"]+)\"', tag, flags=re.IGNORECASE)
            href = href_match.group(1) if href_match else ""
            text = re.sub(r"\s+", " ", (label or "").strip())
            if not text:
                continue
            if len(text) > 120:
                continue
            if text.lower() in _STOP_TERMS:
                continue
            if not any(ch.isalnum() for ch in text):
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            query = _query_from_x_href(href) or text
            out.append(
                {
                    "source": "x",
                    "source_id": f"{text}:{rank}",
                    "title": text,
                    "url": f"https://x.com/search?q={quote_plus(query)}&src=trend_click&f=live",
                    "published_at": datetime.now(timezone.utc),
                    "raw_json": {"rank": rank, "query": query, "provider": "trends24"},
                    "metrics": {"rank": rank},
                }
            )
            rank += 1
            if len(out) >= limit:
                break
        return out


def _region_to_trends24_slug(region: str) -> str:
    code = (region or "").strip().upper()
    mapping = {
        "US": "united-states",
        "GB": "united-kingdom",
        "CA": "canada",
        "AU": "australia",
        "IN": "india",
        "ZA": "south-africa",
        "NG": "nigeria",
    }
    return mapping.get(code, "united-states")


def _query_from_x_href(href: str) -> str:
    if not href:
        return ""
    try:
        parsed = urlparse(href)
        q = parse_qs(parsed.query).get("q", [])
        if q:
            return unquote_plus(str(q[0])).strip()
    except Exception:
        return ""
    return ""
