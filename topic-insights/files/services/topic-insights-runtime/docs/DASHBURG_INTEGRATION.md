# Dashburg Integration (Topic/OIE on .216)

Base URL:

- `http://127.0.0.1:8080`

CORS is enabled for:

- `http://127.0.0.1`
- `http://dashburg.local`
- `http://localhost:5173`
- regex: `http://(localhost|127.0.0.1|127.0.0.1)(:port)?`

## Health

```bash
curl -s http://127.0.0.1:8080/api/v1/health
```

## Trending / clusters / ideas / pains

```bash
curl -s "http://127.0.0.1:8080/api/v1/topics/trending?limit=20"
curl -s "http://127.0.0.1:8080/api/v1/clusters?limit=50"
curl -s "http://127.0.0.1:8080/api/v1/clusters/<cluster_id>"
curl -s "http://127.0.0.1:8080/api/v1/ideas?limit=100"
curl -s "http://127.0.0.1:8080/api/v1/ideas/<idea_id>"
curl -s "http://127.0.0.1:8080/api/v1/pains?topic=auto&limit=200"
```

## Start runs (non-blocking)

Targeted run:

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/runs/targeted \
  -H 'content-type: application/json' \
  -d '{"query":"job application ghosting","topic":"jobs","limit":30,"enable_youtube":false}'
```

Auto run:

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/runs/auto \
  -H 'content-type: application/json' \
  -d '{"ideas_per_run":5,"target_topics":10,"limit_per_topic":20}'
```

Poll status:

```bash
curl -s "http://127.0.0.1:8080/api/v1/runs?limit=50"
curl -s "http://127.0.0.1:8080/api/v1/runs/<run_id>"
```

Dashburg-compat aliases:

```bash
curl -s -X POST http://127.0.0.1:8080/api/runs/start \
  -H 'content-type: application/json' \
  -d '{"query":"job application ghosting","topic":"jobs","limit":30,"sources":{"youtube":true,"google_trends":true,"reddit":true,"x_trends":true},"sources_config":{"x_trends":{"enabled":true,"max_items":20,"use_auth":false}}}'

curl -s "http://127.0.0.1:8080/api/runs/<run_id>"
curl -s "http://127.0.0.1:8080/api/runs/<run_id>/results?limit=25"
```

Notes:
- New source key: `x_trends` (persisted as source `"x"` in result/source badges).
- X connector is optional and soft-failing; run continues if X extraction fails.
- `totals_json.source_warnings` includes partial-source warnings for UI banners.
- `source_details.x` may include `rank`, `category`, and `post_count_text`.
- If a topic only has source `"x"`, UI may mark it as `Emerging on X`.

Planned fallback (not implemented yet):
- Add fallback to Dashburg WebAgent Playwright when local X Playwright extraction fails.
- Expected flow: `start_session` -> `goto` (`/explore/tabs/trending`) -> `wait_for_selector` -> `extract` -> normalize to existing `x` candidate shape.
- Keep constraints unchanged: X remains optional, signal-only, and soft-failing.

## Provider stats / logs

```bash
curl -s "http://127.0.0.1:8080/api/v1/providers/stats?limit=200"
curl -s "http://127.0.0.1:8080/api/v1/logs/tail?offset=0&max_lines=200"
```

## AppGen JSON

```bash
curl -s "http://127.0.0.1:8080/api/v1/appgen/ideas?sort=overall_score_desc"
curl -s "http://127.0.0.1:8080/api/v1/appgen/ideas/<idea_id>"
curl -s "http://127.0.0.1:8080/api/v1/appgen/runs?limit=50"
curl -s "http://127.0.0.1:8080/api/v1/appgen/outbox?limit=200"
curl -s -X POST "http://127.0.0.1:8080/api/v1/appgen/ideas/<idea_id>/export"
```

## Web Search Fallback Behavior

Provider chain is configurable using:

- `WEB_SEARCH_PROVIDER=auto`
- `WEB_SEARCH_FALLBACKS=ddg,serpapi,dataforseo,none`

If DDG is ratelimited, pipeline retries with backoff+jitter and then falls back to SerpAPI/DataForSEO if credentials exist. If all providers fail, web search returns `[]` and pipeline continues.

## LLM Controls

- `LLM_PROVIDER=ollama|openai`
- `LLM_FALLBACK_PROVIDER=openai|ollama`
- `LLM_MAX_CALLS_PER_RUN=40`
- `LLM_CACHE_TTL_SECONDS=604800`
- `OLLAMA_NUM_CTX=131072`
- `OLLAMA_NUM_PREDICT=4096`
- `OLLAMA_TEMPERATURE=0.2`

Local-first mode works with Ollama (`qwen3:14b`) without external keys.

## X Connector Env

```bash
ENABLE_X_TRENDS=false
X_TRENDS_URL=https://x.com/explore/tabs/trending
X_TRENDS_FALLBACK_URL=https://x.com/explore
X_TRENDS_MAX_ITEMS=20
X_TRENDS_TIMEOUT_MS=10000
X_TRENDS_NAV_TIMEOUT_MS=15000
X_TRENDS_USE_AUTH=false
X_TRENDS_STORAGE_STATE_PATH=./secrets/x_storage_state.json
X_TRENDS_LOCALE=en-US
X_TRENDS_REGION_HINT=US
X_TRENDS_DEBUG=false
```
