from __future__ import annotations
from storage.models import ExtractedPain, PainCluster
from storage.repository import insert_clusters
from clustering.embedding_cluster import cluster_pains

# In this MVP we cluster only on ExtractedPain records provided from the current run.
# The mapping cluster_id -> pains is returned for downstream scoring and idea gen.
_current_cluster_map: dict[str, list[ExtractedPain]] = {}

def cluster_pains_pipeline(pains: list[ExtractedPain], run_id: str | None = None) -> list[PainCluster]:
    global _current_cluster_map
    try:
        clusters, cmap = cluster_pains(pains)
    except Exception:
        # Fallback: single cluster to keep pipeline moving
        if not pains:
            clusters, cmap = [], {}
        else:
            import uuid
            label = max(pains, key=lambda x: x.emotional_intensity).pain_summary[:80]
            avg_int = sum(x.emotional_intensity for x in pains) / len(pains)
            cluster_id = str(uuid.uuid4())
            clusters = [PainCluster(
                cluster_id=cluster_id,
                run_id=run_id,
                cluster_label=label,
                pain_count=len(pains),
                avg_intensity=float(avg_int),
                avg_engagement=0.0,
                top_sources=[],
            )]
            cmap = {cluster_id: pains}
    if run_id:
        for cluster in clusters:
            cluster.run_id = run_id
    _current_cluster_map = cmap
    insert_clusters(clusters)
    return clusters

def get_current_cluster_map() -> dict[str, list[ExtractedPain]]:
    return _current_cluster_map

def cluster_pains(pains: list[ExtractedPain], run_id: str | None = None) -> list[PainCluster]:
    return cluster_pains_pipeline(pains, run_id=run_id)
