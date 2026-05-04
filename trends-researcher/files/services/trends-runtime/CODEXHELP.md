# Dashburg API Input Update Prompt

Use this prompt in Dashburg/Codex to implement the trend request update.

## Copy-Paste Prompt

You are updating Dashburg trend-run request construction for the Trend Harvester API.

Goal:
- Support both:
  - broad top trending stories (no focus query), and
  - niche-specific actionable trends (with focus query)
- Send the correct optional focus-aware fields to `/api/runs/start`.

Implement these requirements exactly:

1. Focus fields are optional
- `query` is optional (maps to backend `focus_query` alias).
- When `query` is present, also send:
  - `objective` (default: `video_blog_app_ideas`)
  - `llm_rerank_top_n` (default: `50`)
  - `min_focus_relevance` (default: `0.2`, range `0..1`)
- When `query` is empty/missing, omit focus-only fields or send safe defaults.

2. Two run modes in UI
- `Top Trends` mode:
  - no `query`
  - broad categories/subreddits allowed
- `Focused Trends` mode:
  - include `query`
  - narrow source shaping by niche

3. Source shaping for sports/EPL requests (Focused mode)
- If intent includes EPL / English Premier League / football league ideas:
  - `categories`: `['Sports']`
  - `subreddits`: `['soccer', 'PremierLeague', 'FantasyPL', 'footballhighlights']`
- Avoid broad noise subreddits like `worldnews`, `news`, `todayilearned` in focused mode.

4. Keep limits explicit
- Provide `limits.size` and per-source limits.
- Example focused defaults:
  - `youtube: 200`
  - `reddit: 120`
  - `trends: 50`

5. UI behavior
- `Focus Query` should be optional.
- Add a mode toggle (`Top Trends` vs `Focused Trends`).
- Persist last used query, but do not block run start when empty.

6. API compatibility
- Send `query` key for focused mode; backend maps it to `focus_query`.
- Keep existing keys (`sources`, `limits`, `categories`, `subreddits`, `region`).

7. Observability
- Log outgoing payload (redact secrets).
- Show mode and query/objective (if present) in run details.

## Request Example A (Top Trends, no focus)

```json
{
  "sources": {
    "youtube": {"enabled": true, "limit": 200},
    "trends": {"enabled": true, "limit": 60},
    "reddit": {"enabled": true, "limit": 200}
  },
  "limits": {
    "size": "large",
    "youtube": 200,
    "reddit": 200,
    "trends": 60
  },
  "categories": ["News & Politics", "Entertainment", "Sports", "Gaming", "Science & Technology"],
  "subreddits": ["technology", "worldnews", "science", "gaming", "sports", "movies"],
  "region": "US"
}
```

## Request Example B (Focused EPL)

```json
{
  "sources": {
    "youtube": {"enabled": true, "limit": 200},
    "trends": {"enabled": true, "limit": 50},
    "reddit": {"enabled": true, "limit": 120}
  },
  "limits": {
    "size": "large",
    "youtube": 200,
    "reddit": 120,
    "trends": 50
  },
  "categories": ["Sports"],
  "subreddits": ["soccer", "PremierLeague", "FantasyPL", "footballhighlights"],
  "region": "US",
  "query": "english premier league",
  "objective": "video_blog_app_ideas",
  "llm_rerank_top_n": 50,
  "min_focus_relevance": 0.2
}
```

## Minimal Validation Rules (Dashburg)

- `query`: optional string.
- If `query` is present/non-empty:
  - `llm_rerank_top_n`: integer `0..100`
  - `min_focus_relevance`: float `0..1`
- `subreddits.length <= 20`.

## Acceptance Criteria

- Dashburg can start runs with or without `query`.
- `Top Trends` mode returns broad trending stories.
- `Focused Trends` mode returns niche-relevant results (e.g., EPL-specific when queried).
- Channel-fit and ranking improvements apply in focused mode.
