import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { CalendarClock, XCircle } from "lucide-react";

import { cancelScheduled, fetchScheduled } from "@/api/client";
import { Button } from "@/components/ui/button";
import { messageTime } from "@/lib/format";

export const Route = createFileRoute("/scheduled")({
  component: ScheduledPage,
});

function ScheduledPage() {
  const queryClient = useQueryClient();
  const scheduled = useQuery({
    queryKey: ["scheduled"],
    queryFn: fetchScheduled,
  });

  const cancel = useMutation({
    mutationFn: (sid: string) => cancelScheduled(sid),
    onSuccess: () => queryClient.invalidateQueries(),
  });

  return (
    <div className="flex h-full flex-col">
      <header className="border-b px-4 py-3">
        <h2 className="font-semibold">Scheduled messages</h2>
        <p className="text-xs text-muted-foreground">
          Messages created with ScheduleType=fixed, waiting for their SendAt
          time.
        </p>
      </header>
      <div className="flex-1 overflow-y-auto">
        {scheduled.isSuccess && scheduled.data.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">
            Nothing scheduled.
          </p>
        )}
        {scheduled.data?.map((message) => (
          <div
            key={message.sid}
            className="flex items-center gap-3 border-b px-4 py-2.5 text-sm"
          >
            <CalendarClock className="size-4 shrink-0 text-muted-foreground" />
            <span className="font-medium">{message.to_number}</span>
            <span className="min-w-0 flex-1 truncate text-muted-foreground">
              {message.body}
            </span>
            <span className="shrink-0 text-xs text-muted-foreground">
              fires {messageTime(message.send_at)}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => cancel.mutate(message.sid)}
              disabled={cancel.isPending}
            >
              <XCircle />
              Cancel
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
