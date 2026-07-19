import { Link, Outlet, createRootRoute } from "@tanstack/react-router";
import { MessageSquareText } from "lucide-react";

import { useLiveUpdates, type LiveStatus } from "@/api/ws";
import { NumberSidebar } from "@/components/number-sidebar";
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
        <span
          className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground"
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
