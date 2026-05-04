from __future__ import annotations

from typing import Any

from app.modules.webagent.constants import WEBAGENT_RUN_TYPE_ALIASES


def _int(raw: Any, default: int, lo: int, hi: int) -> int:
    try:
        val = int(raw)
    except Exception:
        val = default
    return max(lo, min(hi, val))


def _bool(raw: Any, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def normalize_settings(raw: dict[str, Any]) -> dict[str, Any]:
    settings = dict(raw or {})
    requested = str(settings.get("requested_run_type") or settings.get("run_type") or "web-discovery").strip().lower()
    canonical = WEBAGENT_RUN_TYPE_ALIASES.get(requested, requested)

    mode = str(settings.get("mode") or canonical).strip().lower()
    aggression = str(settings.get("aggression") or settings.get("deep_explore_aggression") or "normal").strip().lower()
    if aggression not in {"safe", "normal", "aggressive", "destructive-test"}:
        aggression = "normal"

    run_profile = str(settings.get("automation_profile") or mode).strip().lower()
    if run_profile in {"full-automation", "interactive-automation", "e2e-workflow", "workflow-e2e"}:
        run_profile = "test"

    include_screenshots = _bool(settings.get("include_screenshots", settings.get("save_screenshots", True)), True)
    include_generated_tests = _bool(settings.get("include_generated_tests", True), True)
    save_trace = _bool(settings.get("save_trace", True), True)
    save_video = _bool(settings.get("save_video", True), True)
    enable_live_view = _bool(settings.get("enable_live_view", False), False)
    headed_mode = _bool(settings.get("headed_mode", False), False)
    if enable_live_view and not headed_mode:
        headed_mode = True

    max_pages = _int(settings.get("max_pages", 40), 40, 1, 1000)
    crawl_depth = _int(settings.get("crawl_depth", 2), 2, 0, 20)
    max_actions = _int(settings.get("max_actions", 200), 200, 1, 5000)
    max_fills = _int(settings.get("max_fills", 300), 300, 1, 5000)
    max_clicks = _int(settings.get("max_clicks", 400), 400, 1, 5000)

    tool_defaults = {
        "wait_strategy": str(settings.get("wait_strategy") or "domcontentloaded"),
        "selector_strategy": str(settings.get("selector_strategy") or "auto"),
        "strict_targeting": _bool(settings.get("strict_targeting", False), False),
        "retry_count": _int(settings.get("retry_count", 1), 1, 0, 10),
        "retry_backoff_ms": _int(settings.get("retry_backoff_ms", 250), 250, 0, 5000),
    }

    return {
        "requested_run_type": requested,
        "run_type": canonical,
        "mode": mode,
        "automation_profile": run_profile,
        "objective": str(settings.get("objective", "") or "").strip(),
        "notes": str(settings.get("notes", "") or "").strip(),
        "crawl_depth": crawl_depth,
        "max_pages": max_pages,
        "domain_policy": str(settings.get("domain_policy", "same-domain") or "same-domain"),
        "same_origin_only": _bool(settings.get("same_origin_only", True), True),
        "domain_allowlist": settings.get("domain_allowlist", []),
        "include_screenshots": include_screenshots,
        "include_generated_tests": include_generated_tests,
        "include_lighthouse": _bool(settings.get("include_lighthouse", False), False),
        "passive_only_security": _bool(settings.get("passive_only_security", True), True),
        "enable_live_view": enable_live_view,
        "headed_mode": headed_mode,
        "save_trace": save_trace,
        "save_video": save_video,
        "save_screenshots": _bool(settings.get("save_screenshots", include_screenshots), include_screenshots),
        "save_console_logs": _bool(settings.get("save_console_logs", True), True),
        "save_network_summary": _bool(settings.get("save_network_summary", True), True),
        "save_dom_artifacts": _bool(settings.get("save_dom_artifacts", True), True),
        "save_generated_tests": _bool(settings.get("save_generated_tests", include_generated_tests), include_generated_tests),
        "viewport_preset": str(settings.get("viewport_preset", "desktop") or "desktop"),
        "trace_mode": str(settings.get("trace_mode", "on") or "on"),
        "video_mode": str(settings.get("video_mode", "on") or "on"),
        "timeout_seconds": _int(settings.get("timeout_seconds", 900), 900, 5, 7200),
        "max_actions": max_actions,
        "max_clicks": max_clicks,
        "max_fills": max_fills,
        "max_depth": _int(settings.get("max_depth", crawl_depth), crawl_depth, 0, 30),
        "aggression": aggression,
        "allow_destructive": _bool(settings.get("allow_destructive", aggression == "destructive-test"), aggression == "destructive-test"),
        "confirm_destructive": _bool(settings.get("confirm_destructive", False), False),
        "allowlist_selectors": settings.get("allowlist_selectors", []),
        "denylist_selectors": settings.get("denylist_selectors", []),
        "fill_profile": str(settings.get("fill_profile") or "realistic"),
        "persona_seed": _int(settings.get("persona_seed", 7), 7, 0, 10_000_000),
        "upload_size_limit_bytes": _int(settings.get("upload_size_limit_bytes", 25_000_000), 25_000_000, 1024, 2_000_000_000),
        "upload_profiles": settings.get("upload_profiles", ["tiny", "realistic", "oversized", "unsupported", "multiple", "mixed"]),
        "pii_mask_logs": _bool(settings.get("pii_mask_logs", True), True),
        "scrub_secrets": _bool(settings.get("scrub_secrets", True), True),
        "browser_launch": settings.get("browser_launch", {}),
        "context_options": settings.get("context_options", {}),
        "page_options": settings.get("page_options", {}),
        "playwright_action_bundle": [
            str(v).strip() for v in (settings.get("playwright_action_bundle") or []) if str(v).strip()
        ],
        "tool_defaults": tool_defaults,
        "report": {
            "machine_json": _bool(settings.get("report_machine_json", True), True),
            "markdown": _bool(settings.get("report_markdown", True), True),
            "attach_artifacts": _bool(settings.get("report_attach_artifacts", True), True),
        },
    }
