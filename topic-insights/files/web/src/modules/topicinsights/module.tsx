import { lazy } from "react";
import { Search } from "lucide-react";
import type { FrontendModule } from "../types";

const TopicInsightsPage = lazy(async () => ({ default: (await import("./TopicInsightsPage")).TopicInsightsPage }));

export const topicInsightsModule: FrontendModule = {
  key: "topic-insights",
  name: "TopicInsights",
  icon: Search,
  section: "content",
  sidebar: { label: "TopicInsights", href: "/modules/topic-insights" },
  cards: [
    {
      title: "TopicInsights",
      description: "Research layer: signals, pains, patterns, and evidence behind opportunities.",
      href: "/modules/topic-insights",
    },
  ],
  routes: [
    { path: "/modules/topic-insights", element: <TopicInsightsPage initialTab="pain" /> },
    { path: "/modules/topic-insights/pain-graph", element: <TopicInsightsPage initialTab="pain" /> },
    { path: "/modules/topic-insights/workarounds", element: <TopicInsightsPage initialTab="workarounds" /> },
    { path: "/modules/topic-insights/problems", element: <TopicInsightsPage initialTab="problems" /> },
    { path: "/modules/topic-insights/idea-trends", element: <TopicInsightsPage initialTab="trends" /> },
  ],
};
