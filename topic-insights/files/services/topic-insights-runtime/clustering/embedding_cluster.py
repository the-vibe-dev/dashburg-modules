from __future__ import annotations
import uuid
import numpy as np
import logging
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from extraction.llm import embed_texts
from storage.models import ExtractedPain, PainCluster

def _auto_k(n: int) -> int:
    if n < 8:
        return max(2, n // 2) if n > 2 else 1
    if n < 30:
        return 4
    if n < 80:
        return 6
    return 8

def cluster_pains(pains: list[ExtractedPain]) -> tuple[list[PainCluster], dict[str, list[ExtractedPain]]]:
    log = logging.getLogger(__name__)
    if not pains:
        return [], {}
    texts = [p.pain_summary for p in pains]
    vectors: np.ndarray
    try:
        # Try embeddings; fallback to TF-IDF if embed model unavailable
        try:
            emb = embed_texts(texts)
            if not emb or not emb[0]:
                raise RuntimeError("empty embeddings")
            vectors = np.array(emb, dtype=float)
        except Exception:
            tfidf = TfidfVectorizer(max_features=2048, ngram_range=(1,2))
            vectors = tfidf.fit_transform(texts).toarray()

        if len(pains) <= 2:
            k = 1
        else:
            k = min(_auto_k(len(pains)), len(pains))
            k = max(2, k) if len(pains) >= 4 else max(1, k)

        if k == 1:
            labels = np.zeros(len(pains), dtype=int)
        else:
            km = KMeans(n_clusters=k, n_init="auto", random_state=42)
            labels = km.fit_predict(vectors)

        groups: dict[int, list[ExtractedPain]] = {}
        for p, lab in zip(pains, labels):
            groups.setdefault(int(lab), []).append(p)

        clusters: list[PainCluster] = []
        by_cluster_id: dict[str, list[ExtractedPain]] = {}

        for lab, items in groups.items():
            cluster_id = str(uuid.uuid4())
            label = max(items, key=lambda x: x.emotional_intensity).pain_summary[:80]
            avg_int = sum(x.emotional_intensity for x in items) / len(items)
            clusters.append(PainCluster(
                cluster_id=cluster_id,
                cluster_label=label,
                pain_count=len(items),
                avg_intensity=float(avg_int),
                avg_engagement=0.0,  # set in scoring using RawPost join if desired; we approximate in scoring pipeline
                top_sources=[],
            ))
            by_cluster_id[cluster_id] = items

        return clusters, by_cluster_id
    except RecursionError as e:
        log.exception("cluster_pains_recursion_error fallback_single_cluster error=%s", e)
    except Exception as e:
        log.exception("cluster_pains_failed fallback_single_cluster error=%s", e)

    # Fallback: single cluster with all pains to keep pipeline moving
    cluster_id = str(uuid.uuid4())
    label = max(pains, key=lambda x: x.emotional_intensity).pain_summary[:80]
    avg_int = sum(x.emotional_intensity for x in pains) / len(pains)
    cluster = PainCluster(
        cluster_id=cluster_id,
        cluster_label=label,
        pain_count=len(pains),
        avg_intensity=float(avg_int),
        avg_engagement=0.0,
        top_sources=[],
    )
    return [cluster], {cluster_id: pains}
