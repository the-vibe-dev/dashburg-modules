from __future__ import annotations

from connectors.x_trends_playwright import parse_post_count_value, parse_trend_text_block


def test_parse_trend_text_block_extracts_category_title_and_posts():
    block = "Trending in United States\n#MarchMadness\n24.5K posts"
    parsed = parse_trend_text_block(block)
    assert parsed["category"] == "Trending in United States"
    assert parsed["title"] == "#MarchMadness"
    assert parsed["post_count_text"] == "24.5K posts"


def test_parse_post_count_value_supports_suffixes():
    assert parse_post_count_value("1.2K posts") == 1200.0
    assert parse_post_count_value("2M posts") == 2_000_000.0
    assert parse_post_count_value("3 posts") == 3.0
    assert parse_post_count_value("unknown") is None

