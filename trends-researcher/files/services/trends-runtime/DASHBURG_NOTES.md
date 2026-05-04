# Dashburg Notes: Channel Ranking Refresh

## Summary
- Per-topic channel output now includes a filtered `channel_rankings` array.
- `channel_rankings` only includes channels with `relevance_pct > 0`, sorted descending by relevance, capped at 4 items.
- If a trend has no relevant channels, Dashburg should render no per-channel badges or chips for that trend.

## Response Shape
- Existing fields stay in place: `channels`, `channel_scores`, `channel_reasons`, `top_per_channel`, `channels_used`.
- `channels` is now filtered to the same relevant channels returned in `channel_rankings`.
- New optional field on each topic item:

```json
{
  "channel_rankings": [
    {
      "channel": "Stateside Now",
      "channel_slug": "stateside-now",
      "channel_title": "Stateside Now",
      "relevance_pct": 78,
      "score": 64.2,
      "metadata_source": "youtube",
      "ranking_debug": {
        "gated": false,
        "reason": "matched",
        "overlap_terms": ["policy", "election"]
      }
    }
  ]
}
```

## UI Expectations
- Prefer `channel_rankings` for rendering per-topic channel badges.
- Show nothing when `channel_rankings` is empty.
- Use `relevance_pct` as the visible fit percent.
- Use `score` only as a secondary ranking value or tooltip.
- `top_per_channel` is also filtered by the same relevance gate, so empty channels are expected when no topic passes.

## Debug Output
- Debug is off by default.
- Enable per request with `GET /api/runs/{run_id}/results?include_ranking_debug=true`.
- Or set `CHANNEL_RANKING_DEBUG_DEFAULT=true` in `.env`.

## Channel Metadata
- Ranking now prefers cached YouTube channel metadata:
  - `channel_title`
  - `channel_description`
- Fallback stays the local registry profile when YouTube fetch is unavailable or the channel has no configured `youtube_channel_id`.
- Current registry entries do not yet include `youtube_channel_id`, so fallback behavior remains active until IDs are added.

## Env / Ops
- `.env` should live at the repo root: [`.env`](/home/trilobyte/ai/trends/.env)
- Required for YouTube metadata refresh: `YOUTUBE_API_KEY`
- Optional tuning:
  - `CHANNEL_METADATA_TTL_DAYS=7`
  - `CHANNEL_RANKING_MIN_OVERLAP=1`
  - `CHANNEL_RANKING_MIN_RELEVANCE_PCT=1`
  - `CHANNEL_RANKING_DEBUG_DEFAULT=false`

## Migration / Refresh
- New DB table: `channel_metadata`
- Apply migrations before deploy:

```bash
trend-harvester migrate
```

- Refresh cached channel metadata manually:

```bash
trend-harvester refresh-channel-metadata --force
```

## Rollout
1. Deploy backend with the migration.
2. Set `YOUTUBE_API_KEY` in the backend `.env`.
3. Run `trend-harvester refresh-channel-metadata --force` after channel IDs are added to the registry.
4. Update Dashburg to render `channel_rankings` and hide channel UI when the array is empty.

## Changelog
- Changed per-topic channel output to exclude ungated channels, cap visible rankings at 4, and add deterministic overlap-based relevance filtering to prevent nonsense matches.

## 2026-03 Strategy Pass Upgrade (Quick -> Multi-Phase)

### What changed
- Run results now return immediate quick strategy artifacts and then transparently upgrade them via a background multi-phase LLM pass.
- New result fields:
  - `idea_candidates`
  - `idea_groups`
  - `big_calls`
  - `score_breakdowns`
  - `evidence_links`
  - `recommended_next_actions`
  - `strategy_status`

### Lifecycle
1. `GET /api/runs/{run_id}/results` returns quick artifacts immediately.
2. Backend schedules `strategy_v2` for succeeded runs (if not already done).
3. While background pass runs, `strategy_status.status` is `queued` or `running`.
4. When complete, `strategy_status.status=succeeded` and response artifacts are served from the LLM output.
5. If LLM pass fails, quick artifacts remain usable and `strategy_status.status=failed`.

### Key implementation files
- Scheduler + state persistence:
  - `/home/trilobyte/ai/trends/trend_harvester/api/routes.py`
- Multi-phase LLM orchestration (Interpreter/Generator/Grouping/Big Calls):
  - `/home/trilobyte/ai/trends/trend_harvester/services/strategy_pass.py`
- Shared LLM strict-JSON helper:
  - `/home/trilobyte/ai/trends/trend_harvester/services/llm.py`

### Dashburg frontend behavior
- Trends page shows explicit strategy status banner.
- Auto-refetches results while strategy pass is `queued|running`.
- Big Calls/Ideas/Groups tabs read the same response fields; no endpoint switch required.
