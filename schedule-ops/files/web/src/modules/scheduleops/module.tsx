import { lazy } from "react";
import { CalendarClock } from "lucide-react";

import type { FrontendModule } from "../types";

const ScheduleOpsPage = lazy(async () => ({ default: (await import("./ScheduleOpsPage")).ScheduleOpsPage }));

export const scheduleOpsModule: FrontendModule = {
  key: "schedule_ops",
  name: "ScheduleOps",
  icon: CalendarClock,
  section: "infrastructure",
  sidebar: { label: "ScheduleOps", href: "/modules/schedule-ops" },
  cards: [
    {
      title: "ScheduleOps",
      description: "Central cron policy for runner and agent mailbox dispatch on all nodes.",
      href: "/modules/schedule-ops",
    },
  ],
  routes: [{ path: "/modules/schedule-ops", element: <ScheduleOpsPage /> }],
};
