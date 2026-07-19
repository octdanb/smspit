import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ThreadMessage } from "@/api/client";
import { MessageBubble } from "./message-bubble";

function makeMessage(overrides: Partial<ThreadMessage> = {}): ThreadMessage {
  return {
    sid: "SM" + "a".repeat(32),
    direction: "outbound-api",
    from_number: "+15557654321",
    to_number: "+15551234567",
    body: "hello world",
    status: "queued",
    error_code: null,
    error_message: null,
    num_segments: 1,
    num_media: 0,
    encoding: "gsm7",
    channel: "sms",
    media: [],
    tags: [],
    date_created: "2026-07-19T09:00:00Z",
    date_sent: null,
    date_updated: "2026-07-19T09:00:00Z",
    ...overrides,
  };
}

describe("MessageBubble", () => {
  it("renders body and status", () => {
    render(<MessageBubble message={makeMessage()} />);
    expect(screen.getByText("hello world")).toBeInTheDocument();
    expect(screen.getByText("queued")).toBeInTheDocument();
  });

  it("shows segment info for multi-segment messages", () => {
    render(
      <MessageBubble
        message={makeMessage({ num_segments: 3, encoding: "ucs2" })}
      />,
    );
    expect(screen.getByText("3 segments (ucs2)")).toBeInTheDocument();
  });

  it("shows an error badge when the message failed", () => {
    render(
      <MessageBubble
        message={makeMessage({ status: "undelivered", error_code: 30007 })}
      />,
    );
    expect(screen.getByText("error 30007")).toBeInTheDocument();
  });
});
