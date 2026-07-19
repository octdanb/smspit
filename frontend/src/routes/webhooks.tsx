import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, RotateCw } from "lucide-react";

import {
  fetchWebhookLog,
  retryWebhook,
  type WebhookDelivery,
} from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { messageTime } from "@/lib/format";

export const Route = createFileRoute("/webhooks")({
  component: WebhooksPage,
});

function DeliveryRow({ delivery }: { delivery: WebhookDelivery }) {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: () => retryWebhook(delivery.id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["webhook-log"] }),
  });

  const ok =
    delivery.response_status !== null &&
    delivery.response_status >= 200 &&
    delivery.response_status < 300;

  return (
    <div className="border-b">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-accent"
      >
        {open ? (
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        )}
        <Badge variant="secondary">{delivery.kind}</Badge>
        <span className="min-w-0 flex-1 truncate font-mono text-xs">
          {delivery.url}
        </span>
        {delivery.error ? (
          <Badge variant="destructive">failed</Badge>
        ) : (
          <Badge variant={ok ? "outline" : "destructive"}>
            {delivery.response_status}
          </Badge>
        )}
        <span className="w-16 text-right text-xs text-muted-foreground">
          {delivery.duration_ms}ms
        </span>
        <span className="hidden w-32 text-right text-xs text-muted-foreground sm:inline">
          {messageTime(delivery.created_at)}
        </span>
      </button>
      {open && (
        <div className="space-y-2 bg-muted/40 px-11 py-3 text-xs">
          {delivery.error && (
            <p className="text-destructive">{delivery.error}</p>
          )}
          <pre className="overflow-x-auto rounded bg-background p-2">
            {JSON.stringify(delivery.request_params, null, 2)}
          </pre>
          {delivery.response_body && (
            <pre className="max-h-32 overflow-auto rounded bg-background p-2">
              {delivery.response_body}
            </pre>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => retry.mutate()}
            disabled={retry.isPending}
          >
            <RotateCw />
            Retry delivery
          </Button>
        </div>
      )}
    </div>
  );
}

function WebhooksPage() {
  const [kind, setKind] = useState("");
  const [result, setResult] = useState("");
  const [messageSid, setMessageSid] = useState("");
  const log = useQuery({
    queryKey: ["webhook-log", kind, result, messageSid],
    queryFn: () =>
      fetchWebhookLog({ kind, result, message_sid: messageSid.trim() }),
    placeholderData: (previous) => previous,
  });

  const selectClass =
    "h-8 rounded-md border border-input bg-transparent px-2 text-xs";

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-end justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="font-semibold">Webhook deliveries</h2>
          <p className="text-xs text-muted-foreground">
            Status callbacks and inbound webhooks sent to your app, signed with
            X-Twilio-Signature.
          </p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
          <select
            aria-label="Filter by kind"
            className={selectClass}
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">all kinds</option>
            <option value="status_callback">status callbacks</option>
            <option value="inbound">inbound</option>
          </select>
          <select
            aria-label="Filter by result"
            className={selectClass}
            value={result}
            onChange={(event) => setResult(event.target.value)}
          >
            <option value="">any result</option>
            <option value="success">success</option>
            <option value="error">errors</option>
          </select>
          <Input
            className="h-8 w-full text-xs sm:w-64"
            placeholder="Filter by message SID…"
            value={messageSid}
            onChange={(event) => setMessageSid(event.target.value)}
          />
        </div>
      </header>
      <div className="flex-1 overflow-y-auto">
        {log.isSuccess && log.data.deliveries.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">
            No deliveries yet. Send a message with a StatusCallback URL and
            they'll show up here.
          </p>
        )}
        {log.data?.deliveries.map((delivery) => (
          <DeliveryRow key={delivery.id} delivery={delivery} />
        ))}
      </div>
    </div>
  );
}
