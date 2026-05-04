from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from trend_harvester.config import Settings
from trend_harvester.models import ChannelMetadata
from trend_harvester.services.channels import ChannelRecord, get_channel_records
from trend_harvester.services.http_utils import with_retries

logger = logging.getLogger(__name__)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class ChannelMetadataService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_cached_metadata_map(self, db: Session, *, records: list[ChannelRecord] | None = None) -> dict[str, dict]:
        records = records or get_channel_records()
        rows = {
            row.channel_slug: row
            for row in db.scalars(select(ChannelMetadata).where(ChannelMetadata.channel_slug.in_([r.slug for r in records]))).all()
        }
        now = datetime.now(timezone.utc)
        ttl = timedelta(days=max(1, int(self.settings.channel_metadata_ttl_days)))
        return {
            record.slug: self._serialize(rows[record.slug], record)
            if record.slug in rows
            else self._fallback_payload(record, fetched_at=now, expires_at=now + ttl)
            for record in records
        }

    async def refresh_all(self, db: Session, *, force: bool = False) -> list[dict]:
        records = get_channel_records()
        metadata = await self.get_metadata_map(db, records=records, force_refresh=force)
        return [metadata[record.slug] for record in records if record.slug in metadata]

    async def get_metadata_map(
        self,
        db: Session,
        *,
        records: list[ChannelRecord] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, dict]:
        records = records or get_channel_records()
        now = datetime.now(timezone.utc)
        ttl = timedelta(days=max(1, int(self.settings.channel_metadata_ttl_days)))
        cached = {
            row.channel_slug: row
            for row in db.scalars(select(ChannelMetadata).where(ChannelMetadata.channel_slug.in_([r.slug for r in records]))).all()
        }

        to_fetch: list[ChannelRecord] = []
        results: dict[str, dict] = {}
        for record in records:
            row = cached.get(record.slug)
            if (
                force_refresh
                or row is None
                or row.expires_at is None
                or (_as_utc(row.expires_at) or now) <= now
            ):
                to_fetch.append(record)
            else:
                results[record.slug] = self._serialize(row, record)

        if to_fetch:
            fetched_rows = await self._refresh_records(db, to_fetch=to_fetch, ttl=ttl, now=now)
            results.update({record.slug: fetched_rows[record.slug] for record in to_fetch if record.slug in fetched_rows})

        for record in records:
            results.setdefault(record.slug, self._fallback_payload(record, fetched_at=now, expires_at=now + ttl))
        return results

    async def _refresh_records(
        self,
        db: Session,
        *,
        to_fetch: list[ChannelRecord],
        ttl: timedelta,
        now: datetime,
    ) -> dict[str, dict]:
        fetched_by_channel_id: dict[str, dict] = {}
        channel_ids = [record.youtube_channel_id for record in to_fetch if record.youtube_channel_id]
        if self.settings.youtube_api_key and channel_ids:
            fetched_by_channel_id = await self._fetch_from_youtube(channel_ids)

        out: dict[str, dict] = {}
        for record in to_fetch:
            payload = fetched_by_channel_id.get(record.youtube_channel_id or "")
            if payload:
                source = "youtube"
                title = str(payload.get("title", "")).strip() or record.channel_title or record.display_name
                description = str(payload.get("description", "")).strip() or record.channel_description or record.profile
                raw_json = payload
            else:
                source = "fallback"
                title = record.channel_title or record.display_name
                description = record.channel_description or record.profile
                raw_json = {}
                if record.youtube_channel_id and self.settings.youtube_api_key:
                    logger.warning(
                        "channel_metadata_refresh_failed channel=%s channel_id=%s fallback=true",
                        record.slug,
                        record.youtube_channel_id,
                    )

            row = db.get(ChannelMetadata, record.slug)
            if row is None:
                row = ChannelMetadata(channel_slug=record.slug, expires_at=now + ttl)
                db.add(row)
            row.youtube_channel_id = record.youtube_channel_id or None
            row.youtube_channel_title = title
            row.youtube_channel_description = description
            row.metadata_source = source
            row.raw_json = raw_json
            row.fetched_at = now
            row.expires_at = now + ttl
            out[record.slug] = self._serialize(row, record)

        db.commit()
        return out

    async def _fetch_from_youtube(self, channel_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        unique_ids = list(dict.fromkeys(channel_ids))
        for idx in range(0, len(unique_ids), 50):
            batch = unique_ids[idx : idx + 50]
            params = {
                "part": "snippet",
                "id": ",".join(batch),
                "maxResults": len(batch),
                "key": self.settings.youtube_api_key,
            }

            async def _do_request() -> dict:
                async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                    response = await client.get("https://www.googleapis.com/youtube/v3/channels", params=params)
                    response.raise_for_status()
                    return response.json()

            payload = await with_retries(_do_request, self.settings.retries, self.settings.backoff_base_seconds)
            for item in payload.get("items", []):
                channel_id = str(item.get("id", "")).strip()
                snippet = item.get("snippet", {}) if isinstance(item.get("snippet"), dict) else {}
                if not channel_id:
                    continue
                out[channel_id] = {
                    "channel_id": channel_id,
                    "title": str(snippet.get("title", "")).strip(),
                    "description": str(snippet.get("description", "")).strip(),
                }
        return out

    @staticmethod
    def _serialize(row: ChannelMetadata, record: ChannelRecord) -> dict:
        return {
            "channel_slug": record.slug,
            "display_name": record.display_name,
            "youtube_channel_id": row.youtube_channel_id or record.youtube_channel_id,
            "channel_title": row.youtube_channel_title or record.channel_title or record.display_name,
            "channel_description": row.youtube_channel_description or record.channel_description or record.profile,
            "metadata_source": row.metadata_source,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "focus_tags": list(record.focus_tags),
            "category": record.category or (record.youtube_categories[0] if record.youtube_categories else ""),
            "youtube_categories": list(record.youtube_categories),
            "query_terms": list(record.query_terms),
            "profile": record.profile,
        }

    @staticmethod
    def _fallback_payload(record: ChannelRecord, *, fetched_at: datetime, expires_at: datetime) -> dict:
        return {
            "channel_slug": record.slug,
            "display_name": record.display_name,
            "youtube_channel_id": record.youtube_channel_id,
            "channel_title": record.channel_title or record.display_name,
            "channel_description": record.channel_description or record.profile,
            "metadata_source": "fallback",
            "fetched_at": fetched_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "focus_tags": list(record.focus_tags),
            "category": record.category or (record.youtube_categories[0] if record.youtube_categories else ""),
            "youtube_categories": list(record.youtube_categories),
            "query_terms": list(record.query_terms),
            "profile": record.profile,
        }
