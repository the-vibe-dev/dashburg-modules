# Trend Harvester → Dashburg Integration Guide

## 1. Service Overview
The Trend Harvester service is a local-first backend that:
- pulls trends from YouTube Data API v3, Google Trends daily trending RSS, and Reddit top-of-day posts
- merges and deduplicates candidate topics
- scores each topic instance with transparent feature weights
- runs local LLM analysis (Ollama-compatible) for summary, channel relevance, and hook ideas
- exposes REST API endpoints for Dashburg consumption.

Result bundles include:
- Top 25 overall topics
- Top 2 topics per channel (based on LLM classification confidence)
- source metadata (source list, URLs, metrics)
- summary + hook ideas.

## 2. Backend Service Location
Configure Trend Harvester base URL in Dashburg environment.

Example:

`TREND_SERVICE_BASE_URL=http://127.0.0.1:8400`

Dashburg should reference this variable:

`DASHBURG_TRENDS_API_BASE_URL`

Recommended approach:

Option A (preferred):
Dashburg backend proxy route:
`/api/trends/*`

Option B:
Direct client calls to Trend Harvester.

## 3. API Endpoints

### POST /api/runs/start

method:
`POST`

route:
`/api/runs/start`

request schema:
```json
{
  "sources": {
    "youtube": {"enabled": true, "limit": 40},
    "trends": {"enabled": true, "limit": 20},
    "reddit": {"enabled": true, "limit": 40}
  },
  "limits": {
    "size": "small",
    "youtube": 40,
    "reddit": 40,
    "trends": 20
  },
  "categories": ["News & Politics", "Entertainment", "Sports", "Gaming"],
  "subreddits": ["technology", "worldnews", "todayilearned", "science"],
  "region": "US",
  "focus_query": "english premier league",
  "objective": "video_blog_app_ideas",
  "llm_rerank_top_n": 50,
  "min_focus_relevance": 0.2
}
```

response schema:
```json
{
  "run_id": "uuid"
}
```

example request:
```http
POST /api/runs/start
Content-Type: application/json

{
  "sources": {"youtube": {"enabled": true}, "trends": {"enabled": true}, "reddit": {"enabled": true}},
  "limits": {"size": "small"},
  "categories": ["Sports"],
  "subreddits": ["soccer", "PremierLeague", "FantasyPL", "footballhighlights"],
  "region": "US",
  "query": "english premier league",
  "objective": "video_blog_app_ideas",
  "llm_rerank_top_n": 50,
  "min_focus_relevance": 0.2
}
```

example response:
```json
{
  "run_id": "2fd082a4-0470-4ee5-a5b4-93fb37576f9f"
}
```

### GET /api/runs

method:
`GET`

route:
`/api/runs`

request schema:
No request body.

response schema:
```json
[
  {
    "id": "uuid",
    "status": "QUEUED|RUNNING|SUCCEEDED|FAILED",
    "started_at": "ISO-8601|null",
    "finished_at": "ISO-8601|null",
    "params_json": {},
    "totals_json": {},
    "error": "string|null"
  }
]
```

example request:
```http
GET /api/runs
```

example response:
```json
[
  {
    "id": "2fd082a4-0470-4ee5-a5b4-93fb37576f9f",
    "status": "SUCCEEDED",
    "started_at": "2026-03-04T14:22:13.214Z",
    "finished_at": "2026-03-04T14:22:33.019Z",
    "params_json": {"region": "US"},
    "totals_json": {"candidate_count": 87, "topic_count": 42, "instance_count": 59},
    "error": null
  }
]
```

### GET /api/runs/{run_id}

method:
`GET`

route:
`/api/runs/{run_id}`

request schema:
Path param `run_id` (UUID string).

response schema:
```json
{
  "id": "uuid",
  "status": "QUEUED|RUNNING|SUCCEEDED|FAILED",
  "started_at": "ISO-8601|null",
  "finished_at": "ISO-8601|null",
  "params_json": {},
  "totals_json": {},
  "error": "string|null"
}
```

example request:
```http
GET /api/runs/2fd082a4-0470-4ee5-a5b4-93fb37576f9f
```

example response:
```json
{
  "id": "2fd082a4-0470-4ee5-a5b4-93fb37576f9f",
  "status": "RUNNING",
  "started_at": "2026-03-04T14:22:13.214Z",
  "finished_at": null,
  "params_json": {"region": "US"},
  "totals_json": {},
  "error": null
}
```

### GET /api/runs/{run_id}/results

