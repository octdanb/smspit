import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";

import { clearThread, fetchThread } from "@/api/client";
import { MessageBubble } from "@/components/message-bubble";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/numbers/$number")({
  component: ThreadView,
});

function ThreadView() {
  const { number } = Route.useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const thread = useQuery({
    queryKey: ["thread", number],
    queryFn: () => fetchThread(number),
    refetchInterval: 3000, // polling until WebSocket events land (phase 3)
  });

  const clear = useMutation({
    mutationFn: () => clearThread(number),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["numbers"] });
      queryClient.invalidateQueries({ queryKey: ["thread", number] });
      navigate({ to: "/" });
    },
  });

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <h2 className="font-semibold">{number}</h2>
          {thread.isSuccess && (
            <p className="text-xs text-muted-foreground">
              {thread.data.total} message{thread.data.total === 1 ? "" : "s"}
            </p>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => clear.mutate()}
          disabled={clear.isPending}
        >
          <Trash2 />
          Clear thread
        </Button>
      </header>
      <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
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
    </div>
  );
}
