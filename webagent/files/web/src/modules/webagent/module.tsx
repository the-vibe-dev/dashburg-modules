import { lazy } from "react";
import { Globe } from "lucide-react";
import type { FrontendModule } from "../types";

const WebAgentPage = lazy(async () => ({ default: (await import("./WebAgentPages")).WebAgentPage }));

export const webAgentModule: FrontendModule = {
  key: "webagent",
  name: "WebAgent",
  icon: Globe,
  section: "operations",
  sidebar: { label: "WebAgent", href: "/modules/webagent" },
  cards: [
    {
      title: "WebAgent",
      description: "Scrape, discover, and analyze websites with the webagent node.",
      href: "/modules/webagent",
    },
  ],
  routes: [
    { path: "/modules/webagent", element: <WebAgentPage /> },
    { path: "/modules/webagent/new", element: <WebAgentPage /> },
    { path: "/modules/webagent/interactive", element: <WebAgentPage /> },
    { path: "/modules/webagent/runs", element: <WebAgentPage /> },
    { path: "/modules/webagent/runs/:id", element: <WebAgentPage /> },
    { path: "/modules/webagent/reports", element: <WebAgentPage /> },
    { path: "/modules/webagent/status", element: <WebAgentPage /> },
  ],
};
