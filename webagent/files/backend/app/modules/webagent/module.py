from app.modules.base import BackendModule
from app.modules.webagent.router import router

webagent_module = BackendModule(
    key="webagent",
    name="WebAgent",
    sidebar_label="WebAgent",
    router=router,
    routes=[{"path": "/modules/webagent", "label": "WebAgent"}],
    cards=[
        {
            "title": "WebAgent",
            "description": "Scrape, discover, and analyze web apps through the webagent node.",
            "href": "/modules/webagent",
        }
    ],
)
