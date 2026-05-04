CREATE TABLE IF NOT EXISTS channel_metadata (
  channel_slug TEXT PRIMARY KEY,
  youtube_channel_id TEXT,
  youtube_channel_title TEXT,
  youtube_channel_description TEXT,
  metadata_source TEXT NOT NULL DEFAULT 'fallback',
  raw_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_channel_metadata_youtube_channel_id ON channel_metadata(youtube_channel_id);
