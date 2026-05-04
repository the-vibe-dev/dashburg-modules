import { lazy } from "react";
import { Bot } from "lucide-react";
import type { FrontendModule } from "../types";

const SkilledAgentsOverviewPage = lazy(async () => ({ default: (await import("./SkilledAgentsPages")).SkilledAgentsOverviewPage }));
const SkilledAgentCreatePage = lazy(async () => ({ default: (await import("./SkilledAgentsPages")).SkilledAgentCreatePage }));
const SkilledAgentDetailPage = lazy(async () => ({ default: (await import("./SkilledAgentsPages")).SkilledAgentDetailPage }));
const SkilledSkillLibraryPage = lazy(async () => ({ default: (await import("./SkilledAgentsPages")).SkilledSkillLibraryPage }));

export const skilledAgentsModule: FrontendModule = {
  key: "skilled_agents",
  name: "Skilled Agents",
  icon: Bot,
  section: "operations",
  sidebar: { label: "Skilled Agents", href: "/modules/skilled-agents" },
  cards: [
    {
      title: "Skilled Agents",
      description: "Wizard-driven control plane for creating, deploying, and operating specialized agents.",
      href: "/modules/skilled-agents",
    },
  ],
  routes: [
    { path: "/modules/skilled-agents", element: <SkilledAgentsOverviewPage /> },
    { path: "/modules/skilled-agents/new", element: <SkilledAgentCreatePage /> },
    { path: "/modules/skilled-agents/library", element: <SkilledSkillLibraryPage /> },
    { path: "/modules/skilled-agents/:id", element: <SkilledAgentDetailPage /> },
  ],
};
