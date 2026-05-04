# Topic / Trend Harvester Backend

Local-first FastAPI backend that runs trend harvest jobs, stores data in local SQLite, scores and deduplicates topics from YouTube + Google Trends + Reddit, runs local LLM analysis, and exposes REST APIs for interactive research workflows.

## Features

- On-demand harvest runs (`QUEUED`/`RUNNING`/`SUCCEEDED`/`FAILED` persisted in SQLite)
- Source connectors:
  - YouTube Data API v3 (`videos.list`, most popular, by category)
  - Google Trends daily trending RSS (US/default region)
  - Reddit top-of-day from configured subreddits
- Merge + dedupe:
  - normalized-title key
  - fuzzy similarity via `rapidfuzz`
  - URL match dedupe
- Transparent scoring with `reasons_json` per topic instance
- Local LLM analysis (Ollama-compatible endpoint):
  - short summary
  - channel relevance probabilities
  - 2-3 hook ideas
- Focus-aware runs:
  - accepts `focus_query` (aliases: `query`, `topic`, `trend_query`)
  - filters low-signal/noise candidates
  - optional top-N LLM re-grading for actionable video/blog/app ideas
- Actions CRUD: `like|maybe|skip|used|blacklist` + notes
- Topic Factory export payload endpoint
- Idea Factory export v2 payload (`idea_factory_v2` / `topic_factory_v2`)
- Strategy artifacts in run results:
  - quick deterministic `idea_candidates`/`idea_groups`/`big_calls`
  - background multi-phase LLM upgrade with `strategy_status`
- Lightweight SQL migration runner
- Tests for scoring, dedupe, and connector parsing

## Stack

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy + SQLite
- Pydantic v2
- httpx
- rapidfuzz

## Project Layout

- `trend_harvester/main.py` app entry
- `trend_harvester/api/routes.py` API routes
- `trend_harvester/models.py` ORM models
- `trend_harvester/migrations/sql/001_initial.sql` migration
- `trend_harvester/services/*` connectors, scoring, dedupe, LLM, pipeline
- `docs/DASHBURG_INTEGRATION.md` Dashburg integration contract
- `tests/*` unit tests

## Environment Variables

Copy `.env.example` to `.env` and set values:

- `DATABASE_URL` (default local SQLite file)
- `YOUTUBE_API_KEY` (required for YouTube connector)
- `OLLAMA_BASE_URL` + `OLLAMA_MODEL` (required for LLM analysis)
- `OLLAMA_BASE_URLS` (optional comma-separated list for multi-server load distribution, e.g. `http://localhost:11434,http://192.168.1.176:11436`)
- `LLM_MAX_PARALLEL`, `LLM_NUM_PREDICT`, `LLM_TIMEOUT_SECONDS` (use these to tune slow local models)
- `ENABLE_SOURCE_CACHE` (default false; keeps repeated runs from returning cached source snapshots)
- `NOVELTY_*_PENALTY` (rerank repeated/used/skipped/blacklisted topics lower)
- `REDDIT_USER_AGENT` (used for public Reddit JSON scraping; no client id/secret required)
- limits/retries/cache settings

Secrets are read from env and never returned in API responses.

## How To Run Locally

1. Install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

2. Configure env:

```bash
cp .env.example .env
# edit .env
```

3. Run migrations:

```bash
trend-harvester migrate
```

4. Start API server:

```bash
uvicorn trend_harvester.main:app --host 0.0.0.0 --port 8400 --reload
```

5. Optional CLI run:

```bash
trend-harvester run --size small --region US
```

## API Endpoints

- `POST /api/runs/start`
- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/results?limit=25`
- `GET /api/topics/{topic_id}`
- `POST /api/topics/{topic_id}/action`
- `GET /api/actions?filter=like&since=...`
- `POST /api/export`
- `POST /api/config/validate`

## 5 curl Examples

1. Start run

```bash
curl -X POST http://localhost:8400/api/runs/start \
  -H 'Content-Type: application/json' \
  -d '{
    "sources": {"youtube": {"enabled": true}, "trends": {"enabled": true}, "reddit": {"enabled": true}},
    "limits": {"size": "small"},
    "categories": ["Sports"],
    "subreddits": ["soccer", "PremierLeague", "FantasyPL", "footballhighlights"],
    "region": "US",
    "focus_query": "english premier league",
    "objective": "video_blog_app_ideas",
    "llm_rerank_top_n": 50,
    "min_focus_relevance": 0.2
  }'
```

2. List runs

```bash
curl http://localhost:8400/api/runs
```

3. Get run results

```bash
curl "http://localhost:8400/api/runs/<RUN_ID>/results?limit=25"
```

4. Mark topic action

```bash
curl -X POST http://localhost:8400/api/topics/<TOPIC_ID>/action \
  -H 'Content-Type: application/json' \
  -d '{"action":"like","note":"Strong hook potential for BiteSizedKnowledge"}'
```

5. Export selected topics

```bash
curl -X POST http://localhost:8400/api/export \
  -H 'Content-Type: application/json' \
  -d '{"topic_ids":["<TOPIC_ID_1>","<TOPIC_ID_2>"],"format":"idea_factory_v2","run_id":"<RUN_ID>"}'
```

## Testing

```bash
pytest -q
```

## Notes

- Runs are idempotent for matching active payloads (`request_hash` check).
- External fetches use retries + exponential backoff.
- Raw source JSON is truncated when oversized before persistence.
- Hard caps are enforced on per-source limits.
