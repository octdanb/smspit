import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Ban, Trash2 } from "lucide-react";

import {
  clearThread,
  fetchLatestCode,
  fetchThread,
  setOptOut,
} from "@/api/client";
import { CopyChip } from "@/components/copy-chip";
import { MessageBubble } from "@/components/message-bubble";
import { ReplyBox } from "@/components/reply-box";
import { VerificationsPanel } from "@/components/verifications-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/numbers/$number")({
  component: ThreadView,
});

function ThreadView() {
  const { number } = Route.useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Kept fresh by WebSocket-driven invalidation (see api/ws.ts).
  const thread = useQuery({
    queryKey: ["thread", number],
    queryFn: () => fetchThread(number),
  });

  const clear = useMutation({
    mutationFn: () => clearThread(number),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["numbers"] });
      queryClient.invalidateQueries({ queryKey: ["thread", number] });
      navigate({ to: "/" });
    },
  });

  const latestCode = useQuery({
    queryKey: ["latest-code", number],
    queryFn: () => fetchLatestCode(number),
  });

  const optedOut = thread.data?.opted_out ?? false;
  const toggleOptOut = useMutation({
    mutationFn: () => setOptOut(number, !optedOut),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["numbers"] });
      queryClient.invalidateQueries({ queryKey: ["thread", number] });
    },
  });

  const scroller = useRef<HTMLDivElement>(null);
  const messageCount = thread.data?.messages.length ?? 0;
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messageCount, number]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <div>
            <h2 className="font-semibold">{number}</h2>
            {thread.isSuccess && (
              <p className="text-xs text-muted-foreground">
                {thread.data.total} message{thread.data.total === 1 ? "" : "s"}
              </p>
            )}
          </div>
          {optedOut && <Badge variant="destructive">opted out</Badge>}
          {latestCode.data && (
            <CopyChip value={latestCode.data.code} label="latest code" />
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            title={
              optedOut
                ? "Clear the opt-out for this number"
                : "Mark this number as opted out (STOP)"
            }
            onClick={() => toggleOptOut.mutate()}
            disabled={toggleOptOut.isPending}
          >
            <Ban />
            {optedOut ? "Opt back in" : "Opt out"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => clear.mutate()}
            disabled={clear.isPending}
          >
            <Trash2 />
            Clear thread
          </Button>
        </div>
      </header>
      <VerificationsPanel number={number} />
      <div
        ref={scroller}
        className="flex flex-1 flex-col gap-3 overflow-y-auto p-4"
      >
        {thread.isPending && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {thread.isError && (
          <p className="text-sm text-destructive">Failed to load thread.</p>
        )}
        {thread.data?.messages.map((message) => (
          <MessageBubble key={message.sid} message={message} />
        ))}
      </div>
      <ReplyBox number={number} />
    </div>
  );
}
