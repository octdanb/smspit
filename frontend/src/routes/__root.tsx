import { Link, Outlet, createRootRoute } from "@tanstack/react-router";
import { MessageSquareText } from "lucide-react";

import { NumberSidebar } from "@/components/number-sidebar";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
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
