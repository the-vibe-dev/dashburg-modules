from __future__ import annotations

from fastapi import FastAPI

from trend_harvester.api.routes import router as api_router
from trend_harvester.migrations.runner import run_migrations

app = FastAPI(title="Trend Harvester", version="0.1.0")


@app.on_event("startup")
def startup_event() -> None:
    run_migrations()


app.include_router(api_router)
