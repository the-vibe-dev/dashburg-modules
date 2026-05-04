from app.modules.appgen.router import router
from app.modules.base import BackendModule

appgen_module = BackendModule(
    key="appgen",
    name="IdeaFactory",
    sidebar_label="IdeaFactory",
    router=router,
    routes=[{"path": "/modules/appgen", "label": "IdeaFactory"}],
    cards=[
        {
            "title": "IdeaFactory",
            "description": "Opportunity workflow: rank, review, and promote video/app/saas ideas.",
            "href": "/modules/appgen",
        }
    ],
)
