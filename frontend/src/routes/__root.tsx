import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Link,
  Outlet,
  createRootRoute,
  useRouterState,
} from "@tanstack/react-router";
import {
  Bell,
  BellOff,
  CalendarClock,
  KeyRound,
  MessageSquareText,
  Moon,
  Settings,
  Sun,
  Webhook,
} from "lucide-react";

import { fetchNumbers, setDashboardToken } from "@/api/client";
import { useLiveUpdates, type LiveStatus } from "@/api/ws";
import { NumberSidebar } from "@/components/number-sidebar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { notificationsEnabled, setNotificationsEnabled } from "@/lib/notify";
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

function TokenGate({ onSubmit }: { onSubmit: (token: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 p-8">
      <KeyRound className="size-8 text-muted-foreground" />
      <h2 className="font-medium">Dashboard token required</h2>
      <p className="max-w-sm text-center text-sm text-muted-foreground">
        This smspit instance is protected (SMSPIT_DASHBOARD_TOKEN). Enter the
        token to continue.
      </p>
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (value.trim()) onSubmit(value.trim());
        }}
      >
        <Input
          type="password"
          placeholder="token"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <Button type="submit">Unlock</Button>
      </form>
    </div>
  );
}

function RootLayout() {
  const status = useLiveUpdates();
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [notify, setNotify] = useState(notificationsEnabled);
  // On phones the inbox list IS the home screen; other routes take over
  // the full width and offer a back affordance instead of the sidebar.
  const isInbox = useRouterState({
    select: (state) => state.location.pathname === "/",
  });

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // A ?token= in the URL stores the dashboard token (handy first-visit link).
  useEffect(() => {
    const urlToken = new URLSearchParams(location.search).get("token");
    if (urlToken) {
      setDashboardToken(urlToken);
      history.replaceState(null, "", location.pathname);
    }
  }, []);

  // Probe an authed endpoint; a 401 means the instance wants a token.
  const probe = useQuery({
    queryKey: ["auth-probe"],
    queryFn: () => fetchNumbers(),
    retry: false,
  });
  if (probe.isError && probe.error.name === "UnauthorizedError") {
    return (
      <TokenGate
        onSubmit={(token) => {
          setDashboardToken(token);
          location.reload();
        }}
      />
    );
  }

  return (
    <div className="flex h-screen flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b px-4 py-3">
        <Link to="/" className="flex items-center gap-2">
          <MessageSquareText className="size-5" />
          <h1 className="text-lg font-semibold tracking-tight">smspit</h1>
        </Link>
        <span className="hidden text-sm text-muted-foreground lg:inline">
          Twilio-compatible SMS mock
        </span>
        <nav className="ml-auto flex items-center gap-1">
          <Link
            to="/scheduled"
            title="Scheduled"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&.active]:text-foreground"
          >
            <CalendarClock className="size-4" />
            <span className="hidden md:inline">Scheduled</span>
          </Link>
          <Link
            to="/webhooks"
            title="Webhooks"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&.active]:text-foreground"
          >
            <Webhook className="size-4" />
            <span className="hidden md:inline">Webhooks</span>
          </Link>
          <Link
            to="/settings"
            title="Settings"
            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground [&.active]:text-foreground"
          >
            <Settings className="size-4" />
            <span className="hidden md:inline">Settings</span>
          </Link>
        </nav>
        <Button
          variant="ghost"
          size="icon"
          title={
            notify
              ? "Disable desktop notifications"
              : "Notify me of new messages when this tab is hidden"
          }
          onClick={async () =>
            setNotify(await setNotificationsEnabled(!notify))
          }
        >
          {notify ? <Bell /> : <BellOff />}
        </Button>
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
          <span className="hidden sm:inline">{statusStyles[status].label}</span>
        </span>
      </header>
      <div className="flex min-h-0 flex-1">
        <NumberSidebar className={isInbox ? "flex" : "hidden md:flex"} />
        <main
          className={cn(
            "min-w-0 flex-1 overflow-y-auto",
            isInbox && "hidden md:block",
          )}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
