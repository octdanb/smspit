import { Outlet, createRootRoute } from "@tanstack/react-router";
import { MessageSquareText } from "lucide-react";

export const Route = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <MessageSquareText className="size-5" />
        <h1 className="text-lg font-semibold tracking-tight">smspit</h1>
        <span className="text-sm text-muted-foreground">
          Twilio-compatible SMS mock
        </span>
      </header>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}
