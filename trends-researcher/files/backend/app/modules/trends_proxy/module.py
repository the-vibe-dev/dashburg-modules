from app.modules.base import BackendModule
from app.modules.trends_proxy.router import router


trends_proxy_module = BackendModule(
    key="trends_proxy",
    name="Trends Researcher",
    sidebar_label="Trends Researcher",
    router=router,
    routes=[{"path": "/modules/trends", "label": "Trends Researcher"}],
    cards=[
        {
            "title": "Trends Researcher",
            "description": "Run trend harvesting jobs and export winning topics into TopicFactory.",
            "href": "/modules/trends",
        }
    ],
)
