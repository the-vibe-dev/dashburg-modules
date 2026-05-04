# Troubleshooting

## DuckDuckGo rate limits
Symptoms:
- Logs show `duckduckgo_search.exceptions.RatelimitException`
- Web search returns 0 results

Mitigations:
- The pipeline now backs off with jitter and will continue using other sources.
- Caching reduces repeated DDG hits and helps avoid rate limits.
- Set a cooldown to reduce repeated DDG hits:
  - `WEB_SEARCH_COOLDOWN_SECONDS=60`
- Switch providers:
  - `WEB_SEARCH_PROVIDER=serpapi`
  - `SERPAPI_API_KEY=...`
- Or set a fallback chain:
  - `WEB_SEARCH_PROVIDER=auto`
  - `WEB_SEARCH_FALLBACKS=ddg,serpapi,dataforseo,none`
- Disable web search (reddit-only ingestion):
  - `WEB_SEARCH_ENABLED=false`

## SERPAPI setup
1. Create an API key at SerpAPI.
2. Add to `.env`:
   - `WEB_SEARCH_PROVIDER=serpapi`
   - `SERPAPI_API_KEY=...`

## Why RawPost > 0 but Ideas == 0?
Common causes:
- LLM misconfiguration (no OpenAI key and Ollama unreachable)
- Extraction produced 0 pains from the collected posts
- Clustering yielded no clusters (e.g., too few pains)

What to check:
- `/debug` page shows stage events and statuses.
- `data/run.log` shows stage counts and provider errors.
- Ensure LLM is configured:
  - `LLM_PROVIDER=openai` + `OPENAI_API_KEY`, or `LLM_PROVIDER=ollama` + `OLLAMA_BASE_URL`

## No-data report
If ingestion yields 0 posts, the report still renders with a “Run Notes” section explaining why.

## DataForSEO setup
1. Create DataForSEO credentials.
2. Add to `.env`:
   - `DATAFORSEO_LOGIN=...`
   - `DATAFORSEO_PASSWORD=...`
