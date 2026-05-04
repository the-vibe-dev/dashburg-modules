# Trend Harvester Improvement Plan

## Goal

Improve this repo so it:

1. discovers the full channel inventory used by Dashburg,
2. harvests a broader set of relevant trend candidates,
3. ranks topics more accurately against channel fit,
4. returns results that are easier to review and trust.

## Current Issues Observed

### 1. Channel discovery is incomplete

`trend_harvester/services/channels.py` currently loads channels from:

- `TREND_CHANNELS_CSV`
- `../monitor/status/*.json`
- a hard-coded `DEFAULT_CHANNELS` fallback

Problems:

- `../monitor/status` is not a complete source of truth for all channels/repo variants.
- The loader reads only one narrow filesystem shape and does not reuse Dashburg's broader discovery model.
- Channel profiles are partly hard-coded via `_SLUG_PROFILE_HINTS`, which will not scale as channels change.
- Dashburg appears to have a wider repo/channel ecosystem than the 16 hard-coded defaults and the current monitor-title extraction.

Impact:

- Some channels never appear in `top_per_channel`.
- LLM prompts omit channels that should be considered.
- Ranking quality is capped because missing channels cannot be scored.

### 2. Topic harvesting breadth is narrow

Current connectors:

- YouTube most-popular by category
- Google Trends RSS
- Reddit top-of-day from configured subreddits

Problems:

- YouTube only uses broad category pulls, which misses niche/topic-specific velocity.
- Google Trends RSS is a thin signal and does not provide enough expansion around each trend.
- Reddit is limited by a static subreddit list and does not adapt by channel/domain.
- There is no query expansion per channel profile, topic cluster, or recent successful topics.

Impact:

- The system finds obvious broad trends but misses many usable channel-specific topics.
- Results skew toward generic viral topics rather than topics that match actual channels.

### 3. Ranking is too shallow and too global

Current ranking is mainly:

- per-instance source score in `trend_harvester/services/scoring.py`
- cluster sum across instances
- optional focus rerank
- LLM channel tags merged into `top_per_channel`

Problems:

- Scoring mostly rewards raw popularity, not freshness, velocity context, channel fit strength, novelty, or evidence quality.
- `top_per_channel` uses a fixed confidence threshold (`0.45`) and keeps only top 2 items, which hides potentially good matches.
- Channel fit is mostly LLM-only or title/profile similarity fallback, with little structured feature support.
- No explicit per-channel ranking formula combines relevance, novelty, source diversity, and production usefulness.

Impact:

- Broad mainstream topics can outrank more actionable channel-specific ideas.
- Good matches are hidden if they are not in the top 2 or if the LLM under-scores them.

### 4. Output and observability are not sufficient for tuning

Problems:

- The API does not expose enough debugging detail for why one topic won for one channel.
- There is no evaluation dataset or regression harness for channel-fit quality.
- Tests cover connector parsing and basic scoring, but not channel discovery, ranking behavior, or result quality.

Impact:

- Improvements will be guesswork unless ranking changes are measurable.

## Proposed Plan

## Phase 1: Establish a real channel source of truth

### Work

- Replace the current one-path discovery approach in `trend_harvester/services/channels.py` with a layered channel registry.
- Add a dedicated channel discovery service that can merge:
  - explicit env overrides,
  - monitor status files,
  - repo metadata from `/home/trilobyte/ai/*`,
  - optional shared export from Dashburg if available.
- Define a canonical channel record structure:
  - `slug`
  - `display_name`
  - `profile`
  - `platform_links`
  - `repo_path`
  - `status_source`
  - `enabled`
- Move hard-coded profile hints into a versioned data file such as `trend_harvester/data/channel_registry.json` or `channels.yaml`.
- Add normalization so channel names stay stable even if monitor labels differ from display names.

### Why

This is the prerequisite for all ranking work. If the channel list is incomplete, every later scoring step is wrong.

### Deliverables

- New channel registry loader
- Canonical channel/profile data file
- Tests proving all expected channels are discovered

## Phase 2: Expand candidate harvesting beyond broad feeds

### Work

- Add profile-driven harvesting:
  - derive seed keywords from each channel profile,
  - map channels to preferred YouTube categories and subreddit groups,
  - optionally support per-channel fetch packs.
- Expand YouTube harvesting to include:
  - keyword search runs for channel-profile queries,
  - recency-aware pulls,
  - topic/category combinations instead of category-only pulls.
- Expand trend harvesting with follow-on enrichment:
  - for each Google trend, run related-source collection on YouTube/Reddit,
  - keep source provenance so expansions remain explainable.
- Improve Reddit harvesting:
  - subreddit pools by channel/domain,
  - optional discovery list for emerging subreddits,
  - stronger freshness filters.
- Add a run strategy mode:
  - `broad`
  - `channel_balanced`
  - `channel_targeted`

### Why

The current pipeline is broad but shallow. More usable topics will come from targeted enrichment around channel themes.

