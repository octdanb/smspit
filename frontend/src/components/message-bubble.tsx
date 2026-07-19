import type { ThreadMessage } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { messageTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function MessageBubble({ message }: { message: ThreadMessage }) {
  const outbound = message.direction.startsWith("outbound");

  return (
    <div
      data-testid="message-bubble"
      className={cn(
        "flex flex-col gap-1",
        outbound ? "items-end" : "items-start",
      )}
    >
      <div
        className={cn(
          "max-w-[75%] whitespace-pre-wrap break-words rounded-2xl px-4 py-2 text-sm",
          outbound
            ? "rounded-br-sm bg-primary text-primary-foreground"
            : "rounded-bl-sm bg-muted text-foreground",
        )}
      >
        {message.media.length > 0 && (
          <div className="mb-1 flex flex-wrap gap-2">
            {message.media.map((item) =>
              item.content_type.startsWith("image/") ? (
                <img
                  key={item.sid}
                  src={item.url}
                  alt={item.content_type}
                  className="max-h-48 rounded-lg"
                />
              ) : (
                <a
                  key={item.sid}
                  href={item.url}
                  className="text-xs underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  {item.content_type}
                </a>
              ),
            )}
          </div>
        )}
        {message.body || (message.media.length === 0 && <em>(no body)</em>)}
      </div>
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>{messageTime(message.date_created)}</span>
        <Badge variant="outline">{message.status}</Badge>
        {message.num_segments > 1 && (
          <span>
            {message.num_segments} segments ({message.encoding})
          </span>
        )}
        {message.num_media > 0 && <span>{message.num_media} media</span>}
        {message.channel !== "sms" && (
          <Badge variant="secondary">{message.channel}</Badge>
        )}
        {message.error_code !== null && (
          <Badge variant="destructive">error {message.error_code}</Badge>
        )}
      </div>
    </div>
  );
}
