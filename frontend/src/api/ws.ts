import { useEffect, useState } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

export interface WsEvent {
  type: string;
  data: Record<string, unknown>;
}

export type LiveStatus = "connecting" | "live" | "offline";

/** Map a server event onto TanStack Query cache invalidations. */
export function handleWsEvent(queryClient: QueryClient, event: WsEvent): void {
  const number =
    typeof event.data.number === "string" ? event.data.number : null;

  switch (event.type) {
    case "message.created":
    case "message.status_changed":
      queryClient.invalidateQueries({ queryKey: ["numbers"] });
      if (number) {
        queryClient.invalidateQueries({ queryKey: ["thread", number] });
        queryClient.invalidateQueries({ queryKey: ["latest-code", number] });
      }
      break;
    case "verification.created":
    case "verification.updated":
      if (number) {
        queryClient.invalidateQueries({ queryKey: ["verifications", number] });
      }
      break;
    case "messages.cleared":
      queryClient.invalidateQueries({ queryKey: ["numbers"] });
      // number === null means everything was cleared.
      queryClient.invalidateQueries({
        queryKey: number ? ["thread", number] : ["thread"],
      });
      break;
    case "webhook.delivered":
      queryClient.invalidateQueries({ queryKey: ["webhook-log"] });
      break;
    case "optout.changed":
      queryClient.invalidateQueries({ queryKey: ["numbers"] });
      if (number) {
        queryClient.invalidateQueries({ queryKey: ["thread", number] });
      }
      break;
    case "tags.changed":
      queryClient.invalidateQueries({ queryKey: ["numbers"] });
      queryClient.invalidateQueries({ queryKey: ["tags"] });
      if (number) {
        queryClient.invalidateQueries({ queryKey: ["thread", number] });
        queryClient.invalidateQueries({ queryKey: ["message-detail"] });
      }
      break;
  }
}

/**
 * Keep a WebSocket open to /api/ws and invalidate query caches on events.
 * Reconnects with backoff; a fresh connection re-syncs everything in case
 * events were missed while offline.
 */
export function useLiveUpdates(): LiveStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>("connecting");

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: number | undefined;
    let stopped = false;
    let retryDelay = 1000;

    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const token = localStorage.getItem("smspit-token");
      const suffix = token ? `?token=${encodeURIComponent(token)}` : "";
      socket = new WebSocket(`${protocol}://${location.host}/api/ws${suffix}`);
      socket.onopen = () => {
        setStatus("live");
        retryDelay = 1000;
        queryClient.invalidateQueries();
      };
      socket.onmessage = (event) => {
        handleWsEvent(queryClient, JSON.parse(event.data as string) as WsEvent);
      };
      socket.onclose = () => {
        if (stopped) return;
        setStatus("offline");
        timer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [queryClient]);

  return status;
}
