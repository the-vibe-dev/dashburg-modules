from __future__ import annotations
import os
from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine
from core.config import settings

engine = create_engine(settings.database_url, echo=False)

def reset_engine(url: str) -> None:
    global engine
    engine = create_engine(url, echo=False)

def init_db() -> None:
    if engine.url.drivername == "sqlite" and engine.url.database:
        db_path = engine.url.database
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    SQLModel.metadata.create_all(engine)
    if engine.url.drivername == "sqlite":
        with engine.begin() as conn:
            tables = {
                "rawpost": "run_id",
                "extractedpain": "run_id",
                "paincluster": "run_id",
                "idea": "run_id",
            }
            for table, column in tables.items():
                cols = [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()]
                if column not in cols:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} VARCHAR")
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_rawpost_run_id ON rawpost(run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_extractedpain_run_id ON extractedpain(run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_paincluster_run_id ON paincluster(run_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_idea_run_id ON idea(run_id)"))

def get_session() -> Session:
    return Session(engine, expire_on_commit=False)
