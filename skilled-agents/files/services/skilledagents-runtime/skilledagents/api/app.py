from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException

from skilledagents.api.routes.agents import router as agents_router
from skilledagents.api.routes.health import router as health_router
from skilledagents.api.routes.skills import router as skills_router
from skilledagents.api.routes.starter_templates import router as starter_templates_router
from skilledagents.api.routes.templates import router as templates_router
from skilledagents.services.agent_manager import AgentManager
from skilledagents.services.log_service import LogService
from skilledagents.services.mailbox_service import MailboxService
from skilledagents.services.run_service import RunService
from skilledagents.services.starter_template_service import StarterTemplateService
from skilledagents.services.template_service import AgentTemplateService
from skilledagents.services.workspace_service import WorkspaceService


def _required_api_key() -> str | None:
    return os.getenv("SKILLEDAGENTS_API_KEY")


def require_auth(x_api_key: str | None = Header(default=None)) -> None:
    expected = _required_api_key()
    if not expected:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


def create_app() -> FastAPI:
    app = FastAPI(title="SkilledAgents API", version="0.1.0")

    db_path = Path(os.getenv("SKILLEDAGENTS_DB_PATH", "./skilledagents/data/skilledagents.sqlite3")).resolve()
    workspaces_root = Path(os.getenv("SKILLEDAGENTS_WORKSPACES_ROOT", "./skilledagents/workspaces")).resolve()
    skills_root = Path(
        os.getenv("SKILLEDAGENTS_SKILLS_ROOT", os.path.expanduser("~/.codex/skills"))
    ).resolve()
    starter_templates_root = Path(
        os.getenv("SKILLEDAGENTS_STARTER_TEMPLATES_ROOT", "./skilledagents/starter_templates")
    ).resolve()

    template_service = AgentTemplateService.from_env()
    manager = AgentManager(
        db_path=db_path,
        workspaces_root=workspaces_root,
        skills_root=skills_root,
        template_service=template_service,
    )
    manager.init_db()
    starter_template_service = StarterTemplateService(db_path=db_path, storage_root=starter_templates_root)
    starter_template_service.init_db()
    log_service = LogService(db_path=db_path)
    workspace_service = WorkspaceService(log_service=log_service)
    mailbox_service = MailboxService(manager=manager)
    run_service = RunService(manager=manager, log_service=log_service)

    app.state.db_path = db_path
    app.state.agent_manager = manager
    app.state.log_service = log_service
    app.state.workspace_service = workspace_service
    app.state.mailbox_service = mailbox_service
    app.state.run_service = run_service
    app.state.starter_template_service = starter_template_service

    app.include_router(health_router, dependencies=[Depends(require_auth)])
    app.include_router(templates_router, dependencies=[Depends(require_auth)])
    app.include_router(starter_templates_router, dependencies=[Depends(require_auth)])
    app.include_router(skills_router, dependencies=[Depends(require_auth)])
    app.include_router(agents_router, dependencies=[Depends(require_auth)])

    return app


app = create_app()
