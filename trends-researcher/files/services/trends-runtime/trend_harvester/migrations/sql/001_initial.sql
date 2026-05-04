CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  started_at TEXT,
  finished_at TEXT,
  status TEXT NOT NULL,
  params_json TEXT NOT NULL,
  error TEXT,
  totals_json TEXT NOT NULL,
  request_hash TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS ix_runs_request_hash ON runs(request_hash);

CREATE TABLE IF NOT EXISTS candidates (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  published_at TEXT,
  raw_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_candidates_run_id ON candidates(run_id);
CREATE INDEX IF NOT EXISTS ix_candidates_source ON candidates(source);
CREATE INDEX IF NOT EXISTS ix_candidates_run_source ON candidates(run_id, source);

CREATE TABLE IF NOT EXISTS topics (
  id TEXT PRIMARY KEY,
  canonical_title TEXT NOT NULL,
  normalized_key TEXT NOT NULL UNIQUE,
  entities_json TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_topics_normalized_key ON topics(normalized_key);

CREATE TABLE IF NOT EXISTS topic_instances (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  topic_id TEXT NOT NULL,
  source TEXT NOT NULL,
  url TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  score REAL NOT NULL,
  reasons_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
  FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_topic_instances_run_id ON topic_instances(run_id);
CREATE INDEX IF NOT EXISTS ix_topic_instances_topic_id ON topic_instances(topic_id);
CREATE INDEX IF NOT EXISTS ix_topic_instances_source ON topic_instances(source);
CREATE INDEX IF NOT EXISTS ix_topic_instances_run_topic ON topic_instances(run_id, topic_id);

CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  llm_summary TEXT NOT NULL,
  channel_tags_json TEXT NOT NULL,
  angle_suggestions_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE,
  FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_analyses_topic_id ON analyses(topic_id);
CREATE INDEX IF NOT EXISTS ix_analyses_run_id ON analyses(run_id);

CREATE TABLE IF NOT EXISTS actions (
  id TEXT PRIMARY KEY,
  topic_id TEXT NOT NULL,
  action TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_actions_topic_id ON actions(topic_id);
CREATE INDEX IF NOT EXISTS ix_actions_action ON actions(action);
CREATE INDEX IF NOT EXISTS ix_actions_topic_action ON actions(topic_id, action);
