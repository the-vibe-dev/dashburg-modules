from __future__ import annotations
from dataclasses import dataclass
import logging
import time
import uuid
from typing import Sequence
from typing import Any

from ingestion.pipeline import ingest_all, IngestSummary
from ingestion.web.router import set_web_run_id
from extraction.pipeline import extract_pains
from extraction.llm import validate_llm_config, LLMError, set_llm_run_id
from clustering.pipeline import cluster_pains
from scoring.pipeline import score_clusters
from idea_generation.pipeline import generate_ideas_for_clusters
from reports.pipeline import export_reports
from storage.models import RunEvent
from storage.repository import insert_run_event, list_clusters_all
from core.config import settings

@dataclass
class RunParams:
    query: str
    topic: str
    limit: int = 50
    enable_youtube: bool = False
    ingest_overrides: dict[str, int] | None = None
    sources: dict[str, bool] | None = None
    sources_config: dict[str, dict[str, Any]] | None = None
    category_mode: str = "broad"
    category_filters: list[str] | None = None
    exclude_categories: list[str] | None = None

def run_end_to_end(params: RunParams) -> dict:
    log = logging.getLogger(__name__)
    run_id = str(uuid.uuid4())

    def record(stage: str, status: str, input_count: int = 0, output_count: int = 0, error: str | None = None) -> None:
        insert_run_event(
            RunEvent(
                event_id=str(uuid.uuid4()),
                run_id=run_id,
                stage_name=stage,
                status=status,
                input_count=input_count,
                output_count=output_count,
                error_message=error,
            )
        )

    log.info(
        "run_start run_id=%s query=%s topic=%s limit=%s enable_youtube=%s db=%s",
        run_id,
        params.query,
        params.topic,
        params.limit,
        params.enable_youtube,
        settings.database_url,
    )
    record("run_start", "OK")
    set_llm_run_id(run_id)
    set_web_run_id(run_id)

    t0 = time.time()
    raw_posts, ingest_summary = ingest_all(
        query=params.query,
        topic=params.topic,
        limit=params.limit,
        enable_youtube=params.enable_youtube,
        run_id=run_id,
        overrides=params.ingest_overrides,
        sources=params.sources,
        sources_config=params.sources_config,
        category_mode=params.category_mode,
        category_filters=params.category_filters or [],
        exclude_categories=params.exclude_categories or [],
    )
    ingest_status = "OK" if raw_posts else "WARN"
    ingest_error = "; ".join([f"{e['source']}: {e['error']}" for e in ingest_summary.errors]) if ingest_summary.errors else None
    record("ingest", ingest_status, input_count=0, output_count=len(raw_posts), error=ingest_error)
    log.info("run_ingest posts=%s errors=%s elapsed=%.2fs", len(raw_posts), len(ingest_summary.errors), time.time() - t0)

    notes: list[str] = []
    category_counts = {
        k.split(":", 1)[1]: int(v)
        for k, v in (ingest_summary.counts or {}).items()
        if ":" in str(k)
    }
    if ingest_summary.errors:
        notes.append("Ingestion issues: " + ingest_error)
    if ingest_summary.warnings:
        notes.append("Source warnings: " + "; ".join([f"{w['source']}: {w['warning']}" for w in ingest_summary.warnings]))

    if len(raw_posts) == 0:
        notes.append("No posts collected. Check provider availability and rate limits.")
        report_paths = export_reports([], [], title=f"Opportunity Report: {params.topic} / {params.query}", notes=notes)
        record("report", "OK", input_count=0, output_count=0, error="no_data")
        log.info("run_reports %s", report_paths)
        return {
            "run_id": run_id,
            "raw_posts": 0,
            "pains": 0,
            "clusters": 0,
            "ideas": 0,
            "reports": report_paths,
            "errors": ingest_summary.errors,
            "warnings": ingest_summary.warnings,
            "source_counts": ingest_summary.counts,
            "category_counts": category_counts,
        }

    try:
        validate_llm_config()
    except LLMError as e:
        record("llm_validate", "ERROR", input_count=len(raw_posts), output_count=0, error=str(e))
        log.error("llm_config_invalid error=%s", e)
        notes.append(f"LLM misconfigured: {e}")
        report_paths = export_reports([], [], title=f"Opportunity Report: {params.topic} / {params.query}", notes=notes)
        record("report", "OK", input_count=0, output_count=0, error="llm_config_invalid")
        return {
            "run_id": run_id,
            "raw_posts": len(raw_posts),
            "pains": 0,
            "clusters": 0,
            "ideas": 0,
            "reports": report_paths,
            "errors": ingest_summary.errors,
            "warnings": ingest_summary.warnings,
            "source_counts": ingest_summary.counts,
            "category_counts": category_counts,
        }

    t1 = time.time()
    try:
        pains = extract_pains(raw_posts, topic=params.topic, run_id=run_id)
    except Exception as e:
        record("extract", "ERROR", input_count=len(raw_posts), output_count=0, error=str(e))
        log.error("run_extract_failed error=%s", e)
        notes.append(f"Extraction failed: {e}")
        report_paths = export_reports([], [], title=f"Opportunity Report: {params.topic} / {params.query}", notes=notes)
        record("report", "OK", input_count=0, output_count=0, error="extract_failed")
        return {
            "run_id": run_id,
            "raw_posts": len(raw_posts),
            "pains": 0,
            "clusters": 0,
            "ideas": 0,
            "reports": report_paths,
            "errors": ingest_summary.errors,
            "warnings": ingest_summary.warnings,
            "source_counts": ingest_summary.counts,
            "category_counts": category_counts,
        }
    status = "OK" if pains else "WARN"
    record("extract", status, input_count=len(raw_posts), output_count=len(pains))
    log.info("run_extract pains=%s elapsed=%.2fs", len(pains), time.time() - t1)
    if not pains:
        notes.append("Extraction produced 0 pains from collected posts.")

    t2 = time.time()
    try:
        clusters = cluster_pains(pains, run_id=run_id)
    except Exception as e:
        record("cluster", "ERROR", input_count=len(pains), output_count=0, error=str(e))
        log.error("run_cluster_failed error=%s", e)
        notes.append(f"Clustering failed: {e}")
        clusters = []
    record("cluster", "OK" if clusters else "WARN", input_count=len(pains), output_count=len(clusters))
    log.info("run_cluster clusters=%s elapsed=%.2fs", len(clusters), time.time() - t2)

    t3 = time.time()
    try:
        scored = score_clusters(clusters, run_id=run_id)
    except Exception as e:
        record("score", "ERROR", input_count=len(clusters), output_count=0, error=str(e))
        log.error("run_score_failed error=%s", e)
        notes.append(f"Scoring failed: {e}")
        scored = []
    record("score", "OK" if scored else "WARN", input_count=len(clusters), output_count=len(scored))
    log.info("run_score clusters=%s elapsed=%.2fs", len(scored), time.time() - t3)

    t4 = time.time()
    try:
        ideas = generate_ideas_for_clusters(scored, topic=params.topic, run_id=run_id)
    except Exception as e:
        record("ideas", "ERROR", input_count=len(scored), output_count=0, error=str(e))
        log.error("run_ideas_failed error=%s", e)
        notes.append(f"Idea generation failed: {e}")
        ideas = []
    record("ideas", "OK" if ideas else "WARN", input_count=len(scored), output_count=len(ideas))
    log.info("run_ideas ideas=%s elapsed=%.2fs", len(ideas), time.time() - t4)

    report_paths = export_reports(scored, ideas, title=f"Opportunity Report: {params.topic} / {params.query}", notes=notes)
    record("report", "OK", input_count=len(scored), output_count=len(ideas))
    log.info("run_reports %s", report_paths)
    return {
        "run_id": run_id,
        "raw_posts": len(raw_posts),
        "pains": len(pains),
        "clusters": len(scored),
        "ideas": len(ideas),
        "reports": report_paths,
        "errors": ingest_summary.errors,
        "warnings": ingest_summary.warnings,
        "source_counts": ingest_summary.counts,
        "category_counts": category_counts,
    }


