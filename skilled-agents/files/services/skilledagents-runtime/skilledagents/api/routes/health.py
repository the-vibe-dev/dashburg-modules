from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def get_health(request: Request) -> dict:
    manager = request.app.state.agent_manager
    starter_service = request.app.state.starter_template_service
    db_path: Path = request.app.state.db_path
    return {
        "ok": True,
        "service": "skilledagents",
        "time": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "agents_count": len(manager.list_agents()),
        "starter_templates_count": len(starter_service.list_templates()),
    }