method:
`GET`

route:
`/api/runs/{run_id}/results?limit=25`

request schema:
- Path param `run_id` (UUID string)
- Query param `limit` (int, default 25)

response schema:
```json
{
  "run_id": "uuid",
  "status": "SUCCEEDED",
  "top_overall": [
    {
      "topic_id": "uuid",
      "title": "string",
      "score": 87.3,
      "sources": ["youtube", "reddit"],
      "summary": "string",
      "hooks": ["string", "string"],
      "channels": {
        "BiteSizedKnowledge": 0.82,
        "BrainWaveHistory": 0.12
      }
    }
  ],
  "top_per_channel": {
    "BiteSizedKnowledge": [
      {
        "topic_id": "uuid",
        "title": "string",
        "score": 87.3,
        "sources": ["youtube", "reddit"],
        "summary": "string",
        "hooks": ["string"],
        "channels": {"BiteSizedKnowledge": 0.82}
      }
    ]
  }
}
```

example request:
```http
GET /api/runs/2fd082a4-0470-4ee5-a5b4-93fb37576f9f/results?limit=25
```

example response:
```json
{
  "run_id": "2fd082a4-0470-4ee5-a5b4-93fb37576f9f",
  "status": "SUCCEEDED",
  "top_overall": [
    {
      "topic_id": "10eec8e8-12bb-4d12-95d9-c0e91fc8af4c",
      "title": "AI Reality Check: Are We Replacing Real Relationships?",
      "score": 87.3,
      "sources": ["youtube", "reddit"],
      "summary": "A growing debate about AI companionship and social isolation.",
      "hooks": [
        "The 60-Second AI Reality Check",
        "Are AI friendships replacing real ones?"
      ],
      "channels": {
        "BiteSizedKnowledge": 0.82,
        "BrainWaveHistory": 0.12
      }
    }
  ],
  "top_per_channel": {
    "BiteSizedKnowledge": [
      {
        "topic_id": "10eec8e8-12bb-4d12-95d9-c0e91fc8af4c",
        "title": "AI Reality Check: Are We Replacing Real Relationships?",
        "score": 87.3,
        "sources": ["youtube", "reddit"],
        "summary": "A growing debate about AI companionship and social isolation.",
        "hooks": [
          "The 60-Second AI Reality Check",
          "Are AI friendships replacing real ones?"
        ],
        "channels": {
          "BiteSizedKnowledge": 0.82,
          "BrainWaveHistory": 0.12
        }
      }
    ],
    "CrimeStoriesToday": []
  }
}
```

### GET /api/topics/{topic_id}

method:
`GET`

route:
`/api/topics/{topic_id}`

request schema:
Path param `topic_id` (UUID string).

response schema:
```json
{
  "topic_id": "uuid",
  "title": "string",
  "summary": "string",
  "hooks": ["string"],
  "sources": [
    {
      "source": "youtube|reddit|trends",
      "url": "https://...",
      "score": 73.1,
      "reasons": [{"feature": "youtube_views", "contribution": 12.5}]
    }
  ],
  "metrics": {
    "instance_count": 2,
    "total_score": 87.3
  },
  "channel_relevance": {
    "BiteSizedKnowledge": 0.82,
    "BrainWaveHistory": 0.12
  },
  "latest_action": "like|maybe|skip|used|blacklist|null",
  "notes": ["string"]
}
```

example request:
```http
GET /api/topics/10eec8e8-12bb-4d12-95d9-c0e91fc8af4c
```

example response:
```json
{
  "topic_id": "10eec8e8-12bb-4d12-95d9-c0e91fc8af4c",
  "title": "AI Reality Check: Are We Replacing Real Relationships?",
  "summary": "A growing debate about AI companionship and social isolation.",
  "hooks": [
    "The 60-Second AI Reality Check",
    "Are AI friendships replacing real ones?"
  ],
  "sources": [
    {
      "source": "youtube",
      "url": "https://www.youtube.com/watch?v=abc123",
      "score": 42.1,
      "reasons": [{"feature": "youtube_views", "contribution": 21.0}]
    },
    {
      "source": "reddit",
      "url": "https://www.reddit.com/r/technology/comments/xyz",
      "score": 45.2,
      "reasons": [{"feature": "reddit_score", "contribution": 20.1}]
    }
  ],
  "metrics": {
    "instance_count": 2,
    "total_score": 87.3
  },
  "channel_relevance": {
    "BiteSizedKnowledge": 0.82,
    "BrainWaveHistory": 0.12
  },
  "latest_action": "maybe",
  "notes": ["Potential angle for shorts"]
}
```

