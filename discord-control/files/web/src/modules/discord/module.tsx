import { lazy } from "react";
import { MessageSquareCode } from "lucide-react";

import type { FrontendModule } from "../types";

const DiscordControlPage = lazy(async () => ({
  default: (await import("./DiscordControlPage")).DiscordControlPage,
}));

export const discordModule: FrontendModule = {
  key: "discord_control",
  name: "Discord Control",
  icon: MessageSquareCode,
  section: "infrastructure",
  sidebar: { label: "Discord Control", href: "/modules/discord-control" },
  cards: [
    {
      title: "Discord Control",
      description: "Secure Discord communications, bridge health, memory context, and dispatch readiness.",
      href: "/modules/discord-control",
    },
  ],
  routes: [{ path: "/modules/discord-control", element: <DiscordControlPage /> }],
};
