from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path


@dataclass(slots=True)
class ChannelRecord:
    slug: str
    display_name: str
    profile: str
    youtube_channel_id: str = ""
    channel_title: str = ""
    channel_description: str = ""
    focus_tags: list[str] = field(default_factory=list)
    category: str = ""
    repo_slug: str = ""
    aliases: list[str] = field(default_factory=list)
    youtube_categories: list[str] = field(default_factory=list)
    reddit_subreddits: list[str] = field(default_factory=list)
    query_terms: list[str] = field(default_factory=list)
    source: str = "registry"
    enabled: bool = True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "channel_registry.json"


def _slugify(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "-" for ch in (value or "").strip())
    parts = [part for part in text.split("-") if part]
    return "-".join(parts)


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in values if isinstance(item, str) and item.strip()))


def _merge_lists(base: list[str], extra: list[str]) -> list[str]:
    return _unique_strings([*base, *extra])


def _load_registry_rows() -> list[dict]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = payload.get("channels") if isinstance(payload, dict) else None
    return rows if isinstance(rows, list) else []


def _record_from_row(row: dict) -> ChannelRecord | None:
    if not isinstance(row, dict):
        return None
    slug = _slugify(str(row.get("slug", "")))
    name = str(row.get("display_name", "")).strip()
    profile = str(row.get("profile", "")).strip()
    if not slug or not name or not profile:
        return None
    return ChannelRecord(
        slug=slug,
        display_name=name,
        profile=profile,
        youtube_channel_id=str(row.get("youtube_channel_id") or row.get("channel_id") or "").strip(),
        channel_title=str(row.get("channel_title", "")).strip(),
        channel_description=str(row.get("channel_description", "")).strip(),
        focus_tags=_unique_strings(list(row.get("focus_tags", []) or [])),
        category=str(row.get("category", "")).strip(),
        repo_slug=str(row.get("repo_slug", "")).strip().lower(),
        aliases=_unique_strings(list(row.get("aliases", []) or [])),
        youtube_categories=_unique_strings(list(row.get("youtube_categories", []) or [])),
        reddit_subreddits=_unique_strings(list(row.get("reddit_subreddits", []) or [])),
        query_terms=_unique_strings(list(row.get("query_terms", []) or [])),
        source="registry",
        enabled=bool(row.get("enabled", True)),
    )


def _env_channels() -> list[str]:
    raw = str(os.getenv("TREND_CHANNELS_CSV", "")).strip()
    if not raw:
        return []
    return _unique_strings(raw.split(","))


def _env_profiles() -> dict[str, str]:
    raw = str(os.getenv("TREND_CHANNEL_PROFILES_JSON", "")).strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
            out[key.strip()] = value.strip()
    return out