### POST /api/topics/{topic_id}/action

method:
`POST`

route:
`/api/topics/{topic_id}/action`

request schema:
```json
{
  "action": "like|maybe|skip|used|blacklist",
  "note": "string (optional)"
}
```

response schema:
```json
{
  "status": "ok"
}
```

example request:
```http
POST /api/topics/10eec8e8-12bb-4d12-95d9-c0e91fc8af4c/action
Content-Type: application/json

{
  "action": "like",
  "note": "Good for Bite-Sized Knowledge"
}
```

example response:
```json
{
  "status": "ok"
}
```

### POST /api/export

method:
`POST`

route:
`/api/export`

request schema:
```json
{
  "topic_ids": ["uuid1", "uuid2"],
  "format": "topic_factory_v1"
}
```

response schema:
```json
{
  "topics": [
    {
      "topic_id": "uuid",
      "title": "string",
      "summary": "string",
      "research_angles": ["string"],
      "source_count": 2
    }
  ]
}
```

example request:
```http
POST /api/export
Content-Type: application/json

{
  "topic_ids": ["10eec8e8-12bb-4d12-95d9-c0e91fc8af4c", "e4d5ae40-9b0f-4996-98ca-100e8c597157"],
  "format": "topic_factory_v1"
}
```

example response:
```json
{
  "topics": [
    {
      "topic_id": "10eec8e8-12bb-4d12-95d9-c0e91fc8af4c",
      "title": "AI Reality Check: Are We Replacing Real Relationships?",
      "summary": "A growing debate about AI companionship and social isolation.",
      "research_angles": [
        "The 60-Second AI Reality Check",
        "Are AI friendships replacing real ones?"
      ],
      "source_count": 2
    }
  ]
}
```

## 4. UI Interaction Model
Dashburg should use this interaction sequence.

Startup flow:

1) page loads
2) `GET /api/runs`
3) select latest completed run
4) `GET /api/runs/{run_id}/results`

Starting a run:

`POST /api/runs/start`

Dashburg should poll:

`GET /api/runs/{run_id}`

until `status=SUCCEEDED`.

Polling interval recommendation:

2 seconds.

## 5. Topic Detail Flow
When user clicks a topic card:

Dashburg calls:

`GET /api/topics/{topic_id}`

Returns:

- summary
- hooks
- sources
- metrics
- channel_relevance

Display these in a side panel or modal.

## 6. Topic Actions
Dashburg buttons:

- Like
- Maybe
- Skip
- Used
- Blacklist

API call:

`POST /api/topics/{topic_id}/action`

Payload:

```json
{
  "action": "like",
  "note": "Good for Bite-Sized Knowledge"
}
```

Response:

```json
{
  "status": "ok"
}
```

## 7. Topic Factory Export Flow
Dashburg selection → Topic Factory.

Steps:

1) user selects topics
2) Dashburg calls:

`POST /api/export`

Payload:

```json
{
  "topic_ids": ["uuid1", "uuid2"],
  "format": "topic_factory_v1"
}
```

Response:

```json
{
  "topics": [
    {
      "title": "...",
      "summary": "...",
      "research_angles": ["..."]
    }
  ]
}
```

Dashburg then sends this payload to Topic Factory.

## 8. Run Configuration Controls
Parameters Dashburg can send:

sources:
- youtube
- reddit
- google_trends (maps to backend `trends` source key)

categories (YouTube):

News & Politics = 25  
Entertainment = 24  
Sports = 17  
Gaming = 20

These category IDs are defined by the YouTube Data API and allow filtering when requesting most-popular videos.

Subreddit list example:

- technology
- worldnews
- todayilearned
- science
- futurology
- AskReddit
- gaming
- news

Run size presets:

- Small
- Medium
- Large

Each preset adjusts API fetch limits.

## 9. Expected Run Timing
Typical run time:

Small: ~10 seconds
Medium: ~20 seconds
Large: ~45 seconds

Most time is spent on:
- YouTube API calls
- LLM classification.

## 10. Error Handling
Dashburg should handle:

- backend unreachable
- run failure
- partial source failure

Return message example:

```json
{
  "status": "FAILED",
  "error": "YouTube quota exceeded"
}
```

## 11. Future Extension Hooks
Optional future endpoints:

- `/api/topics/similar`
- `/api/topics/history`
- `/api/channels/recommendations`

Dashburg can ignore these for now.
