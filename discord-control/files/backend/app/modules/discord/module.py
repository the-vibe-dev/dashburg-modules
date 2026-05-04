from __future__ import annotations

from app.modules.base import BackendModule
from app.modules.discord.router import router


discord_module = BackendModule(
    key="discord",
    name="Discord Control",
    sidebar_label="Discord Control",
    router=router,
    routes=[{"path": "/modules/discord-control", "label": "Discord Bot & Bridge"}],
    cards=[
        {
            "title": "Discord Control",
            "description": "Secure Discord bridge settings, health checks, memory context, and dispatch readiness.",
            "href": "/modules/discord-control",
        }
    ],
)
