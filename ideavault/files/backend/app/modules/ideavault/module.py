from app.modules.base import BackendModule
from app.modules.ideavault.router import router


ideavault_module = BackendModule(
    key="ideavault",
    name="IdeaVault",
    sidebar_label="IdeaVault",
    router=router,
    routes=[{"path": "/modules/ideavault", "label": "IdeaVault"}],
    cards=[
        {
            "title": "IdeaVault",
            "description": "Save trends/topics/ideas and queue them for TopicFactory research.",
            "href": "/modules/ideavault",
        }
    ],
)
