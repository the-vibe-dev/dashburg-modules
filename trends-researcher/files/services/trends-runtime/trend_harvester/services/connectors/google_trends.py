from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from trend_harvester.config import Settings
from trend_harvester.services.http_utils import TTLCache, with_retries


class GoogleTrendsConnector:
    def __init__(self, settings: Settings, cache: TTLCache | None = None):
        self.settings = settings
        self.cache = cache or TTLCache(ttl_seconds=180)

    async def fetch(self, region: str, limit: int) -> list[dict]:
        cache_key = f"trends:{region}:{limit}"
        payload = self.cache.get(cache_key) if self.settings.enable_source_cache else None
        if payload is None:
            payload = await self._request(region)
            if self.settings.enable_source_cache:
                self.cache.set(cache_key, payload)
        parsed = self._parse_rss(payload, limit)
        if len(parsed) >= limit or limit <= 1:
            return parsed[:limit]

        # RSS commonly returns ~10 items. Expand coverage with fallback geos and merge unique titles.
        merged = list(parsed)
        seen = {str(item.get("title", "")).strip().lower() for item in merged if isinstance(item, dict)}
        fallback_geos = self._fallback_geos(region)
        for geo in fallback_geos:
            try:
                extra_xml = await self._request(geo)
                extra = self._parse_rss(extra_xml, limit)
            except Exception:
                extra = []
            for row in extra:
                key = str(row.get("title", "")).strip().lower()
                if not key or key in seen:
                    continue
                raw = row.get("raw_json") if isinstance(row.get("raw_json"), dict) else {}
                raw["geo"] = geo
                row["raw_json"] = raw
                merged.append(row)
                seen.add(key)
                if len(merged) >= limit:
                    return merged[:limit]

        return merged[:limit]

    @staticmethod
    def _fallback_geos(primary_region: str) -> list[str]:
        primary = (primary_region or "").strip().upper()
        ordered = ["US", "GB", "CA", "AU", "IN", "ZA", "NG"]
        return [geo for geo in ordered if geo != primary]

    async def _request(self, region: str) -> str:
        async def _do_request() -> str:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                # Prefer the daily trends RSS endpoint (returns broader lists).
                # Fallback to the older endpoint for compatibility.
                endpoints = [
                    ("https://trends.google.com/trends/trendingsearches/daily/rss", {"geo": region}),
                    ("https://trends.google.com/trending/rss", {"geo": region}),
                ]
                last_exc: Exception | None = None
                for url, params in endpoints:
                    try:
                        response = await client.get(url, params=params)
                        response.raise_for_status()
                        if response.text.strip():
                            return response.text
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        continue
                if last_exc is not None:
                    raise last_exc
                raise RuntimeError("Google Trends returned an empty response")

        return await with_retries(_do_request, self.settings.retries, self.settings.backoff_base_seconds)

    async def _request_daily_json(self, region: str, limit: int) -> list[dict]:
        async def _do_request() -> list[dict]:
            url = "https://trends.google.com/trends/api/dailytrends"
            params = {"hl": "en-US", "tz": "0", "geo": region, "ns": "15"}
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                text = response.text

            # Google prefixes with XSSI guard: )]}'
            cleaned = text.lstrip()
            if cleaned.startswith(")]}'"):
                nl = cleaned.find("\n")
                cleaned = cleaned[nl + 1 :] if nl >= 0 else cleaned[4:]
            data = json.loads(cleaned)
            days = ((data.get("default") or {}).get("trendingSearchesDays") or [])
            if not days:
                return []

            out: list[dict] = []
            rank = 1
            seen_titles: set[str] = set()
            for day in days:
                for trend in day.get("trendingSearches", []):
                    title = ((trend.get("title") or {}).get("query") or "").strip()
                    if not title:
                        continue
                    key = title.lower()
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)

                    article_url = ""
                    articles = trend.get("articles") or []
                    if articles and isinstance(articles, list):
                        article_url = str((articles[0] or {}).get("url") or "")

                    traffic_raw = str(trend.get("formattedTraffic") or "")
                    traffic_num = _parse_traffic(traffic_raw)
                    out.append(
                        {
                            "source": "trends",
                            "source_id": f"{title}:{rank}",
                            "title": title,
                            "url": article_url,
                            "published_at": datetime.now(timezone.utc),
                            "raw_json": {"rank": rank, "traffic": traffic_raw},
                            "metrics": {"rank": rank, "traffic": traffic_num},
                        }
                    )
                    rank += 1
                    if len(out) >= limit:
                        return out
            return out

        return await with_retries(_do_request, self.settings.retries, self.settings.backoff_base_seconds)

    def _parse_rss(self, xml_text: str, limit: int) -> list[dict]:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else []
        # Namespace-safe fallback: tags may come through as {ns}item.
        # If direct lookup returns very few rows, merge in fallback nodes.
        fallback_items = [node for node in root.iter() if node.tag.endswith("item")]
        if len(items) < max(3, min(limit, 10)):
            merged: list[ET.Element] = []
            seen_nodes: set[int] = set()
            for node in [*items, *fallback_items]:
                ptr = id(node)
                if ptr in seen_nodes:
                    continue
                seen_nodes.add(ptr)
                merged.append(node)
            items = merged
        elif not items:
            items = fallback_items

        out: list[dict] = []
        seen_titles: set[str] = set()
        rank = 1
        for item in items:
            title = _find_child_text(item, "title") or _find_child_text(item, "news_item_title") or ""
            link = _find_child_text(item, "link") or ""
            pub_date = _find_child_text(item, "pubDate")
            if not title.strip():
                continue
            key = title.strip().lower()
            if key in seen_titles:
                continue
            seen_titles.add(key)
            published_at = _parse_rfc_date(pub_date)
            out.append(
                {
                    "source": "trends",
                    "source_id": f"{title}:{rank}",
                    "title": title,
                    "url": link,
                    "published_at": published_at,
                    "raw_json": {"rank": rank},
                    "metrics": {"rank": rank},
                }
            )
            rank += 1
            if len(out) >= limit:
                break

        return out


def _parse_rfc_date(value: str | None):
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        return datetime.now(timezone.utc)


def _find_child_text(node: ET.Element, name: str) -> str | None:
    direct = node.findtext(name)
    if direct is not None:
        return direct
    for child in list(node):
        if child.tag.endswith(name):
            return child.text
    return None


def _parse_traffic(value: str) -> int:
    text = value.strip().upper().replace(",", "")
    if not text:
        return 0
    m = re.match(r"([0-9]+(?:\.[0-9]+)?)\s*([KMB])?\+?$", text)
    if not m:
        return 0
    base = float(m.group(1))
    suffix = m.group(2)
    mult = 1
    if suffix == "K":
        mult = 1_000
    elif suffix == "M":
        mult = 1_000_000
    elif suffix == "B":
        mult = 1_000_000_000
    return int(base * mult)
