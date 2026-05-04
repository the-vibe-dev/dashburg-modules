from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from trend_harvester.config import Settings
from trend_harvester.db import Base
from trend_harvester.models import ChannelMetadata
from trend_harvester.services.channel_metadata import ChannelMetadataService
from trend_harvester.services.channels import ChannelRecord


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_channel_metadata_refresh_uses_cache_until_expired(monkeypatch):
    settings = Settings(youtube_api_key="test", channel_metadata_ttl_days=7)
    service = ChannelMetadataService(settings)
    record = ChannelRecord(
        slug="stateside-now",
        display_name="Stateside Now",
        profile="US politics and policy explainers.",
        youtube_channel_id="yt-123",
    )
    db = _session()
    now = datetime.now(timezone.utc)
    db.add(
        ChannelMetadata(
            channel_slug=record.slug,
            youtube_channel_id="yt-123",
            youtube_channel_title="Cached Title",
            youtube_channel_description="Cached Description",
            metadata_source="youtube",
            raw_json={},
            fetched_at=now,
            expires_at=now + timedelta(days=3),
        )
    )
    db.commit()

    calls = {"count": 0}

    async def fake_fetch(channel_ids):
        calls["count"] += 1
        return {channel_ids[0]: {"channel_id": channel_ids[0], "title": "Fresh Title", "description": "Fresh Description"}}

    monkeypatch.setattr(service, "_fetch_from_youtube", fake_fetch)
    cached = service.get_cached_metadata_map(db, records=[record])
    assert cached[record.slug]["channel_title"] == "Cached Title"

    refreshed = __import__("asyncio").run(service.get_metadata_map(db, records=[record], force_refresh=False))
    assert refreshed[record.slug]["channel_title"] == "Cached Title"
    assert calls["count"] == 0


def test_channel_metadata_refresh_fetches_and_persists_when_expired(monkeypatch):
    settings = Settings(youtube_api_key="test", channel_metadata_ttl_days=7)
    service = ChannelMetadataService(settings)
    record = ChannelRecord(
        slug="stateside-now",
        display_name="Stateside Now",
        profile="US politics and policy explainers.",
        youtube_channel_id="yt-123",
    )
    db = _session()
    stale = datetime.now(timezone.utc) - timedelta(days=8)
    db.add(
        ChannelMetadata(
            channel_slug=record.slug,
            youtube_channel_id="yt-123",
            youtube_channel_title="Old Title",
            youtube_channel_description="Old Description",
            metadata_source="youtube",
            raw_json={},
            fetched_at=stale,
            expires_at=stale,
        )
    )
    db.commit()

    calls = {"count": 0}

    async def fake_fetch(channel_ids):
        calls["count"] += 1
        return {channel_ids[0]: {"channel_id": channel_ids[0], "title": "Fresh Title", "description": "Fresh Description"}}

    monkeypatch.setattr(service, "_fetch_from_youtube", fake_fetch)
    refreshed = __import__("asyncio").run(service.get_metadata_map(db, records=[record], force_refresh=False))

    assert refreshed[record.slug]["channel_title"] == "Fresh Title"
    assert refreshed[record.slug]["channel_description"] == "Fresh Description"
    assert calls["count"] == 1
