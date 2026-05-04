from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from connectors.x_trends_playwright import fetch_x_trends
from core.config import settings
from ingestion.normalization import normalize_topic_key
from ingestion.reddit.comments import reddit_fetch_comments
from ingestion.reddit.search import reddit_search
from ingestion.web.search import web_search
from ingestion.youtube.comments import fetch_video_comments
from ingestion.youtube.search import youtube_search
from storage.models import RawPost
from storage.repository import upsert_raw_posts

_CATEGORY_QUERY_HINTS: dict[str, list[str]] = {
    "business_ops": ["invoice reconciliation", "ap workflow", "back office operations"],
    "marketing": ["content workflow", "campaign reporting", "attribution pain"],
    "sales": ["lead follow up", "pipeline hygiene", "crm updates"],
    "field_service": ["dispatch scheduling", "work order tracking", "service estimates"],
    "ecommerce": ["shopify operations", "returns workflow", "catalog updates"],
    "creator": ["creator production workflow", "editing pipeline", "sponsorship ops"],
    "dev_tools": ["developer workflow friction", "build pipeline pain", "debugging toil"],
    "game_dev": ["game dev workflow pain", "unity pipeline pain", "qa triage pain"],
}

_DEFAULT_BROAD_CATEGORIES = [
    "business_ops",
    "marketing",
    "sales",
    "field_service",
    "ecommerce",
    "creator",
    "dev_tools",
    "game_dev",
]


