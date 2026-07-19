import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { fetchHealth } from "@/api/client";

export const Route = createFileRoute("/")({
  component: Index,
});

function Index() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth });

  return (
    <div className="mx-auto flex max-w-lg flex-col gap-4 p-8">
      <Card>
        <CardHeader>
          <CardTitle>Welcome to smspit</CardTitle>
          <CardDescription>
            Point your app's Twilio base URL here and messages will show up in
            this dashboard.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          {health.isPending && <p>Checking backend…</p>}
          {health.isError && (
            <p>Backend unreachable — is the API running on port 8025?</p>
          )}
          {health.isSuccess && (
            <p data-testid="backend-status">Backend: {health.data.status}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
