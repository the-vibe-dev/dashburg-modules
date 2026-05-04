from trend_harvester.services.dedupe import cluster_candidates, normalize_title


def test_normalize_title():
    assert normalize_title("Hello,   World!!!") == "hello world"


def test_cluster_candidates_similarity_and_url():
    items = [
        {"title": "AI Revolution in Healthcare", "url": "https://a"},
        {"title": "AI revolution in health care", "url": "https://b"},
        {"title": "Completely different", "url": "https://c"},
        {"title": "Another", "url": "https://a"},
    ]
    clusters = cluster_candidates(items, threshold=80)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [1, 3]
