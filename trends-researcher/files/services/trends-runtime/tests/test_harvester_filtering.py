from trend_harvester.services.harvester import HarvesterService


def test_filter_candidates_keeps_minimum_trends_in_focus_mode():
    items = []
    for idx in range(20):
        items.append(
            {
                "source": "trends",
                "title": f"Generic trend headline {idx}",
                "raw_json": {},
            }
        )
    # Include a clearly relevant one to ensure normal threshold behavior still applies.
    items.append(
        {
            "source": "trends",
            "title": "Premier League transfer rumors this week",
            "raw_json": {},
        }
    )

    kept, _filtered_total, _filtered_by_source, kept_by_source = HarvesterService._filter_candidates(
        items,
        "english premier league",
        min_keep_by_source={"trends": 10},
    )

    assert len(kept) >= 10
    assert kept_by_source.get("trends", 0) >= 10


def test_filter_candidates_without_focus_keeps_non_low_signal():
    items = [
        {"source": "trends", "title": "Premier League transfer update this morning", "raw_json": {}},
        {"source": "trends", "title": "#oc", "raw_json": {}},  # low-signal, should be filtered
        {"source": "reddit", "title": "Reddit discussion on Arsenal tactics", "raw_json": {}},
    ]
    kept, _filtered_total, _filtered_by_source, kept_by_source = HarvesterService._filter_candidates(items, "")
    assert len(kept) == 2
    assert kept_by_source.get("trends", 0) == 1
    assert kept_by_source.get("reddit", 0) == 1
