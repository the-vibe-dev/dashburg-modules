import { lazy } from "react";
import { Archive } from "lucide-react";
import type { FrontendModule } from "../types";

const IdeaVaultPage = lazy(async () => ({ default: (await import("./IdeaVaultPage")).IdeaVaultPage }));

export const ideaVaultModule: FrontendModule = {
  key: "ideavault",
  name: "IdeaVault",
  icon: Archive,
  section: "content",
  sidebar: { label: "IdeaVault", href: "/modules/ideavault" },
  cards: [
    {
      title: "IdeaVault",
      description: "Saved opportunities with source evidence and related runs.",
      href: "/modules/ideavault",
    },
  ],
  routes: [{ path: "/modules/ideavault", element: <IdeaVaultPage /> }],
};
