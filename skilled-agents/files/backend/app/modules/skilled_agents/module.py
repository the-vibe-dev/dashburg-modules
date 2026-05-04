from app.modules.base import BackendModule
from app.modules.skilled_agents.router import router

skilled_agents_module = BackendModule(
    key="skilled_agents",
    name="Skilled Agents",
    sidebar_label="Skilled Agents",
    router=router,
    routes=[
        {"path": "/modules/skilled-agents", "label": "Overview"},
        {"path": "/modules/skilled-agents/new", "label": "Create Wizard"},
        {"path": "/modules/skilled-agents/library", "label": "Skill Library"},
    ],
    cards=[
        {
            "title": "Skilled Agents",
            "description": "Create, deploy, and monitor specialized agents on the SkilledAgents server.",
            "href": "/modules/skilled-agents",
        }
    ],
)
