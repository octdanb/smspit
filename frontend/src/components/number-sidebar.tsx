import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Search } from "lucide-react";

import { fetchNumbers } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function NumberSidebar() {
  const [search, setSearch] = useState("");
  // Kept fresh by WebSocket-driven invalidation (see api/ws.ts).
  const numbers = useQuery({ queryKey: ["numbers"], queryFn: fetchNumbers });

  const filtered = (numbers.data ?? []).filter(
    (entry) =>
      entry.number.toLowerCase().includes(search.toLowerCase()) ||
      entry.last_message.body.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <aside className="flex w-80 shrink-0 flex-col border-r">
      <div className="relative border-b p-3">
        <Search className="pointer-events-none absolute left-6 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search numbers or messages…"
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
              <span className="truncate font-medium">{entry.number}</span>
              <Badge variant="secondary">{entry.message_count}</Badge>
            </div>
            <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
              <span className="truncate">
                {entry.last_message.body || "(no body)"}
              </span>
              <span className="shrink-0 text-xs">
                {relativeTime(entry.last_message.date_created)}
              </span>
            </div>
          </Link>
        ))}
      </nav>
    </aside>
  );
}
