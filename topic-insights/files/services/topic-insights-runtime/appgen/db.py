from __future__ import annotations
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path("./data/appgen.sqlite3")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS appgen_schema_version (
            version INTEGER NOT NULL
        )
        """)
        row = conn.execute("SELECT version FROM appgen_schema_version LIMIT 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO appgen_schema_version(version) VALUES (1)")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS appgen_ideas (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            one_liner TEXT NOT NULL,
            problem_statement TEXT NOT NULL,
            target_user TEXT NOT NULL,
            primary_pain_point TEXT NOT NULL,
            category TEXT,
            status TEXT NOT NULL,
            execution_stage TEXT NOT NULL,
            scores_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            source_meta_json TEXT NOT NULL,
            project_ref_json TEXT,
            appcreator_ref_json TEXT,
            model_usage_json TEXT NOT NULL,
            feedback_meta_json TEXT NOT NULL,
            novelty_hash TEXT,
            needs_scoring INTEGER NOT NULL DEFAULT 0,
            quality_flags_json TEXT NOT NULL DEFAULT '[]',
            imported_from TEXT,
            imported_source_ref TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS appgen_artifacts (
            id TEXT PRIMARY KEY,
            idea_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            content_format TEXT NOT NULL,
            content_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS appgen_pain_points (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            text TEXT NOT NULL,
            severity REAL,
            category TEXT,
            extracted_at TEXT NOT NULL
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS appgen_runs (
            id TEXT PRIMARY KEY,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL,
            provider_used TEXT,
            model_used TEXT,
            input_hash TEXT,
            metrics_json TEXT NOT NULL,
            budget_snapshot_json TEXT NOT NULL DEFAULT '{}',
            input_summary_json TEXT NOT NULL DEFAULT '{}',
            idea_id TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            error_text TEXT
        )
        """)
        # Migrations for older local DBs
        idea_cols = [r[1] for r in conn.execute("PRAGMA table_info(appgen_ideas)").fetchall()]
        if "novelty_hash" not in idea_cols:
            conn.execute("ALTER TABLE appgen_ideas ADD COLUMN novelty_hash TEXT")
        if "needs_scoring" not in idea_cols:
            conn.execute("ALTER TABLE appgen_ideas ADD COLUMN needs_scoring INTEGER NOT NULL DEFAULT 0")
        if "quality_flags_json" not in idea_cols:
            conn.execute("ALTER TABLE appgen_ideas ADD COLUMN quality_flags_json TEXT NOT NULL DEFAULT '[]'")
        if "imported_from" not in idea_cols:
            conn.execute("ALTER TABLE appgen_ideas ADD COLUMN imported_from TEXT")
        if "imported_source_ref" not in idea_cols:
            conn.execute("ALTER TABLE appgen_ideas ADD COLUMN imported_source_ref TEXT")

        run_cols = [r[1] for r in conn.execute("PRAGMA table_info(appgen_runs)").fetchall()]
        if "budget_snapshot_json" not in run_cols:
            conn.execute("ALTER TABLE appgen_runs ADD COLUMN budget_snapshot_json TEXT NOT NULL DEFAULT '{}'")
        if "input_summary_json" not in run_cols:
            conn.execute("ALTER TABLE appgen_runs ADD COLUMN input_summary_json TEXT NOT NULL DEFAULT '{}'")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS appgen_outbox_events (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            delivered_at TEXT
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS appgen_followup_seeds (
            id TEXT PRIMARY KEY,
            seed_text TEXT NOT NULL,
            source_meta_json TEXT NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_appgen_ideas_status ON appgen_ideas(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appgen_ideas_novelty_hash ON appgen_ideas(novelty_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appgen_runs_type ON appgen_runs(run_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_appgen_outbox_status ON appgen_outbox_events(status)")
