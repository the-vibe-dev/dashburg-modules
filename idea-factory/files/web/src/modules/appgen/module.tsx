import { lazy } from "react";
import { Zap } from "lucide-react";
import type { FrontendModule } from "../types";

const AppGenPage = lazy(async () => ({ default: (await import("./AppGenPage")).AppGenPage }));

export const appgenModule: FrontendModule = {
  key: "appgen",
  name: "IdeaFactory",
  icon: Zap,
  section: "content",
  sidebar: { label: "IdeaFactory", href: "/modules/appgen" },
  cards: [{ title: "IdeaFactory", description: "Rank and review video/app/saas opportunities.", href: "/modules/appgen" }],
  routes: [{ path: "/modules/appgen", element: <AppGenPage /> }],
};
