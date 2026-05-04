import pytest

from trend_harvester.config import Settings
from trend_harvester.services.connectors.google_trends import GoogleTrendsConnector
from trend_harvester.services.connectors.reddit import RedditConnector
from trend_harvester.services.connectors.youtube import YouTubeConnector


@pytest.mark.asyncio
async def test_youtube_connector_parses_items(monkeypatch):
    settings = Settings(youtube_api_key="test")
    connector = YouTubeConnector(settings)

    async def fake_request(params):
        return {
            "items": [
                {
                    "id": "abc",
                    "snippet": {
                        "title": "Hello",
                        "publishedAt": "2026-03-01T00:00:00Z",
                        "channelTitle": "Channel",
                    },
                    "statistics": {"viewCount": "10", "likeCount": "1", "commentCount": "2"},
                }
            ]
        }

    monkeypatch.setattr(connector, "_request", fake_request)
    result = await connector.fetch("US", ["News & Politics"], 1)
    assert len(result) == 1
    assert result[0]["source"] == "youtube"


@pytest.mark.asyncio
async def test_reddit_connector_parses_items(monkeypatch):
    settings = Settings()
    connector = RedditConnector(settings)

    async def fake_request(subreddit, limit):
        return {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "p1",
                            "title": "Post",
                            "permalink": "/r/test/comments/p1/post",
                            "created_utc": 1700000000,
                            "score": 5,
                            "num_comments": 2,
                            "upvote_ratio": 0.9,
                            "subreddit": subreddit,
                        }
                    }
                ]
            }
        }

    monkeypatch.setattr(connector, "_request", fake_request)
    result = await connector.fetch(["test"], 5)
    assert len(result) == 1
    assert result[0]["source"] == "reddit"


@pytest.mark.asyncio
async def test_trends_connector_parses_rss(monkeypatch):
    settings = Settings()
    connector = GoogleTrendsConnector(settings)

    async def fake_request(region):
        return """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
        <rss><channel>
            <item><title>Trend 1</title><link>https://example.com/1</link><pubDate>Tue, 04 Mar 2026 10:00:00 +0000</pubDate></item>
            <item><title>Trend 2</title><link>https://example.com/2</link><pubDate>Tue, 04 Mar 2026 11:00:00 +0000</pubDate></item>
        </channel></rss>"""

    monkeypatch.setattr(connector, "_request", fake_request)
    result = await connector.fetch("US", 2)
    assert len(result) == 2
    assert result[0]["metrics"]["rank"] == 1
