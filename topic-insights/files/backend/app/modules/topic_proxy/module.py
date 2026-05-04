from app.modules.base import BackendModule
from app.modules.topic_proxy.router import router


topic_proxy_module = BackendModule(
    key="topic_proxy",
    name="TopicInsights Proxy",
    sidebar_label="TopicInsights",
    router=router,
    routes=[{"path": "/modules/appgen", "label": "AppGen"}],
    cards=[
        {
            "title": "Topic Intelligence",
            "description": "Signals, patterns, pains, and clusters powering IdeaFactory opportunities.",
            "href": "/modules/appgen",
        }
    ],
)
