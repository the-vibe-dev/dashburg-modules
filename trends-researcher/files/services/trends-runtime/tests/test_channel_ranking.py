from trend_harvester.config import Settings
from trend_harvester.services.channel_ranking import build_channel_rankings


def _channel(
    display_name: str,
    *,
    description: str,
    categories: list[str] | None = None,
    aliases: list[str] | None = None,
    query_terms: list[str] | None = None,
) -> dict:
    return {
        "channel_slug": display_name.lower().replace(" ", "-"),
        "display_name": display_name,
        "channel_title": display_name,
        "channel_description": description,
        "metadata_source": "fallback",
        "aliases": aliases or [],
        "focus_tags": [],
        "category": "",
        "youtube_categories": categories or [],
        "query_terms": query_terms or [],
        "profile": description,
    }


def test_channel_rankings_filter_irrelevant_channels_and_limit_to_top_four():
    settings = Settings()
    channels = [
        _channel("Daily Bible Passages", description="Bible verses scripture prayer christian devotional", categories=["People & Blogs"]),
        _channel("Heartfelt Critter Chronicles", description="cat rescue pet stories animal moments", categories=["Pets & Animals"]),
        _channel("Crime Stories Today", description="crime police cases court news", categories=["News & Politics"]),
        _channel("Stateside Now", description="US politics elections policy news", categories=["News & Politics"]),
        _channel("Anime Bios", description="anime lore character backstory fandom", categories=["Entertainment"]),
        _channel("Bite Sized Knowledge", description="educational facts science explainers", categories=["Education"]),
    ]

    rankings, filtered_channels, _, _ = build_channel_rankings(
        topic_id="t1",
        title="Cat rescue story goes viral after neighborhood saves injured kitten",
        summary="A pet rescue update focused on cats, animals, and local adoption support.",
        channels=channels,
        model_scores={channel["display_name"]: 0.4 for channel in channels},
        focus_fit_scores={channel["display_name"]: 0.0 for channel in channels},
        legacy_relevance={channel["display_name"]: 0.3 for channel in channels},
        channel_scores={channel["display_name"]: 60.0 for channel in channels},
        include_debug=False,
        settings=settings,
    )

    assert len(rankings) <= 4
    assert "Daily Bible Passages" not in filtered_channels
    assert all(item["relevance_pct"] > 0 for item in rankings)


def test_cat_story_does_not_rank_for_bible_channel_without_faith_overlap():
    settings = Settings()
    rankings, _, _, debug_map = build_channel_rankings(
        topic_id="t2",
        title="Cat story shocks celebrity gossip fans",
        summary="A celebrity pet story with gossip coverage and cat footage.",
        channels=[
            _channel("Daily Bible Passages", description="Bible verses scripture prayer christian devotional", categories=["People & Blogs"]),
            _channel("Heartfelt Critter Chronicles", description="cat rescue pet stories animal moments", categories=["Pets & Animals"]),
        ],
        model_scores={"Daily Bible Passages": 0.9, "Heartfelt Critter Chronicles": 0.4},
        focus_fit_scores={"Daily Bible Passages": 0.8, "Heartfelt Critter Chronicles": 0.3},
        legacy_relevance={"Daily Bible Passages": 0.7, "Heartfelt Critter Chronicles": 0.4},
        channel_scores={"Daily Bible Passages": 85.0, "Heartfelt Critter Chronicles": 50.0},
        include_debug=True,
        settings=settings,
    )

    assert [item["channel"] for item in rankings] == ["Heartfelt Critter Chronicles"]
    assert debug_map["Daily Bible Passages"]["gated"] is True
    assert debug_map["Daily Bible Passages"]["reason"] in {"no keyword overlap", "faith disqualifier"}


def test_channel_rankings_sort_ties_stably_by_score_then_name():
    settings = Settings()
    rankings, _, _, _ = build_channel_rankings(
        topic_id="t3",
        title="Space science breakthrough explained",
        summary="A science explainer about space research and physics.",
        channels=[
            _channel("Alpha Science", description="space science physics explainers", categories=["Science & Technology"]),
            _channel("Beta Science", description="space science physics explainers", categories=["Science & Technology"]),
        ],
        model_scores={"Alpha Science": 0.5, "Beta Science": 0.5},
        focus_fit_scores={"Alpha Science": 0.0, "Beta Science": 0.0},
        legacy_relevance={"Alpha Science": 0.5, "Beta Science": 0.5},
        channel_scores={"Alpha Science": 70.0, "Beta Science": 70.0},
        include_debug=False,
        settings=settings,
    )

    assert [item["channel"] for item in rankings] == ["Alpha Science", "Beta Science"]


def test_geo_anchor_terms_boost_obvious_channel_domain_matches():
    settings = Settings()
    rankings, _, _, debug_map = build_channel_rankings(
        topic_id="t4",
        title="Average Day in Africa",
        summary="",
        channels=[
            _channel(
                "Afrika Dispatch",
                description="Africa-focused geopolitics, development, business, diplomacy, elections, security, and regional explainers.",
                categories=["News & Politics", "Education"],
                aliases=["Africa", "africa", "Afrika Dispatch"],
                query_terms=["africa geopolitics", "africa development", "africa business", "africa security"],
            )
        ],
        model_scores={"Afrika Dispatch": 0.0},
        focus_fit_scores={"Afrika Dispatch": 0.0},
        legacy_relevance={"Afrika Dispatch": 0.0},
        channel_scores={"Afrika Dispatch": 28.0},
        include_debug=True,
        settings=settings,
    )

    assert rankings[0]["relevance_pct"] >= 45
    assert debug_map["Afrika Dispatch"]["anchor_overlap"] == ["africa"]