def _normalized_categories(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        key = str(item or "").strip().lower().replace(" ", "_")
        if key and key in _CATEGORY_QUERY_HINTS and key not in out:
            out.append(key)
    return out


def _resolve_category_queries(
    query: str,
    *,
    category_mode: str,
    category_filters: list[str],
    exclude_categories: list[str],
) -> list[tuple[str, str]]:
    mode = str(category_mode or "broad").strip().lower()
    include = _normalized_categories(category_filters)
    exclude = set(_normalized_categories(exclude_categories))
    if mode == "strict":
        categories = include or ["business_ops"]
    elif mode == "focused":
        categories = include if include else _DEFAULT_BROAD_CATEGORIES[:4]
        for fallback in _DEFAULT_BROAD_CATEGORIES:
            if len(categories) >= 4:
                break
            if fallback not in categories:
                categories.append(fallback)
    else:
        categories = list(_DEFAULT_BROAD_CATEGORIES)
        if include:
            for cat in include:
                if cat not in categories:
                    categories.append(cat)
    categories = [cat for cat in categories if cat not in exclude]
    if not categories:
        categories = ["business_ops"]
    out: list[tuple[str, str]] = []
    for cat in categories:
        hints = _CATEGORY_QUERY_HINTS.get(cat) or []
        hint = hints[0] if hints else cat
        out.append((cat, f"{query} {hint}".strip()))
    return out


@dataclass
class IngestSummary:
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    warnings: list[dict[str, str]] = field(default_factory=list)

    def add_count(self, source: str, n: int) -> None:
        self.counts[source] = self.counts.get(source, 0) + n

    def add_error(self, source: str, error: Exception | str) -> None:
        self.errors.append({"source": source, "error": str(error)})

    def add_warning(self, source: str, warning: str) -> None:
        self.warnings.append({"source": source, "warning": warning})


def ingest_all(
    query: str,
    topic: str,
    limit: int = 50,
    enable_youtube: bool = False,
    run_id: str | None = None,
    overrides: dict[str, int] | None = None,
    sources: dict[str, bool] | None = None,
    sources_config: dict[str, dict[str, Any]] | None = None,
    category_mode: str = "broad",
    category_filters: list[str] | None = None,
    exclude_categories: list[str] | None = None,
) -> tuple[list[RawPost], IngestSummary]:
    log = logging.getLogger(__name__)
    posts: list[RawPost] = []
    summary = IngestSummary()

    overrides = overrides or {}
    sources = sources or {}
    sources_config = sources_config or {}

    reddit_max_posts = overrides.get("reddit_max_posts", settings.reddit_max_posts)
    reddit_max_comment_posts = overrides.get("reddit_max_comment_posts", settings.reddit_max_comment_posts)
    reddit_max_comments_per_post = overrides.get("reddit_max_comments_per_post", settings.reddit_max_comments_per_post)
    youtube_max_videos = overrides.get("youtube_max_videos", settings.youtube_max_videos)
    youtube_max_comments_per_video = overrides.get("youtube_max_comments_per_video", settings.youtube_max_comments_per_video)
    youtube_search_max_results = overrides.get("youtube_search_max_results", settings.youtube_search_max_results)
    web_search_max_results = overrides.get("web_search_max_results", settings.web_search_max_results)

    x_cfg = sources_config.get("x_trends") or {}
    x_enabled = bool(
        x_cfg.get("enabled")
        if "enabled" in x_cfg
        else sources.get("x_trends", settings.enable_x_trends)
    )
    x_max_items = int(x_cfg.get("max_items", settings.x_trends_max_items))
    x_max_items = max(1, min(30, x_max_items))

    enable_reddit = bool(sources.get("reddit", True))
    enable_web = bool(sources.get("google_trends", settings.web_search_enabled)) and settings.web_search_enabled
    enable_yt = bool(sources.get("youtube", enable_youtube or settings.enable_youtube))

    # Split budget across classic sources (x_trends has its own cap and is signal-only).
    active_sources: list[str] = []
    if enable_reddit and reddit_max_posts > 0:
        active_sources.append("reddit")
    if enable_web and web_search_max_results > 0:
        active_sources.append("web")
    if enable_yt and youtube_max_videos > 0:
        active_sources.append("youtube")

    per_source = 0
    remainder = 0
    if limit > 0 and active_sources:
        per_source = limit // len(active_sources)
        remainder = limit % len(active_sources)

    def _alloc(idx: int) -> int:
        return per_source + (1 if idx < remainder else 0)

    reddit_n = _alloc(0) if active_sources else 0
    web_n = _alloc(active_sources.index("web")) if "web" in active_sources else 0
    yt_n = _alloc(active_sources.index("youtube")) if "youtube" in active_sources else 0

    reddit_n = min(reddit_n, reddit_max_posts)
    web_n = min(web_n, web_search_max_results)
    yt_n = min(yt_n, youtube_max_videos)

    log.info(
        "ingest_start query=%s limit=%s reddit_n=%s web_n=%s yt_n=%s x_enabled=%s x_max_items=%s",
        query,
        limit,
        reddit_n,
        web_n,
        yt_n,
        x_enabled,
        x_max_items,
    )

    if reddit_n > 0:
        log.info("ingest_reddit_search start")
        try:
            bucket_queries = _resolve_category_queries(
                query,
                category_mode=category_mode,
                category_filters=category_filters or [],
                exclude_categories=exclude_categories or [],
            )
            per_bucket = max(1, reddit_n // max(1, len(bucket_queries)))
            remaining = reddit_n
            reddit_total = 0
            for idx, (bucket, bucket_query) in enumerate(bucket_queries):
                alloc = min(remaining, per_bucket + (1 if idx < (reddit_n % len(bucket_queries)) else 0))
                if alloc <= 0:
                    continue
                bucket_posts = reddit_search(bucket_query, limit=alloc)
                for post in bucket_posts:
                    post.metadata_ = {**(post.metadata_ or {}), "category_bucket": bucket}
                posts.extend(bucket_posts)
                summary.add_count(f"reddit:{bucket}", len(bucket_posts))
                reddit_total += len(bucket_posts)
                remaining -= alloc
                if remaining <= 0:
                    break
            summary.add_count("reddit", reddit_total)
            log.info("ingest_reddit_search done count=%s buckets=%s", reddit_total, len(bucket_queries))
        except Exception as exc:
            summary.add_error("reddit_search", exc)
            log.exception("ingest_reddit_search failed")
    else:
        log.info("ingest_reddit_search skipped reddit_n=0")

    log.info("ingest_reddit_comments start")
    comment_posts: list[RawPost] = []
    try:
        reddit_posts = [x for x in posts if x.source == "reddit"]
        reddit_posts.sort(key=lambda p: p.engagement_score, reverse=True)
        for p in reddit_posts[: min(len(reddit_posts), reddit_max_comment_posts)]:
            pid = p.id.split(":", 1)[-1] if ":" in p.id else p.id
            try:
                comment_posts.extend(reddit_fetch_comments(pid, limit=reddit_max_comments_per_post))
            except Exception as exc:
                summary.add_error("reddit_comments", exc)
                continue
        if comment_posts:
            posts.extend(comment_posts)
            summary.add_count("reddit_comment", len(comment_posts))
        log.info("ingest_reddit_comments done count=%s", len(comment_posts))
    except Exception as exc:
        summary.add_error("reddit_comments", exc)
        log.exception("ingest_reddit_comments failed")

    if web_n > 0 and enable_web:
        log.info("ingest_web_search start")
        try:
            bucket_queries = _resolve_category_queries(
                query,
                category_mode=category_mode,
                category_filters=category_filters or [],
                exclude_categories=exclude_categories or [],
            )
            per_bucket = max(1, web_n // max(1, len(bucket_queries)))
            remaining = web_n
            web_total = 0
            for idx, (bucket, bucket_query) in enumerate(bucket_queries):
                alloc = min(remaining, per_bucket + (1 if idx < (web_n % len(bucket_queries)) else 0))
                if alloc <= 0:
                    continue
                bucket_posts = web_search(bucket_query, limit=alloc)
                for post in bucket_posts:
                    post.metadata_ = {**(post.metadata_ or {}), "category_bucket": bucket}
                posts.extend(bucket_posts)
                summary.add_count(f"web:{bucket}", len(bucket_posts))
                web_total += len(bucket_posts)
                remaining -= alloc
                if remaining <= 0:
                    break
            summary.add_count("web", web_total)
            log.info("ingest_web_search done count=%s buckets=%s", web_total, len(bucket_queries))
        except Exception as exc:
            summary.add_error("web_search", exc)
            log.exception("ingest_web_search failed")
    else:
        log.info("ingest_web_search skipped web_n=%s enabled=%s", web_n, enable_web)

    if enable_yt:
        log.info("ingest_youtube_search start")
        try:
            if yt_n > 0:
                yt_videos = youtube_search(query, limit=min(yt_n, youtube_search_max_results), region=settings.youtube_region)
                posts.extend(yt_videos)
                summary.add_count("youtube", len(yt_videos))
                log.info("ingest_youtube_search done count=%s", len(yt_videos))
                if settings.youtube_api_key:
                    log.info("ingest_youtube_comments start videos=%s", min(len(yt_videos), youtube_max_videos))
                    for v in yt_videos[: youtube_max_videos]:
                        vid = (v.metadata_ or {}).get("video_id")
                        if not vid:
                            continue
                        try:
                            posts.extend(fetch_video_comments(vid, max_comments=youtube_max_comments_per_video))
                        except Exception:
                            summary.add_error("youtube_comments", f"youtube_comments_failed video_id={vid}")
                            continue
                    summary.add_count("youtube_comment", len([p for p in posts if p.source == "youtube_comment"]))
                    log.info("ingest_youtube_comments done")
                else:
                    warning = "missing_youtube_api_key"
                    log.warning("ingest_youtube_comments skipped %s", warning)
                    summary.add_warning("youtube_comments", warning)
            else:
                log.info("ingest_youtube_search skipped yt_n=0")
        except Exception:
            summary.add_error("youtube_search", "youtube_search_failed")
            log.exception("ingest_youtube_search failed")

    if x_enabled:
        log.info("ingest_x_trends start")
        x_options = {
            "enabled": True,
            "max_items": x_max_items,
            "timeout_ms": int(x_cfg.get("timeout_ms", settings.x_trends_timeout_ms)),
            "nav_timeout_ms": int(x_cfg.get("nav_timeout_ms", settings.x_trends_nav_timeout_ms)),
            "use_auth": bool(x_cfg.get("use_auth", settings.x_trends_use_auth)),
            "storage_state_path": str(x_cfg.get("storage_state_path", settings.x_trends_storage_state_path)),
            "locale": str(x_cfg.get("locale", settings.x_trends_locale)),
            "region_hint": str(x_cfg.get("region_hint", settings.x_trends_region_hint)),
            "url": str(x_cfg.get("url", settings.x_trends_url)),
            "fallback_url": str(x_cfg.get("fallback_url", settings.x_trends_fallback_url)),
            "debug": bool(x_cfg.get("debug", settings.x_trends_debug)),
        }
        try:
            x_rows, x_warnings = fetch_x_trends(x_options)
            for warning in x_warnings:
                summary.add_warning("x", warning)
            now = datetime.utcnow()
            x_posts: list[RawPost] = []
            for row in x_rows:
                title = str(row.get("title") or "").strip()
                if not title:
                    continue
                sid = str(row.get("source_id") or normalize_trend_topic(title) or hashlib.sha1(title.encode()).hexdigest()[:12])
                metrics = row.get("metrics") or {}
                rank = int(metrics.get("rank") or len(x_posts) + 1)
                x_posts.append(
                    RawPost(
                        id=f"x:{sid}",
                        run_id=run_id,
                        source="x",
                        url=str(row.get("url") or settings.x_trends_fallback_url),
                        author=None,
                        timestamp=now,
                        text=title,
                        engagement_score=max(0, 30 - rank),
                        metadata_={
                            "source_confidence": row.get("source_confidence", "low"),
                            "metrics": {
                                "rank": rank,
                                "post_count_text": metrics.get("post_count_text"),
                                "category": metrics.get("category"),
                                "tab_label": metrics.get("tab_label"),
                            },
                            "raw_json": row.get("raw_json") or {},
                        },
                    )
                )
            posts.extend(x_posts)
            summary.add_count("x", len(x_posts))
            log.info("ingest_x_trends done count=%s warnings=%s", len(x_posts), len(x_warnings))
        except Exception as exc:
            summary.add_warning("x", f"x_connector_soft_failed: {exc}")
            log.exception("ingest_x_trends failed soft")

    deduped: list[RawPost] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    seen_text: set[str] = set()
    seen_topic_keys: set[str] = set()

    for p in posts:
        p.run_id = p.run_id or run_id
        text_hash = hashlib.sha1((p.text or "").encode()).hexdigest()
        topic_key = normalize_topic_key(p.text or "")
        if p.id in seen_ids:
            continue
        if p.url and p.url in seen_urls:
            continue
        if text_hash in seen_text:
            continue
        if topic_key and topic_key in seen_topic_keys:
            continue
        seen_ids.add(p.id)
        if p.url:
            seen_urls.add(p.url)
        seen_text.add(text_hash)
        if topic_key:
            seen_topic_keys.add(topic_key)
        deduped.append(p)

    upsert_raw_posts(deduped)
    log.info("ingest_done total_posts=%s deduped=%s", len(posts), len(deduped))
    return deduped, summary
