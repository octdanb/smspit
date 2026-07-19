import { useEffect, useState } from "react";
import { Link, Outlet, createRootRoute } from "@tanstack/react-router";
import { MessageSquareText, Moon, Settings, Sun, Webhook } from "lucide-react";

import { useLiveUpdates, type LiveStatus } from "@/api/ws";
import { NumberSidebar } from "@/components/number-sidebar";
import { Button } from "@/components/ui/button";
import { applyTheme, initialTheme, type Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

export const Route = createRootRoute({
  component: RootLayout,
});

const statusStyles: Record<LiveStatus, { dot: string; label: string }> = {
  live: { dot: "bg-emerald-500", label: "live" },
  connecting: { dot: "bg-amber-500", label: "connecting" },
  offline: { dot: "bg-destructive", label: "offline" },
};

function RootLayout() {
  const status = useLiveUpdates();
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <div className="flex h-screen flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
        <Link to="/" className="flex items-center gap-2">
          <MessageSquareText className="size-5" />
          <h1 className="text-lg font-semibold tracking-tight">smspit</h1>
        </Link>
        <span className="text-sm text-muted-foreground">
          Twilio-compatible SMS mock
        </span>
        <nav className="ml-auto flex items-center gap-1">
          <Link
            to="/webhooks"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&.active]:text-foreground"
          >
            <Webhook className="size-4" />
            Webhooks
          </Link>
          <Link
            to="/settings"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&.active]:text-foreground"
          >
            <Settings className="size-4" />
            Settings
          </Link>
        </nav>
        <Button
          variant="ghost"
          size="icon"
          title="Toggle dark mode"
          onClick={() =>
            setTheme((value) => (value === "dark" ? "light" : "dark"))
          }
        >
          {theme === "dark" ? <Sun /> : <Moon />}
        </Button>
        <span
          className="flex items-center gap-1.5 text-xs text-muted-foreground"
          title="Dashboard live-update connection"
        >
          <span
            className={cn("size-2 rounded-full", statusStyles[status].dot)}
          />
          {statusStyles[status].label}
        </span>
      </header>
      <div className="flex min-h-0 flex-1">
        <NumberSidebar />
        <main className="min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
