import type { ThreadMessage } from "@/api/client";
import { CopyChip } from "@/components/copy-chip";
import { Badge } from "@/components/ui/badge";
import { messageTime } from "@/lib/format";
import { extractCode } from "@/lib/otp";
import { cn } from "@/lib/utils";

export function MessageBubble({
  message,
  onSelect,
}: {
  message: ThreadMessage;
  onSelect?: (sid: string) => void;
}) {
  const outbound = message.direction.startsWith("outbound");
  const code = outbound ? extractCode(message.body) : null;

  return (
    <div
      data-testid="message-bubble"
      onClick={() => onSelect?.(message.sid)}
      className={cn(
        "flex flex-col gap-1",
        outbound ? "items-end" : "items-start",
        onSelect && "cursor-pointer",
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
        {code && <CopyChip value={code} label="code" />}
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
        {message.tags.map((tag) => (
          <span
            key={tag}
            className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-700 dark:text-amber-400"
          >
            {tag}
          </span>
        ))}
      </div>
    </div>
  );
}
