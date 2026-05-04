from __future__ import annotations

import asyncio
import hashlib
import json
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from trend_harvester.config import get_settings
from trend_harvester.db import SessionLocal
from trend_harvester.enums import RunStatus
from trend_harvester.models import Analysis, Candidate, Run, Topic, TopicInstance
from trend_harvester.schemas import RunStartRequest
from trend_harvester.services.channels import get_channel_records_json
from trend_harvester.services.connectors.google_trends import GoogleTrendsConnector
from trend_harvester.services.connectors.reddit import RedditConnector
from trend_harvester.services.connectors.x_trends import XTrendsConnector
from trend_harvester.services.connectors.youtube import YouTubeConnector
from trend_harvester.services.dedupe import cluster_candidates, normalize_title
from trend_harvester.services.focus import expand_focus_keywords, focus_relevance_score, is_low_signal_title
from trend_harvester.services.llm import LLMAnalyzer
from trend_harvester.services.run_logs import append_run_log
from trend_harvester.services.scoring import score_topic_instance


class HarvesterService:
    def __init__(self):
        self.settings = get_settings()
        self.channel_records = get_channel_records_json()
        self.youtube = YouTubeConnector(self.settings)
        self.reddit = RedditConnector(self.settings)
        self.trends = GoogleTrendsConnector(self.settings)
        self.x = XTrendsConnector(self.settings)
        self.llm = LLMAnalyzer(self.settings)
        self._tasks: dict[str, asyncio.Task] = {}
        self._futures: dict[str, Future] = {}
        self._cancel_requests: set[str] = set()
        # Single worker ensures explicit QUEUED -> RUNNING behavior for subsequent runs.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="harvester")

    def start_run(self, db: Session, payload: RunStartRequest) -> str:
        request_hash = hashlib.sha256(
            json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        # Always create a new run so users can queue repeated runs with identical settings.
        # Stale queued/running rows are still reconciled by API status reconciliation logic.

        run = Run(
            status=RunStatus.QUEUED.value,
            params_json=payload.model_dump(mode="json"),
            totals_json={},
            request_hash=request_hash,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        append_run_log(run.id, "Run queued", event="run_queued", payload={"status": run.status})

        self._schedule_run(run.id)
        return run.id

    def _schedule_run(self, run_id: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            future = self._executor.submit(asyncio.run, self._execute_run(run_id))
            self._futures[run_id] = future

            def _cleanup(_: Future) -> None:
                self._futures.pop(run_id, None)

            future.add_done_callback(_cleanup)
            return

        task = loop.create_task(self._execute_run(run_id))
        self._tasks[run_id] = task

        def _cleanup(_: asyncio.Task) -> None:
            self._tasks.pop(run_id, None)

        task.add_done_callback(_cleanup)

    def is_running(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is not None:
            return not task.done()
        future = self._futures.get(run_id)
        if future is not None:
            return not future.done()
        return False

    def request_cancel(self, run_id: str) -> None:
        self._cancel_requests.add(run_id)
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            task.cancel()
        future = self._futures.get(run_id)
        if future is not None and not future.done():
            future.cancel()

    def _is_cancel_requested(self, run_id: str) -> bool:
        return run_id in self._cancel_requests

    def nudge_run(self, run_id: str) -> None:
        if not self.is_running(run_id):
            self._schedule_run(run_id)

    async def _execute_run(self, run_id: str) -> None:
        db = SessionLocal()
        try:
            run = db.get(Run, run_id)
            if not run:
                return
            if self._is_cancel_requested(run_id):
                run.status = RunStatus.FAILED.value
                run.error = "Run stopped by user before execution."
                run.finished_at = datetime.now(timezone.utc)
                db.commit()
                return
            run.status = RunStatus.RUNNING.value
            run.started_at = datetime.now(timezone.utc)
            run.totals_json = {
                "stage": "starting",
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "events": ["run started"],
                "progress_pct": 2,
            }
            db.commit()
            append_run_log(run.id, "Run started", event="run_started", payload={"stage": "starting", "progress_pct": 2})

            payload = RunStartRequest.model_validate(run.params_json)
            focus_query = (payload.focus_query or "").strip()
            llm_calls = self._new_llm_calls_state(payload)
            if self._is_cancel_requested(run_id):
                raise RuntimeError("Run stopped by user.")
            limits = self._resolve_limits(payload)
            fetch_plan = self._build_fetch_plan(payload)
            self._mark_progress(
                db,
                run,
                stage="fetching_sources",
                progress_pct=8,
                message="Collecting candidates from enabled sources",
                extra={
                    "enabled_sources": {
                        "youtube": payload.sources.youtube.enabled,
                        "reddit": payload.sources.reddit.enabled,
                        "trends": payload.sources.trends.enabled,
                        "x": payload.sources.x.enabled,
                    },
                    "limits": limits,
                    "channel_inventory": self.channel_records,
                    "fetch_plan": fetch_plan,
                    "llm_calls": llm_calls,
                },
            )

            fetch_tasks = []
            if payload.sources.youtube.enabled:
                fetch_tasks.append(
                    self.youtube.fetch(
                        payload.region,
                        fetch_plan["youtube_categories"],
                        limits["youtube"],
                        search_queries=fetch_plan["youtube_queries"],
                    )
                )
            if payload.sources.reddit.enabled:
                per_sub = max(1, limits["reddit"] // max(1, len(fetch_plan["subreddits"])))
                fetch_tasks.append(self.reddit.fetch(fetch_plan["subreddits"], per_sub))
            if payload.sources.trends.enabled:
                fetch_tasks.append(self.trends.fetch(payload.region, limits["trends"]))
            if payload.sources.x.enabled:
                fetch_tasks.append(self.x.fetch(payload.region, limits["x"], seed_queries=fetch_plan["youtube_queries"]))

            fetched = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            if self._is_cancel_requested(run_id):
                raise RuntimeError("Run stopped by user.")
            all_candidates: list[dict] = []
            source_errors: dict[str, str] = {}
            source_candidate_counts: dict[str, int] = {"youtube": 0, "reddit": 0, "trends": 0, "x": 0}

            for idx, result in enumerate(fetched):
                if isinstance(result, Exception):
                    source_errors[f"source_{idx}"] = str(result)
                    continue
                all_candidates.extend(result)
                for item in result:
                    src = str(item.get("source", ""))
                    source_candidate_counts[src] = source_candidate_counts.get(src, 0) + 1
            min_keep_by_source = {
                # Keep a stronger floor for fast-headline sources so grouped LLM calls have richer context.
                "trends": min(max(10, int(limits["trends"] * 0.85)), max(1, limits["trends"])),
                "x": min(max(8, int(limits["x"] * 0.8)), max(1, limits["x"])),
            }
            all_candidates, filtered_candidate_count, filtered_by_source, kept_by_source = self._filter_candidates(
                all_candidates,
                focus_query,
                min_keep_by_source=min_keep_by_source,
            )

            self._mark_progress(
                db,
                run,
                stage="storing_candidates",
                progress_pct=20,
                message="Persisting candidate records",
                extra={
                    "candidate_count": len(all_candidates),
                    "filtered_candidate_count": filtered_candidate_count,
                    "source_candidate_counts": source_candidate_counts,
                    "kept_candidate_counts": kept_by_source,
                    "filtered_candidate_counts": filtered_by_source,
                    "source_errors": source_errors,
                    "fetch_plan": fetch_plan,
                },
            )

            candidate_models = []
            for item in all_candidates:
                candidate_models.append(
                    Candidate(
                        run_id=run.id,
                        source=item["source"],
                        source_id=str(item["source_id"]),
                        title=item["title"][:1000],
                        url=item["url"][:1000],
                        published_at=item.get("published_at"),
                        raw_json=_truncate_json(item.get("raw_json", {})),
                    )
                )
            db.add_all(candidate_models)
            db.commit()

            self._mark_progress(
                db,
                run,
                stage="clustering_topics",
                progress_pct=35,
                message="Clustering related candidates into canonical topics",
                extra={"candidate_count": len(candidate_models)},
            )

            clusters = cluster_candidates(
                [
                    {
                        "source": c.source,
                        "source_id": c.source_id,
                        "title": c.title,
                        "url": c.url,
                        "published_at": c.published_at,
                        "raw_json": c.raw_json,
                        "metrics": c.raw_json.get("statistics", c.raw_json),
                    }
                    for c in candidate_models
                ],
                threshold=self.settings.similarity_threshold,
            )
            if self._is_cancel_requested(run_id):
                raise RuntimeError("Run stopped by user.")

            topic_instances: list[TopicInstance] = []
            for cluster in clusters:
                representative = max(cluster, key=lambda x: len(x["title"]))
                normalized_key = normalize_title(representative["title"])[:256]

                topic = db.scalar(select(Topic).where(Topic.normalized_key == normalized_key).limit(1))
                now = datetime.now(timezone.utc)
                if not topic:
                    topic = Topic(
                        canonical_title=representative["title"][:1000],
                        normalized_key=normalized_key,
                        entities_json={},
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                    db.add(topic)
                    db.flush()
                else:
                    topic.last_seen_at = now

                source_count = len({x["source"] for x in cluster})
                for item in cluster:
                    metrics = self._extract_metrics(item)
                    score, reasons = score_topic_instance(item["source"], metrics, cross_source_count=source_count)
                    topic_instances.append(
                        TopicInstance(
                            run_id=run.id,
                            topic_id=topic.id,
                            source=item["source"],
                            url=item["url"][:1000],
                            metrics_json=metrics,
                            score=score,
                            reasons_json=reasons,
                        )
                    )
            db.add_all(topic_instances)
            db.commit()

            self._mark_progress(
                db,
                run,
                stage="llm_analysis",
                progress_pct=55,
                message="Running LLM topic analysis",
                extra={"topic_count": len(clusters), "instance_count": len(topic_instances), "llm_calls": llm_calls},
            )

            await self._analyze_topics(db, run, payload=payload, llm_calls=llm_calls)
            if self._is_cancel_requested(run_id):
                raise RuntimeError("Run stopped by user.")
            if focus_query and payload.llm_rerank_top_n > 0:
                self._mark_progress(
                    db,
                    run,
                    stage="focus_rerank",
                    progress_pct=94,
                    message=f"LLM focus grading for top {payload.llm_rerank_top_n} topics",
                    extra={"focus_query": focus_query, "llm_calls": llm_calls},
                )
                await self._grade_focus_topics(
                    db=db,
                    run=run,
                    focus_query=focus_query,
                    objective=payload.objective,
                    top_n=payload.llm_rerank_top_n,
                    llm_calls=llm_calls,
                )

            if llm_calls.get("status") == "running":
                llm_calls["status"] = "completed"

            run.totals_json = {
                "candidate_count": len(candidate_models),
                "topic_count": len(clusters),
                "instance_count": len(topic_instances),
                "focus_query": focus_query,
                "min_focus_relevance": payload.min_focus_relevance,
                "source_candidate_counts": source_candidate_counts,
                "source_errors": source_errors,
                "channel_inventory": self.channel_records,
                "fetch_plan": fetch_plan,
                "llm_calls": llm_calls,
                "stage": "completed",
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "progress_pct": 100,
                "events": (run.totals_json or {}).get("events", []),
            }
            run.status = RunStatus.SUCCEEDED.value
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            append_run_log(
                run.id,
                "Run completed successfully",
                event="run_completed",
                payload={"stage": "completed", "progress_pct": 100, "status": run.status},
            )
        except Exception as exc:  # noqa: BLE001
            run = db.get(Run, run_id)
            if run:
                prev_totals = run.totals_json or {}
                run.status = RunStatus.FAILED.value
                run.error = ("Run stopped by user." if self._is_cancel_requested(run_id) else str(exc))[:2000]
                run.finished_at = datetime.now(timezone.utc)
                llm_calls = prev_totals.get("llm_calls", {})
                if isinstance(llm_calls, dict):
                    llm_calls["status"] = "failed"
                run.totals_json = {
                    **prev_totals,
                    "llm_calls": llm_calls if isinstance(llm_calls, dict) else prev_totals.get("llm_calls"),
                    "stage": "failed",
                    "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                    "progress_pct": prev_totals.get("progress_pct", 0),
                    "last_exception": str(exc)[:500],
                }
                db.commit()
                append_run_log(
                    run.id,
                    "Run failed",
                    level="ERROR",
                    event="run_failed",
                    payload={"error": run.error or str(exc)[:500], "stage": "failed", "status": run.status},
                )
        finally:
            db.close()
            self._cancel_requests.discard(run_id)
            self._tasks.pop(run_id, None)
            self._futures.pop(run_id, None)

    def _mark_progress(
        self,
        db: Session,
        run: Run,
        *,
        stage: str,
        progress_pct: int,
        message: str,
        extra: dict | None = None,
    ) -> None:
        current = dict(run.totals_json or {})
        events = current.get("events")
        if not isinstance(events, list):
            events = []
        timestamp = datetime.now(timezone.utc).isoformat()
        events.append(f"{timestamp} {message}")
        if len(events) > 120:
            events = events[-120:]
        current.update(extra or {})
        current["stage"] = stage
        current["progress_pct"] = int(max(0, min(100, progress_pct)))
        current["heartbeat_at"] = timestamp
        current["events"] = events
        run.totals_json = current
        db.commit()
        append_run_log(
            run.id,
            message,
            event="stage_progress",
            payload={"stage": stage, "progress_pct": current["progress_pct"]},
        )

    def _new_llm_calls_state(self, payload: RunStartRequest) -> dict:
        retries = max(1, int(self.settings.retries))
        endpoint_count = max(1, int(self.llm.endpoint_count))
        rerank_top_n = int(max(0, payload.llm_rerank_top_n))
        return {
            "status": "idle",
            "endpoints": self.llm.endpoints,
            "endpoint_count": endpoint_count,
            "retries_per_logical_call": retries,
            "max_http_attempts_per_logical_call": retries * endpoint_count,
            "max_http_attempts_per_run": max(1, int(self.settings.llm_max_http_attempts_per_run)),
            "planned_from_settings": {
                "llm_rerank_top_n": rerank_top_n,
                "focus_query_enabled": bool((payload.focus_query or "").strip()),
            },
            "expected": {
                "analysis_logical_calls": 0,
                "focus_logical_calls": rerank_top_n if bool((payload.focus_query or "").strip()) else 0,
                "total_logical_calls": 0,
                "max_http_attempts": 0,
            },
            "actual": {
                "logical_started": 0,
                "logical_completed": 0,
                "logical_failed": 0,
                "retries": 0,
                "http_attempt_started": 0,
                "http_attempt_succeeded": 0,
                "http_attempt_failed": 0,
            },
            "by_kind": {},
            "endpoint_stats": {},
            "api_health": {"last_http_event": "", "last_http_error": "", "last_http_endpoint": ""},
            "last_event_at": None,
            "last_event": "",
            "attempt_cap_reached": False,
            "degraded_reason": "",
        }

    @staticmethod
    def _llm_kind_bucket(llm_calls: dict, call_kind: str) -> dict:
        by_kind = llm_calls.get("by_kind")
        if not isinstance(by_kind, dict):
            by_kind = {}
            llm_calls["by_kind"] = by_kind
        bucket = by_kind.get(call_kind)
        if not isinstance(bucket, dict):
            bucket = {
                "logical_started": 0,
                "logical_completed": 0,
                "logical_failed": 0,
                "retries": 0,
                "http_attempt_started": 0,
                "http_attempt_succeeded": 0,
                "http_attempt_failed": 0,
            }
            by_kind[call_kind] = bucket
        return bucket

    @staticmethod
    def _consume_llm_event(llm_calls: dict, event: dict) -> None:
        if not isinstance(event, dict):
            return
        actual = llm_calls.get("actual")
        if not isinstance(actual, dict):
            actual = {}
            llm_calls["actual"] = actual
        call_kind = str(event.get("call_kind", "unknown")).strip() or "unknown"
        bucket = HarvesterService._llm_kind_bucket(llm_calls, call_kind)
        event_name = str(event.get("event", "")).strip()
        run_id = str(event.get("run_id", "")).strip()
        endpoint = str(event.get("endpoint", "")).strip()
        endpoint_stats = llm_calls.get("endpoint_stats")
        if not isinstance(endpoint_stats, dict):
            endpoint_stats = {}
            llm_calls["endpoint_stats"] = endpoint_stats
        if endpoint:
            row = endpoint_stats.get(endpoint)
            if not isinstance(row, dict):
                row = {"started": 0, "succeeded": 0, "failed": 0, "last_error": "", "last_status_code": None}
            endpoint_stats[endpoint] = row
        else:
            row = None
        api_health = llm_calls.get("api_health")
        if not isinstance(api_health, dict):
            api_health = {"last_http_event": "", "last_http_error": "", "last_http_endpoint": ""}
            llm_calls["api_health"] = api_health
        if event_name == "logical_call_started":
            actual["logical_started"] = int(actual.get("logical_started", 0)) + 1
            bucket["logical_started"] = int(bucket.get("logical_started", 0)) + 1
        elif event_name == "logical_call_completed":
            actual["logical_completed"] = int(actual.get("logical_completed", 0)) + 1
            bucket["logical_completed"] = int(bucket.get("logical_completed", 0)) + 1
        elif event_name == "logical_call_failed":
            actual["logical_failed"] = int(actual.get("logical_failed", 0)) + 1
            bucket["logical_failed"] = int(bucket.get("logical_failed", 0)) + 1
        elif event_name == "logical_call_retry":
            actual["retries"] = int(actual.get("retries", 0)) + 1
            bucket["retries"] = int(bucket.get("retries", 0)) + 1
        elif event_name == "http_attempt_started":
            actual["http_attempt_started"] = int(actual.get("http_attempt_started", 0)) + 1
            bucket["http_attempt_started"] = int(bucket.get("http_attempt_started", 0)) + 1
            if row is not None:
                row["started"] = int(row.get("started", 0)) + 1
            api_health["last_http_event"] = "started"
            api_health["last_http_endpoint"] = endpoint
            if run_id:
                append_run_log(
                    run_id,
                    f"HTTP attempt started ({call_kind})",
                    event="llm_http_started",
                    payload={"endpoint": endpoint, "logical_attempt": event.get("logical_attempt")},
                )
        elif event_name == "http_attempt_succeeded":
            actual["http_attempt_succeeded"] = int(actual.get("http_attempt_succeeded", 0)) + 1
            bucket["http_attempt_succeeded"] = int(bucket.get("http_attempt_succeeded", 0)) + 1
            if row is not None:
                row["succeeded"] = int(row.get("succeeded", 0)) + 1
                row["last_status_code"] = event.get("status_code")
            api_health["last_http_event"] = "succeeded"
            api_health["last_http_endpoint"] = endpoint
            api_health["last_http_error"] = ""
            if run_id:
                append_run_log(
                    run_id,
                    f"HTTP attempt succeeded ({call_kind})",
                    event="llm_http_ok",
                    payload={"endpoint": endpoint, "logical_attempt": event.get("logical_attempt"), "status_code": event.get("status_code")},
                )
        elif event_name == "http_attempt_failed":
            actual["http_attempt_failed"] = int(actual.get("http_attempt_failed", 0)) + 1
            bucket["http_attempt_failed"] = int(bucket.get("http_attempt_failed", 0)) + 1
            err = str(event.get("error", "")).strip()
            if row is not None:
                row["failed"] = int(row.get("failed", 0)) + 1
                row["last_error"] = err[:320]
            api_health["last_http_event"] = "failed"
            api_health["last_http_endpoint"] = endpoint
            api_health["last_http_error"] = err[:320]
            if run_id:
                append_run_log(
                    run_id,
                    f"HTTP attempt failed ({call_kind}): {err[:180]}",
                    level="WARN",
                    event="llm_http_failed",
                    payload={"endpoint": endpoint, "logical_attempt": event.get("logical_attempt")},
                )
        llm_calls["last_event_at"] = datetime.now(timezone.utc).isoformat()
        llm_calls["last_event"] = event_name

    async def _analyze_topics(self, db: Session, run: Run, *, payload: RunStartRequest, llm_calls: dict) -> None:
        run_id = run.id
        topic_ids = db.scalars(select(TopicInstance.topic_id).where(TopicInstance.run_id == run_id).distinct()).all()
        cache_cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.llm_cache_days)
        total_topics = len(topic_ids)
        if total_topics == 0:
            llm_calls["status"] = "completed"
            expected = llm_calls.get("expected", {})
            if isinstance(expected, dict):
                expected["analysis_logical_calls"] = 0
                expected["total_logical_calls"] = 0
                expected["max_http_attempts"] = 0
            self._mark_progress(
                db,
                run,
                stage="llm_analysis",
                progress_pct=80,
                message="No topics to analyze",
                extra={"llm_total_topics": 0, "llm_done_topics": 0, "llm_calls": llm_calls},
            )
            return

        pending: list[tuple[str, str, dict]] = []
        completed = 0

        for topic_id in topic_ids:
            if self._is_cancel_requested(run_id):
                raise RuntimeError("Run stopped by user.")
            topic = db.get(Topic, topic_id)
            if not topic:
                continue

            latest = db.scalar(
                select(Analysis)
                .where(Analysis.topic_id == topic_id)
                .order_by(desc(Analysis.created_at))
                .limit(1)
            )
            latest_created_at = _as_utc(latest.created_at) if latest else None
            if latest and latest_created_at and latest_created_at >= cache_cutoff:
                analysis = Analysis(
                    topic_id=topic_id,
                    run_id=run_id,
                    llm_summary=latest.llm_summary,
                    channel_tags_json=latest.channel_tags_json,
                    angle_suggestions_json=latest.angle_suggestions_json,
                )
                db.add(analysis)
                db.commit()
                completed += 1
                continue

            instances = db.scalars(
                select(TopicInstance).where(TopicInstance.run_id == run_id, TopicInstance.topic_id == topic_id)
            ).all()
            pending.append((topic_id, topic.canonical_title, self._build_topic_signals(instances)))

        expected = llm_calls.get("expected", {})
        if not isinstance(expected, dict):
            expected = {}
            llm_calls["expected"] = expected
        expected["analysis_logical_calls"] = len(pending)
        focus_expected = int(payload.llm_rerank_top_n) if bool((payload.focus_query or "").strip()) else 0
        expected["focus_logical_calls"] = max(0, min(total_topics, focus_expected))
        expected["total_logical_calls"] = int(expected.get("analysis_logical_calls", 0)) + int(expected.get("focus_logical_calls", 0))
        expected["max_http_attempts"] = int(expected.get("total_logical_calls", 0)) * int(
            llm_calls.get("max_http_attempts_per_logical_call", 1)
        )
        llm_calls["status"] = "running"
        llm_calls["cache_hits"] = completed

        if completed > 0:
            self._mark_progress(
                db,
                run,
                stage="llm_analysis",
                progress_pct=55 + int((completed / max(total_topics, 1)) * 40),
                message=f"LLM cache reuse for {completed}/{total_topics} topics",
                extra={"llm_total_topics": total_topics, "llm_done_topics": completed, "llm_calls": llm_calls},
            )

        if not pending:
            return

        semaphore = asyncio.Semaphore(max(1, self.settings.llm_max_parallel))

        def _progress_event(event: dict) -> None:
            self._consume_llm_event(llm_calls, event)

        async def _analyze_one(topic_id: str, title: str, signals: dict) -> tuple[str, dict]:
            async with semaphore:
                if self._is_cancel_requested(run_id):
                    raise RuntimeError("Run stopped by user.")
                try:
                    analyzed = await self.llm.analyze_topic(title, signals, run_id=run_id, progress_cb=_progress_event)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    analyzed = {
                        "summary": f"Trending topic: {title}",
                        "hooks": [],
                        "channel_relevance": {},
                    }
                return topic_id, analyzed

        pending_tasks = {asyncio.create_task(_analyze_one(topic_id, title, signals)) for topic_id, title, signals in pending}
        done_count = 0
        while pending_tasks:
            if self._is_cancel_requested(run_id):
                for task in pending_tasks:
                    task.cancel()
                await asyncio.gather(*pending_tasks, return_exceptions=True)
                raise RuntimeError("Run stopped by user.")
            done, pending_tasks = await asyncio.wait(pending_tasks, timeout=8.0, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                in_flight = len(pending_tasks)
                self._mark_progress(
                    db,
                    run,
                    stage="llm_analysis",
                    progress_pct=55 + int(((completed + done_count) / max(total_topics, 1)) * 40),
                    message=f"LLM calls in flight: {in_flight}",
                    extra={"llm_total_topics": total_topics, "llm_done_topics": completed + done_count, "llm_calls": llm_calls},
                )
                continue
            for task in done:
                topic_id, analyzed = task.result()
                analysis = Analysis(
                    topic_id=topic_id,
                    run_id=run_id,
                    llm_summary=analyzed["summary"],
                    channel_tags_json=analyzed["channel_relevance"],
                    angle_suggestions_json=analyzed["hooks"],
                )
                db.add(analysis)
                db.commit()
                done_count += 1
                done_total = completed + done_count
                if done_count == 1 or done_count % 3 == 0 or done_total == total_topics:
                    self._mark_progress(
                        db,
                        run,
                        stage="llm_analysis",
                        progress_pct=55 + int((done_total / max(total_topics, 1)) * 40),
                        message=f"LLM analyzed topic {done_total}/{total_topics}",
                        extra={"llm_total_topics": total_topics, "llm_done_topics": done_total, "llm_calls": llm_calls},
                    )

    @staticmethod
    def _build_topic_signals(instances: list[TopicInstance]) -> dict:
        source_scores: dict[str, float] = {}
        source_counts: dict[str, int] = {}
        source_groups: dict[str, dict] = {}
        metric_highlights: dict[str, int | float] = {}
        all_scores: list[float] = []

        for inst in instances:
            all_scores.append(inst.score)
            source = str(inst.source or "unknown")
            source_scores[source] = max(source_scores.get(source, 0.0), float(inst.score))
            source_counts[source] = source_counts.get(source, 0) + 1
            row = source_groups.get(source)
            if not isinstance(row, dict):
                row = {
                    "source": source,
                    "count": 0,
                    "top_score": 0.0,
                    "sample_urls": [],
                    "metric_highlights": {},
                }
                source_groups[source] = row
            row["count"] = int(row.get("count", 0)) + 1
            row["top_score"] = round(max(float(row.get("top_score", 0.0)), float(inst.score)), 2)
            sample_urls = row.get("sample_urls")
            if not isinstance(sample_urls, list):
                sample_urls = []
            if len(sample_urls) < 3 and inst.url:
                sample_urls.append(str(inst.url)[:160])
            row["sample_urls"] = sample_urls
            metrics = inst.metrics_json or {}
            for key in ("view_count", "like_count", "comment_count", "score", "num_comments", "rank"):
                value = metrics.get(key)
                try:
                    value_f = float(value)
                except (TypeError, ValueError):
                    continue
                previous = metric_highlights.get(key)
                if previous is None or value_f > float(previous):
                    metric_highlights[key] = value_f
                grouped_metrics = row.get("metric_highlights")
                if not isinstance(grouped_metrics, dict):
                    grouped_metrics = {}
                grouped_prev = grouped_metrics.get(key)
                if grouped_prev is None or value_f > float(grouped_prev):
                    grouped_metrics[key] = value_f
                row["metric_highlights"] = grouped_metrics

        avg_score = round(sum(all_scores) / max(len(all_scores), 1), 2)
        grouped_rows = sorted(source_groups.values(), key=lambda x: float(x.get("top_score", 0.0)), reverse=True)
        return {
            "source_count": len(source_scores),
            "source_scores": source_scores,
            "source_counts": source_counts,
            "source_groups": grouped_rows,
            "avg_instance_score": avg_score,
            "max_instance_score": round(max(all_scores) if all_scores else 0.0, 2),
            "metric_highlights": metric_highlights,
        }

    async def _grade_focus_topics(
        self,
        *,
        db: Session,
        run: Run,
        focus_query: str,
        objective: str,
        top_n: int,
        llm_calls: dict,
    ) -> None:
        run_id = run.id
        topic_rows = db.execute(
            select(
                Topic.id,
                Topic.canonical_title,
                func.sum(TopicInstance.score).label("total_score"),
            )
            .join(TopicInstance, Topic.id == TopicInstance.topic_id)
            .where(TopicInstance.run_id == run_id)
            .group_by(Topic.id)
            .order_by(desc("total_score"))
            .limit(max(0, int(top_n)))
        ).all()
        if not topic_rows:
            expected = llm_calls.get("expected", {})
            if isinstance(expected, dict):
                expected["focus_logical_calls"] = 0
                expected["total_logical_calls"] = int(expected.get("analysis_logical_calls", 0))
                expected["max_http_attempts"] = int(expected.get("total_logical_calls", 0)) * int(
                    llm_calls.get("max_http_attempts_per_logical_call", 1)
                )
            return

        expected = llm_calls.get("expected", {})
        if isinstance(expected, dict):
            expected["focus_logical_calls"] = len(topic_rows)
            expected["total_logical_calls"] = int(expected.get("analysis_logical_calls", 0)) + int(expected.get("focus_logical_calls", 0))
            expected["max_http_attempts"] = int(expected.get("total_logical_calls", 0)) * int(
                llm_calls.get("max_http_attempts_per_logical_call", 1)
            )

        analyses = {
            row.topic_id: row
            for row in db.execute(
                select(Analysis.topic_id, Analysis.llm_summary, Analysis.channel_tags_json)
                .where(Analysis.run_id == run_id)
            ).all()
        }
        semaphore = asyncio.Semaphore(max(1, self.settings.llm_max_parallel))
        run_id = run.id

        def _progress_event(event: dict) -> None:
            self._consume_llm_event(llm_calls, event)

        async def _one(topic_id: str, title: str) -> tuple[str, dict]:
            if self._is_cancel_requested(run_id):
                raise RuntimeError("Run stopped by user.")
            analysis = analyses.get(topic_id)
            instances = db.scalars(
                select(TopicInstance).where(TopicInstance.run_id == run_id, TopicInstance.topic_id == topic_id)
            ).all()
            signals = self._build_topic_signals(instances)
            summary = analysis.llm_summary if analysis else ""
            existing = analysis.channel_tags_json if analysis else {}
            async with semaphore:
                if self._is_cancel_requested(run_id):
                    raise RuntimeError("Run stopped by user.")
                try:
                    graded = await self.llm.grade_topic_focus(
                        title=title,
                        summary=summary,
                        signals=signals,
                        focus_query=focus_query,
                        objective=objective,
                        channel_relevance=existing,
                        run_id=run_id,
                        progress_cb=_progress_event,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    lexical = focus_relevance_score(title, focus_query)
                    graded = {
                        "overall_score": lexical,
                        "focus_relevance": lexical,
                        "actionability_video": 0.0,
                        "actionability_blog": 0.0,
                        "actionability_app": 0.0,
                        "channel_fit": existing if isinstance(existing, dict) else {},
                        "reason": "fallback_grade",
                    }
            return topic_id, graded

        pending_tasks = {asyncio.create_task(_one(row.id, row.canonical_title)) for row in topic_rows}
        results: list[tuple[str, dict]] = []
        total_focus = len(pending_tasks)
        done_focus = 0
        while pending_tasks:
            if self._is_cancel_requested(run_id):
                for task in pending_tasks:
                    task.cancel()
                await asyncio.gather(*pending_tasks, return_exceptions=True)
                raise RuntimeError("Run stopped by user.")
            done, pending_tasks = await asyncio.wait(pending_tasks, timeout=8.0, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                self._mark_progress(
                    db,
                    run,
                    stage="focus_rerank",
                    progress_pct=94 + int((done_focus / max(total_focus, 1)) * 5),
                    message=f"LLM focus calls in flight: {len(pending_tasks)}",
                    extra={"llm_calls": llm_calls},
                )
                continue
            for task in done:
                results.append(task.result())
                done_focus += 1
                self._mark_progress(
                    db,
                    run,
                    stage="focus_rerank",
                    progress_pct=94 + int((done_focus / max(total_focus, 1)) * 5),
                    message=f"LLM focus graded {done_focus}/{total_focus}",
                    extra={"llm_calls": llm_calls},
                )
        totals = dict(run.totals_json or {})
        focus_grades = totals.get("focus_grades", {})
        if not isinstance(focus_grades, dict):
            focus_grades = {}
        for topic_id, graded in results:
            focus_grades[topic_id] = graded
        totals["focus_query"] = focus_query
        totals["focus_objective"] = objective
        totals["focus_grades"] = focus_grades
        totals["llm_calls"] = llm_calls
        run.totals_json = totals
        db.commit()

    def _resolve_limits(self, payload: RunStartRequest) -> dict[str, int]:
        size = payload.limits.size
        defaults = {
                "small": {
                    "youtube": self.settings.small_youtube_limit,
                    "reddit": self.settings.small_reddit_limit,
                    "trends": self.settings.small_trends_limit,
                    "x": self.settings.small_x_limit,
                },
                "medium": {
                    "youtube": self.settings.medium_youtube_limit,
                    "reddit": self.settings.medium_reddit_limit,
                    "trends": self.settings.medium_trends_limit,
                    "x": self.settings.medium_x_limit,
                },
                "large": {
                    "youtube": self.settings.large_youtube_limit,
                    "reddit": self.settings.large_reddit_limit,
                    "trends": self.settings.large_trends_limit,
                    "x": self.settings.large_x_limit,
                },
            }[size]

        youtube = payload.limits.youtube if payload.limits.youtube is not None else defaults["youtube"]
        reddit = payload.limits.reddit if payload.limits.reddit is not None else defaults["reddit"]
        trends = payload.limits.trends if payload.limits.trends is not None else defaults["trends"]
        x = payload.limits.x if payload.limits.x is not None else defaults["x"]

        return {
            "youtube": min(max(youtube, 1), self.settings.max_youtube_limit),
            "reddit": min(max(reddit, 1), self.settings.max_reddit_limit),
            "trends": min(max(trends, 1), self.settings.max_trends_limit),
            "x": min(max(x, 1), self.settings.max_x_limit),
        }

    def _build_fetch_plan(self, payload: RunStartRequest) -> dict[str, list[str]]:
        registry = list(self.channel_records)
        focus_tokens = expand_focus_keywords(payload.focus_query)
        youtube_categories = list(payload.categories)
        subreddit_pool = list(payload.subreddits)
        query_terms: list[str] = [payload.focus_query] if payload.focus_query.strip() else []

        for record in registry:
            profile = str(record.get("profile", "")).lower()
            terms = [str(item) for item in record.get("query_terms", []) if isinstance(item, str)]
            include = not focus_tokens
            if focus_tokens and any(token in profile for token in focus_tokens):
                include = True
            if focus_tokens and any(any(token in term.lower() for token in focus_tokens) for term in terms):
                include = True
            if include:
                youtube_categories.extend([str(item) for item in record.get("youtube_categories", []) if isinstance(item, str)])
                subreddit_pool.extend([str(item) for item in record.get("reddit_subreddits", []) if isinstance(item, str)])
                query_terms.extend(terms[:2])

        query_terms.extend(focus_tokens[:8])
        return {
            "youtube_categories": list(dict.fromkeys(item for item in youtube_categories if item)),
            "subreddits": list(dict.fromkeys(item for item in subreddit_pool if item))[:20],
            "youtube_queries": list(dict.fromkeys(item.strip() for item in query_terms if item and item.strip()))[:12],
        }

    @staticmethod
    def _filter_candidates(
        items: list[dict],
        focus_query: str,
        *,
        min_keep_by_source: dict[str, int] | None = None,
    ) -> tuple[list[dict], int, dict[str, int], dict[str, int]]:
        focus = (focus_query or "").strip()
        min_keep_by_source = {str(k): max(0, int(v)) for k, v in (min_keep_by_source or {}).items()}
        filtered_by_source: dict[str, int] = {}
        kept_by_source: dict[str, int] = {}
        for item in items:
            source = str(item.get("source", "unknown"))
            filtered_by_source.setdefault(source, 0)
            kept_by_source.setdefault(source, 0)
            title = str(item.get("title", ""))
            if is_low_signal_title(title):
                filtered_by_source[source] += 1
                continue
            raw = item.get("raw_json")
            relevance = None
            if focus:
                relevance = focus_relevance_score(title, focus)
                if isinstance(raw, dict):
                    raw["focus_relevance"] = relevance
            else:
                relevance = 1.0

            # Defer thresholding until we can enforce per-source minimum keeps.
            item["_tmp_focus_relevance"] = relevance

        # Apply relevance threshold with per-source floor.
        grouped: dict[str, list[dict]] = {}
        for item in items:
            if "_tmp_focus_relevance" not in item:
                continue
            source = str(item.get("source", "unknown"))
            grouped.setdefault(source, []).append(item)

        out: list[dict] = []
        for source, rows in grouped.items():
            if not focus:
                out.extend(rows)
                kept_by_source[source] += len(rows)
                continue

            threshold = 0.08
            if source in {"trends", "x"}:
                threshold = 0.02

            passing = [row for row in rows if float(row.get("_tmp_focus_relevance", 0.0) or 0.0) >= threshold]
            passing_ids = {id(row) for row in passing}

            min_keep = min_keep_by_source.get(source, 0)
            if len(passing) < min_keep:
                remainder = [row for row in rows if id(row) not in passing_ids]
                remainder.sort(key=lambda r: float(r.get("_tmp_focus_relevance", 0.0) or 0.0), reverse=True)
                passing.extend(remainder[: max(0, min_keep - len(passing))])

            kept_by_source[source] += len(passing)
            filtered_by_source[source] += max(0, len(rows) - len(passing))
            out.extend(passing)

        for item in items:
            item.pop("_tmp_focus_relevance", None)

        filtered_count = sum(filtered_by_source.values())
        return out, filtered_count, filtered_by_source, kept_by_source

    @staticmethod
    def _extract_metrics(item: dict) -> dict:
        source = item.get("source")
        raw = item.get("raw_json", {}) or {}
        if source == "youtube":
            stats = raw.get("statistics", {})
            return {
                "view_count": stats.get("view_count"),
                "like_count": stats.get("like_count"),
                "comment_count": stats.get("comment_count"),
            }
        if source == "reddit":
            return {
                "score": raw.get("score"),
                "num_comments": raw.get("num_comments"),
                "upvote_ratio": raw.get("upvote_ratio"),
            }
        if source in {"trends", "x"}:
            return {"rank": raw.get("rank")}
        return {}


def _truncate_json(payload: dict, max_chars: int = 5000) -> dict:
    serialized = json.dumps(payload, ensure_ascii=True)
    if len(serialized) <= max_chars:
        return payload
    return {"truncated": True, "preview": serialized[:max_chars]}


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


harvester_service = HarvesterService()