from core.discovery import discover_topics
from storage.repository import list_clusters

def run_auto_discovery(
    ideas_per_run: int = 5,
    target_topics: int = 20,
    limit_per_topic: int = 30,
    ingest_overrides: dict[str, int] | None = None,
) -> dict:
    log = logging.getLogger(__name__)
    log.info("auto_discovery_start target_topics=%s ideas_per_run=%s", target_topics, ideas_per_run)
    topics = discover_topics(target=target_topics)
    log.info("auto_discovery_topics count=%s", len(topics))
    # For each discovered topic, run a small scan; accumulate pains in same run context
    total = {"raw_posts": 0, "pains": 0, "clusters": 0, "ideas": 0, "reports": {}, "errors": []}
    for t in topics:
        try:
            res = run_end_to_end(
                RunParams(
                    query=t.topic,
                    topic="auto",
                    limit=limit_per_topic,
                    enable_youtube=False,
                    ingest_overrides=ingest_overrides,
                )
            )
            total["raw_posts"] += res["raw_posts"]
            total["pains"] += res["pains"]
            if res.get("errors"):
                total["errors"].extend(res["errors"])
        except Exception as e:
            log.exception("auto_discovery_run_failed topic=%s", t.topic)
            total["errors"].append({"topic": t.topic, "error": str(e)})
    # After multiple runs, pick top clusters and generate only N ideas (ideas already inserted; we just export fresh report)
    clusters = list_clusters(limit=50)
    # Choose best ideas across clusters in DB; API/UI will show them.
    total["clusters"] = len(clusters)
    # reports already written per run; overwrite a combined report is handled by latest run
    log.info("auto_discovery_done clusters=%s errors=%s", total["clusters"], len(total["errors"]))
    return total


def generate_top_ideas_from_db(ideas: int = 8, cluster_limit: int = 80, topic: str = "db") -> dict:
    """Generate ideas directly from persisted clusters/pains without re-ingestion."""
    log = logging.getLogger(__name__)
    clusters = list_clusters_all(limit=cluster_limit)
    if not clusters:
        return {"clusters": 0, "ideas": 0, "items": []}

    scored = score_clusters(clusters)
    generated = generate_ideas_for_clusters(scored, topic=topic, max_ideas=max(1, int(ideas)))

    rows = []
    by_cluster = {i.cluster_id: i for i in generated}
    for c in scored[: max(ideas, min(len(scored), 20))]:
        rows.append(
            {
                "cluster_label": c.cluster_label,
                "opportunity_score": c.opportunity_score,
                "idea_name": by_cluster.get(c.cluster_id).idea_name if by_cluster.get(c.cluster_id) else "-",
            }
        )
    log.info("top_from_db_done clusters=%s ideas=%s", len(scored), len(generated))
    return {"clusters": len(scored), "ideas": len(generated), "items": rows}