def _discover_monitor_rows() -> list[dict]:
    status_dir = (_repo_root() / "monitor" / "status").resolve()
    if not status_dir.exists() or not status_dir.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(status_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        social = data.get("social") if isinstance(data.get("social"), dict) else {}
        identifiers = data.get("identifiers") if isinstance(data.get("identifiers"), dict) else {}
        last = data.get("last") if isinstance(data.get("last"), dict) else {}
        title_candidates = [
            social.get("youtube_channel_title"),
            identifiers.get("name"),
            data.get("display_name"),
            (
                ((last.get("comment_summary") or {}).get("youtube_channel_title"))
                if isinstance(last.get("comment_summary"), dict)
                else None
            ),
        ]
        display_name = next((str(v).strip() for v in title_candidates if isinstance(v, str) and v.strip()), "")
        repo_slug = str(last.get("channel") or data.get("repo") or path.stem).strip().lower()
        if not repo_slug and not display_name:
            continue
        rows.append(
            {
                "repo_slug": repo_slug,
                "display_name": display_name or repo_slug,
                "aliases": [path.stem, repo_slug, display_name],
                "source": "monitor_status",
            }
        )
    return rows


def _discover_repo_rows() -> list[dict]:
    ai_root = _repo_root()
    rows: list[dict] = []
    for config_path in sorted(ai_root.glob("*/config.json")):
        repo_slug = config_path.parent.name.strip().lower()
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        channel = payload.get("channel") if isinstance(payload, dict) else {}
        display_name = ""
        if isinstance(channel, dict):
            display_name = str(channel.get("name", "")).strip()
        rows.append(
            {
                "repo_slug": repo_slug,
                "display_name": display_name or repo_slug,
                "aliases": [repo_slug, display_name],
                "source": "repo_config",
            }
        )
    return rows


def _merge_record(existing: ChannelRecord, incoming: ChannelRecord) -> ChannelRecord:
    display_name = existing.display_name
    if existing.display_name == existing.slug and incoming.display_name:
        display_name = incoming.display_name
    elif incoming.source == "registry" and incoming.display_name:
        display_name = incoming.display_name

    profile = existing.profile
    if incoming.profile and (not profile or incoming.source == "registry"):
        profile = incoming.profile

    repo_slug = existing.repo_slug or incoming.repo_slug
    youtube_channel_id = existing.youtube_channel_id or incoming.youtube_channel_id
    channel_title = incoming.channel_title or existing.channel_title
    channel_description = incoming.channel_description or existing.channel_description
    focus_tags = _merge_lists(existing.focus_tags, incoming.focus_tags)
    category = incoming.category or existing.category
    aliases = _merge_lists(existing.aliases, incoming.aliases)
    youtube_categories = _merge_lists(existing.youtube_categories, incoming.youtube_categories)
    reddit_subreddits = _merge_lists(existing.reddit_subreddits, incoming.reddit_subreddits)
    query_terms = _merge_lists(existing.query_terms, incoming.query_terms)
    source = existing.source if existing.source == "registry" else incoming.source

    return ChannelRecord(
        slug=existing.slug,
        display_name=display_name,
        profile=profile,
        youtube_channel_id=youtube_channel_id,
        channel_title=channel_title,
        channel_description=channel_description,
        focus_tags=focus_tags,
        category=category,
        repo_slug=repo_slug,
        aliases=aliases,
        youtube_categories=youtube_categories,
        reddit_subreddits=reddit_subreddits,
        query_terms=query_terms,
        source=source,
        enabled=existing.enabled and incoming.enabled,
    )


def _lookup_key(display_name: str, repo_slug: str, aliases: list[str], by_alias: dict[str, str]) -> str:
    candidates = [repo_slug, display_name, *aliases]
    for candidate in candidates:
        slug = _slugify(str(candidate))
        if not slug:
            continue
        if slug in by_alias:
            return by_alias[slug]
    return _slugify(repo_slug or display_name)


@lru_cache(maxsize=1)
def get_channel_records() -> list[ChannelRecord]:
    records_by_slug: dict[str, ChannelRecord] = {}
    alias_to_slug: dict[str, str] = {}

    for row in _load_registry_rows():
        record = _record_from_row(row)
        if not record or not record.enabled:
            continue
        records_by_slug[record.slug] = record
        for alias in [record.slug, record.display_name, record.repo_slug, *record.aliases]:
            slug = _slugify(alias)
            if slug:
                alias_to_slug[slug] = record.slug

    discovered_rows = [*_discover_monitor_rows(), *_discover_repo_rows()]
    for row in discovered_rows:
        display_name = str(row.get("display_name", "")).strip()
        repo_slug = str(row.get("repo_slug", "")).strip().lower()
        aliases = _unique_strings(list(row.get("aliases", []) or []))
        channel_slug = _lookup_key(display_name, repo_slug, aliases, alias_to_slug)
        existing = records_by_slug.get(channel_slug)
        source = str(row.get("source", "discovered")).strip() or "discovered"
        fallback_profile = existing.profile if existing else (f"General content channel about {display_name or repo_slug}.")
        incoming = ChannelRecord(
            slug=channel_slug,
            display_name=display_name or (existing.display_name if existing else repo_slug or channel_slug),
            profile=fallback_profile,
            youtube_channel_id=existing.youtube_channel_id if existing else "",
            channel_title=existing.channel_title if existing else "",
            channel_description=existing.channel_description if existing else "",
            focus_tags=existing.focus_tags if existing else [],
            category=existing.category if existing else "",
            repo_slug=repo_slug or (existing.repo_slug if existing else ""),
            aliases=aliases,
            source=source,
        )
        records_by_slug[channel_slug] = _merge_record(existing, incoming) if existing else incoming
        for alias in [channel_slug, display_name, repo_slug, *aliases]:
            slug = _slugify(alias)
            if slug:
                alias_to_slug[slug] = channel_slug

    env_profiles = _env_profiles()
    env_channels = _env_channels()
    if env_channels:
        explicit: list[ChannelRecord] = []
        for name in env_channels:
            slug = _lookup_key(name, "", [name], alias_to_slug) or _slugify(name)
            current = records_by_slug.get(slug)
            explicit.append(
                ChannelRecord(
                    slug=slug,
                    display_name=name,
                    profile=env_profiles.get(name, current.profile if current else f"General content channel about {name}."),
                    youtube_channel_id=current.youtube_channel_id if current else "",
                    channel_title=current.channel_title if current else "",
                    channel_description=current.channel_description if current else "",
                    focus_tags=current.focus_tags if current else [],
                    category=current.category if current else "",
                    repo_slug=current.repo_slug if current else "",
                    aliases=current.aliases if current else [],
                    youtube_categories=current.youtube_categories if current else [],
                    reddit_subreddits=current.reddit_subreddits if current else [],
                    query_terms=current.query_terms if current else [],
                    source="env_override",
                )
            )
        records_by_slug = {record.slug: record for record in explicit}
    else:
        for name, profile in env_profiles.items():
            slug = _lookup_key(name, "", [name], alias_to_slug) or _slugify(name)
            current = records_by_slug.get(slug)
            if current:
                records_by_slug[slug] = ChannelRecord(
                    slug=current.slug,
                    display_name=current.display_name,
                    profile=profile,
                    youtube_channel_id=current.youtube_channel_id,
                    channel_title=current.channel_title,
                    channel_description=current.channel_description,
                    focus_tags=current.focus_tags,
                    category=current.category,
                    repo_slug=current.repo_slug,
                    aliases=current.aliases,
                    youtube_categories=current.youtube_categories,
                    reddit_subreddits=current.reddit_subreddits,
                    query_terms=current.query_terms,
                    source="env_profile",
                )

    records = [record for record in records_by_slug.values() if record.enabled]
    records.sort(key=lambda item: item.display_name.lower())
    return records


def get_channels() -> list[str]:
    return [record.display_name for record in get_channel_records()]


def get_channel_profiles() -> dict[str, str]:
    return {record.display_name: record.profile for record in get_channel_records()}


def get_channel_records_json() -> list[dict]:
    return [asdict(record) for record in get_channel_records()]
