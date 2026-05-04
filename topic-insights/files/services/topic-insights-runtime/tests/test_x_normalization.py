from __future__ import annotations

from connectors.x_trends_playwright import normalize_trend_topic
from ingestion.normalization import normalize_topic_key


def test_hashtag_and_plain_text_normalize_to_same_key():
    assert normalize_trend_topic("#MarchMadness") == normalize_trend_topic("March Madness")
    assert normalize_topic_key("#Bitcoin") == normalize_topic_key("Bitcoin")

