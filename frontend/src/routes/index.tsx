import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { Inbox } from "lucide-react";

import { fetchHealth } from "@/api/client";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth });

  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <Inbox className="size-10 text-muted-foreground" />
      <h2 className="text-lg font-medium">Select a conversation</h2>
      <p className="max-w-sm text-sm text-muted-foreground">
        Messages your app sends through the Twilio-compatible API show up in the
        sidebar, grouped by number.
      </p>
      <p className="text-xs text-muted-foreground" data-testid="backend-status">
        {health.isSuccess
          ? "Backend connected"
          : health.isError
            ? "Backend unreachable — is the API running on port 8025?"
            : "Checking backend…"}
      </p>
    </div>
  );
}
