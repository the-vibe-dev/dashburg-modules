# Opportunity Intelligence Engine (OIE)

A working, end-to-end app that scans public sources (Reddit, Web search results, optional YouTube, optional X trends), extracts pain points, clusters them, scores opportunities, and generates ranked micro‑SaaS ideas with MVP scopes and reports.

## What you get
- **CLI**: run scans, extract pains, cluster, score, generate ideas, export reports
- **API**: FastAPI endpoints for scans/ideas/reports
- **Web UI**: lightweight dashboard (FastAPI + Jinja) to browse ranked clusters & ideas
- **SQLite DB** (SQLModel)
- **Configurable scoring** via `scoring_config.yaml`
- **LLM providers**:
  - OpenAI (requires `OPENAI_API_KEY`)
  - Ollama (local; defaults to `http://localhost:11434`)
- **Web search providers with fallback**:
  - DuckDuckGo (no key) → SerpAPI → DataForSEO → none

> No real keys included. A full `.env.example` is provided.

---

## Quickstart (local dev)

### 1) Create venv and install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# Optional browser install for X trends Playwright connector
python -m playwright install chromium
```

### 2) Configure env
```bash
cp .env.example .env
# edit .env and set at least one LLM provider:
# - OPENAI_API_KEY=...
#   OR
# - OLLAMA_BASE_URL=http://localhost:11434
```

If using Ollama, make sure models exist, e.g.:
```bash
ollama pull qwen3:14b
ollama pull nomic-embed-text
```

### 3) Initialize database
```bash
python -m apps.cli.main db-init --reset
```

### 4) Run a scan + idea generation (Reddit + web + Reddit comments + competition scan)
```bash
python -m apps.cli.main run \
  --query "gardening watering schedule" \
  --topic "gardening" \
  --limit 40
```

This will:
- ingest posts
- extract structured pain points
- cluster
- score
- generate ideas
- export `reports/latest_report.html`

### 5) Start API + Web UI
```bash
uvicorn apps.api.main:app --host 0.0.0.0 --port 8080
```
Open: http://localhost:8080

### 6) Run with X trends enabled
```bash
python -m apps.cli.main run \
  --query "sports chatter" \
  --topic "sports" \
  --limit 40 \
  --enable-x-trends
```

---

## Docker (deployment)

### Build & run
```bash
docker build -t oie .
docker run --rm -p 8080:8080 --env-file .env -v $(pwd)/data:/app/data oie
```

### docker-compose
```bash
docker compose up --build
```

---

## Notes on sources
- **Reddit**: uses public `reddit.com/search.json` (no auth) with safe headers & backoff.
- **Reddit comments**: fetched for the top posts by engagement (score + comments) up to `REDDIT_MAX_COMMENT_POSTS`.
- **Web**: uses a provider chain with caching and fallbacks (DDG → SerpAPI → DataForSEO → none).
- **YouTube**: optional via `youtubesearchpython` (scrapes search). Enable with `--enable-youtube`.
  - If `YOUTUBE_API_KEY` is set, search uses the official API.
  - Comments are fetched per video up to `YOUTUBE_MAX_COMMENTS_PER_VIDEO`.
- **X trends**: optional via Playwright (`/explore/tabs/trending`, fallback `/explore`).
  - Signal-only collection (trend labels + metadata); no timeline/post scraping.
  - Optional auth state (`X_TRENDS_USE_AUTH=true` + `X_TRENDS_STORAGE_STATE_PATH`).
  - Soft-fail by design: connector warnings do not abort a run.
  - Planned fallback (not implemented yet): use Dashburg WebAgent Playwright session/actions when local Playwright extraction fails.

Some sources can break due to upstream changes. The pipeline is designed so sources are modular: if one fails, the scan still completes.

---

## Repo layout
- `apps/cli` – Typer CLI
- `apps/api` – FastAPI API + web UI routes
- `connectors/` – optional source connectors (X trends via Playwright)
- `ingestion/` – source connectors
- `extraction/` – pain extraction + classifiers
- `clustering/` – clustering implementations
- `scoring/` – scoring math + ranker
- `idea_generation/` – idea + MVP scope generation
- `reports/` – HTML/JSON renderers
- `storage/` – DB models/repository

---

## License
MIT for internal use; adjust as needed.


## Auto discovery mode
From the web UI, click **Auto Scan** to:
- discover top pain topics across sources
- run focused scans per topic
- generate **~5 app ideas per run**

CLI (advanced):
- Currently exposed via web UI `/auto-run`.


> Note: After upgrading versions that add DB columns, run `db-init --reset` once.

## Web search providers
Configure in `.env`:
- `WEB_SEARCH_PROVIDER=auto`
- `WEB_SEARCH_FALLBACKS=ddg,serpapi,dataforseo,none`
- `SERPAPI_API_KEY=...`
- `DATAFORSEO_LOGIN=...`
- `DATAFORSEO_PASSWORD=...`

## LLM routing
Configure in `.env`:
- `LLM_PROVIDER=ollama` or `openai`
- `LLM_FALLBACK_PROVIDER=openai` (or `ollama`)
- `OLLAMA_MODEL=qwen3:14b`
- `OPENAI_MODEL_PRIMARY=gpt-4o-mini`
- `OPENAI_MODEL_EVAL=gpt-4o-mini`

## Caching + concurrency
- Web search and LLM responses are cached to reduce rate limiting.
- Tune concurrency limits:
  - `WEB_MAX_CONCURRENCY`, `REDDIT_MAX_CONCURRENCY`, `YOUTUBE_MAX_CONCURRENCY`
  - `LLM_LOCAL_MAX_CONCURRENCY`, `LLM_OPENAI_MAX_CONCURRENCY`

## Debugging
- Web UI: `/debug`
- CLI: `python -m apps.cli.main diagnose`

## Dashburg Integration
- AppGen API and SSE integration guide: `docs/DASHBURG_INTEGRATION.md`
- AppGen UI pages:
  - `/appgen/ideas`
  - `/appgen/runs`
  - `/appgen/settings`


- DB-only generation guide: `docs/TOP_FROM_DB.md`


## Dashburg API

- Versioned API root: `/api/v1`
- Integration guide: `docs/DASHBURG_INTEGRATION.md`
- Health check: `/api/v1/health`