### Deliverables

- Expanded fetch planner
- Channel-aware source presets
- Tests for query generation and connector aggregation

## Phase 3: Build a better ranking model

### Work

- Split ranking into two layers:
  - `trend_strength_score`
  - `channel_fit_score`
- Keep source scoring, but add structured features such as:
  - freshness decay
  - engagement velocity proxy
  - cross-source corroboration
  - source diversity
  - repeated-topic penalty
  - prior action penalty
  - exact/semantic overlap with channel profile
  - educational/news/history/devotional/etc. content-type match
- Compute a final per-channel score:
  - `final_channel_score = trend_strength + channel_fit + novelty + actionability`
- Store per-channel reasoning so review UI can explain rankings.
- Replace the fixed `0.45` threshold with adaptive ranking:
  - keep top N per channel,
  - require a minimum score floor,
  - expose more than 2 items to the API, with UI choosing display count.
- Use LLM output as one signal, not the only signal:
  - blend LLM fit with deterministic profile similarity and source/topic features.

### Why

A topic should rank highly for a channel because it is both trending and suitable for that channel, not just because it is globally popular.

### Deliverables

- New ranking module or refactor of `services/scoring.py` + route ranking logic
- Per-channel score breakdowns
- Regression tests for ranking order

## Phase 4: Improve dedupe and topic quality

### Work

- Strengthen clustering so related topics merge even when titles differ significantly.
- Add entity extraction or lightweight keyword extraction before clustering.
- Separate near-duplicate stories from distinct angles on the same event.
- Track topic families and sub-angles:
  - main event
  - explainer angle
  - reaction angle
  - channel-specific framing

### Why

Right now, broad normalization can still miss better grouping, which hurts score aggregation and channel-specific ranking.

### Deliverables

- Improved clustering heuristics
- Tests for merge/no-merge behavior on realistic title variants

## Phase 5: Expose review-grade output for Dashburg

### Work

- Extend API response payloads to include:
  - complete channel inventory used for the run,
  - per-topic per-channel score breakdown,
  - why a topic matched a channel,
  - harvest provenance and fetch query used,
  - more than top 2 candidates per channel.
- Add channel coverage diagnostics:
  - channels with zero candidates,
  - channels with low-confidence candidates only,
  - channels excluded from the run and why.
- Add run summary stats:
  - candidates by source
  - candidates by channel-targeting strategy
  - dropped by dedupe
  - dropped by relevance floor

### Why

The review workflow needs visibility into why topics were selected and why some channels have empty results.

### Deliverables

- Updated API schema
- Updated integration doc

## Phase 6: Add evaluation and tuning infrastructure

### Work

- Create a small gold dataset of:
  - known good topics for specific channels,
  - known bad matches,
  - expected ranking order examples.
- Add tests for:
  - channel discovery completeness,
  - per-channel ranking stability,
  - novelty penalties,
  - focus rerank interaction,
  - API response completeness.
- Add a local evaluation script that compares scoring changes before/after.
- Log run metrics that support tuning:
  - average candidates per channel
  - coverage percentage
  - top-score distribution
  - number of empty channels

### Why

Without an evaluation loop, ranking work will drift and regress.

### Deliverables

- Evaluation fixtures
- Ranking regression tests
- Tuning script

## Suggested Implementation Order

1. Fix channel discovery and create a canonical registry.
2. Update LLM prompts and channel-fit logic to use the canonical registry.
3. Expand harvesting with profile-driven query generation.
4. Refactor ranking into trend-strength plus channel-fit scoring.
5. Expose better review/debug data in API responses.
6. Add evaluation fixtures and regression tests.

## Concrete File-Level Targets

- `trend_harvester/services/channels.py`
  - replace current ad hoc discovery with registry-based loading
- `trend_harvester/services/llm.py`
  - consume canonical channel metadata and blend deterministic + LLM channel fit
- `trend_harvester/services/scoring.py`
  - expand feature set and separate trend strength from channel fit
- `trend_harvester/services/harvester.py`
  - add channel-aware fetch planning and richer progress/accounting
- `trend_harvester/api/routes.py`
  - return more channel/ranking diagnostics and more complete per-channel results
- `tests/test_scoring.py`
  - extend for new ranking rules
- `tests/`
  - add channel discovery and result ranking tests

## Success Criteria

- All expected channels from the broader Dashburg ecosystem appear in the run output.
- Each channel gets a larger candidate pool, not just one or two accidental matches.
- Top results show visibly better fit to the intended channel themes.
- Broad viral stories no longer dominate every channel unless they genuinely fit.
- API responses are detailed enough to explain ranking decisions during review.
- Ranking changes are covered by reproducible tests and evaluation fixtures.

## Recommended First Milestone

Implement Phase 1 only:

- build canonical channel discovery,
- add tests for completeness,
- update API to expose the channel list used in a run.

That milestone will solve the current “not all channels are shown” issue and create the foundation for better harvesting and ranking.
