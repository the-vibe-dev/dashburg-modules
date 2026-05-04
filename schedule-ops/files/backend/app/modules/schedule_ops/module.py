from app.modules.base import BackendModule
from app.modules.schedule_ops.router import router

schedule_ops_module = BackendModule(
    key="schedule_ops",
    name="ScheduleOps",
    sidebar_label="ScheduleOps",
    router=router,
    routes=[
        {"path": "/modules/schedule-ops", "label": "ScheduleOps"},
    ],
    cards=[
        {
            "title": "ScheduleOps",
            "description": "Central cron and mailbox dispatch policy across remote runner nodes.",
            "href": "/modules/schedule-ops",
        }
    ],
)
