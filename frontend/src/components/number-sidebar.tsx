import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Search } from "lucide-react";

import { fetchNumbers } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function NumberSidebar({ className }: { className?: string }) {
  const [search, setSearch] = useState("");
  // Kept fresh by WebSocket-driven invalidation (see api/ws.ts). The search
  // runs server-side across full message bodies, not just previews.
  const numbers = useQuery({
    queryKey: ["numbers", search],
    queryFn: () => fetchNumbers(search),
    placeholderData: (previous) => previous,
  });

  const filtered = numbers.data ?? [];

  return (
    <aside
      className={cn(
        "w-full shrink-0 flex-col border-r md:w-80",
        className ?? "flex",
      )}
    >
      <div className="relative border-b p-3">
        <Search className="pointer-events-none absolute left-6 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          title="Operators: tag: from: to: status: has:media is:unread before:/after:YYYY-MM-DD"
          placeholder="Search… (tag: from: status: is:unread…)"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="pl-8"
        />
      </div>
      <nav className="flex-1 overflow-y-auto">
        {numbers.isSuccess && filtered.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">
            {search
              ? "No matches."
              : "No messages yet. Point your app's Twilio base URL at this service and send an SMS."}
          </p>
        )}
        {filtered.map((entry) => (
          <Link
            key={entry.number}
            to="/numbers/$number"
            params={{ number: entry.number }}
            className={cn(
              "flex flex-col gap-1 border-b px-4 py-3 hover:bg-accent",
              "data-[status=active]:bg-accent",
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5">
                <span
                  className={cn(
                    "truncate font-medium",
                    entry.unread_count > 0 && "font-bold",
                  )}
                >
                  {entry.number}
                </span>
                {entry.opted_out && (
                  <Badge variant="destructive" className="shrink-0">
                    stop
                  </Badge>
                )}
              </span>
              <span className="flex shrink-0 items-center gap-1">
                {entry.unread_count > 0 && (
                  <Badge className="bg-sky-600 text-white">
                    {entry.unread_count}
                  </Badge>
                )}
                <Badge variant="secondary">{entry.message_count}</Badge>
              </span>
            </div>
            <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
              <span className="truncate">
                {entry.last_message.body || "(no body)"}
              </span>
              <span className="shrink-0 text-xs">
                {relativeTime(entry.last_message.date_created)}
              </span>
            </div>
            {entry.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {entry.tags.slice(0, 4).map((tag) => (
                  <button
                    key={tag}
                    type="button"
                    title={`Filter by tag:${tag}`}
                    onClick={(event) => {
                      event.preventDefault();
                      setSearch(`tag:${tag}`);
                    }}
                    className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-700 hover:bg-amber-500/30 dark:text-amber-400"
                  >
                    {tag}
                  </button>
                ))}
              </div>
            )}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
