# Dashburg Integration Notes

## Purpose

Trend Harvester now returns a fuller channel inventory, channel-aware fetch planning, and richer ranking data. Dashburg should consume these new fields instead of assuming a fixed hard-coded channel list or only top-2 matches.

## New Result Fields

`GET /api/runs/{run_id}/results` now includes:

- `channels_used`
  - Full channel registry used for the run.
  - Each item includes:
    - `slug`
    - `display_name`
    - `profile`
    - `repo_slug`
    - `aliases`
    - `youtube_categories`
    - `reddit_subreddits`
    - `query_terms`
    - `source`
    - `enabled`
- `empty_channels`
  - Channel names that received no viable candidates.
- `fetch_plan`
  - The effective source plan used by the harvester:
    - `youtube_categories`
    - `subreddits`
    - `youtube_queries`

Each `TopicResult` now also includes:

- `channel_scores`
  - Final per-channel ranking scores after combining trend strength, channel fit, freshness, diversity, novelty, and actionability.
- `channel_reasons`
  - Per-channel scoring reasons for review/debug.

## Dashburg Changes

### 1. Use `channels_used` as the source of truth

Do not build the channel list from a static UI constant.

Instead:

- read `channels_used` from the run results response,
- render channels in that order or sort by `display_name`,
- use `display_name` as the user-facing label,
- use `slug` or `repo_slug` for stable keys.

### 2. Increase per-channel display capacity

Trend Harvester now returns up to 5 items per channel in `top_per_channel`.

Dashburg should:

- stop assuming `top_per_channel[channel]` contains only 2 rows,
- render all returned items or allow collapse/expand,
- optionally default to showing the first 3 and reveal the rest on demand.

### 3. Prefer `channel_scores` over raw `channels`

Use:

- `channel_scores[channel]` for ordering within a channel,
- `channels[channel]` as the normalized fit/confidence value,
- `channel_reasons[channel]` for expandable explanations.

Recommended display:

- primary badge: final `channel_scores[channel]`
- secondary badge: fit/confidence from `channels[channel]`
- explanation drawer: render `channel_reasons[channel]`

### 4. Surface diagnostics

Dashburg should add lightweight diagnostics:

- `empty_channels`
- `fetch_plan`
- `channel_fit_counts`
- `top_by_source`

This will make it obvious when a run had poor coverage for a channel, or when a fetch plan was too narrow.

### 5. Preserve backward compatibility

If Dashburg talks to an older Trend Harvester instance:

- fall back to existing `top_per_channel` and `channels`,
- treat missing `channels_used` as an older server,
- use the old static channel list only as a final fallback.

## Suggested UI Wiring

For a run results screen:

1. Load `channels_used`.
2. Build the channel tabs/sections from that list.
3. For each channel section:
   - show `top_per_channel[channel.display_name]`
   - sort by `channel_scores[channel.display_name]` if the client reorders
   - show score explanation from `channel_reasons[channel.display_name]`
4. Show `empty_channels` in a diagnostics panel instead of silently omitting them.
5. Show `fetch_plan` in a debug/info panel for operator review.

## Notes

- The channel registry now lives inside this repo and is merged with monitor/repo discovery.
- Dashburg does not need to duplicate that registry logic; it should consume the API output.
- If Dashburg wants to show repo affinity, use `repo_slug` from `channels_used`.
