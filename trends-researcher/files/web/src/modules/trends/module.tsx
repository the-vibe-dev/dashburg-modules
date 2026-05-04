import { lazy } from "react";
import { LineChart } from "lucide-react";
import type { FrontendModule } from "../types";

const TrendsResearcherPage = lazy(async () => ({ default: (await import("./TrendsResearcherPage")).TrendsResearcherPage }));

export const trendsModule: FrontendModule = {
  key: "trends",
  name: "TrendsResearcher",
  icon: LineChart,
  section: "content",
  sidebar: { label: "TrendsResearcher", href: "/modules/trends" },
  cards: [
    {
      title: "TrendsResearcher",
      description: "Harvest trends, score topics, and export winners to IdeaFactory.",
      href: "/modules/trends",
    },
  ],
  routes: [
    { path: "/modules/trends", element: <TrendsResearcherPage /> },
    { path: "/trends", element: <TrendsResearcherPage /> },
  ],
};
