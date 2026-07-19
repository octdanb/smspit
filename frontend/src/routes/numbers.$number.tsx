import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, Ban, Download, Trash2 } from "lucide-react";

import {
  clearThread,
  exportUrl,
  fetchLatestCode,
  fetchThread,
  markThreadRead,
  setOptOut,
} from "@/api/client";
import { CopyChip } from "@/components/copy-chip";
import { MessageBubble } from "@/components/message-bubble";
import { MessageDetail } from "@/components/message-detail";
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

  // Opening the thread (and every new message while it's open) marks it read.
  useEffect(() => {
    if (messageCount > 0) {
      markThreadRead(number).then(() =>
        queryClient.invalidateQueries({ queryKey: ["numbers"] }),
      );
    }
  }, [messageCount, number, queryClient]);

  const [selectedSid, setSelectedSid] = useState<string | null>(null);
  useEffect(() => setSelectedSid(null), [number]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b px-2 py-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
            title="Back to inbox"
            asChild
          >
            <Link to="/">
              <ArrowLeft />
            </Link>
          </Button>
          <div className="min-w-0">
            <h2 className="truncate font-semibold">{number}</h2>
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
            title="Export this thread as JSON"
            asChild
          >
            <a href={exportUrl("json", number)} download>
              <Download />
              <span className="hidden sm:inline">Export</span>
            </a>
          </Button>
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
            <span className="hidden sm:inline">
              {optedOut ? "Opt back in" : "Opt out"}
            </span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            title="Clear thread"
            onClick={() => clear.mutate()}
            disabled={clear.isPending}
          >
            <Trash2 />
            <span className="hidden sm:inline">Clear thread</span>
          </Button>
        </div>
      </header>
      <VerificationsPanel number={number} />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
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
              <MessageBubble
                key={message.sid}
                message={message}
                onSelect={setSelectedSid}
              />
            ))}
          </div>
          <ReplyBox number={number} />
        </div>
        {selectedSid && (
          <MessageDetail
            sid={selectedSid}
            onClose={() => setSelectedSid(null)}
          />
        )}
      </div>
    </div>
  );
}
