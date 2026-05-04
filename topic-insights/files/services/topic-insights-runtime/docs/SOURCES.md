# Sources & Signals

## Reddit
- Search: `https://www.reddit.com/search.json`
- Comments: `https://www.reddit.com/comments/{id}.json` (best-effort flattening)

## Web Search
- Provider chain with fallback:
  - DuckDuckGo (no key) → SerpAPI → DataForSEO → none
- Optional page fetch + text extraction (BeautifulSoup)

## YouTube
- Video discovery (no key): `youtubesearchpython`
- **Comments (requires key)**: YouTube Data API `commentThreads`
  - Set `YOUTUBE_API_KEY` in `.env`

## Competition scan (best effort)
For each cluster label, OIE queries:
- "{cluster_label} app"
- "best {cluster_label} app"

Signals include:
- unique domain count
- review/alternatives/VS saturation
- app store presence
