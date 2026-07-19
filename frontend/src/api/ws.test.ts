import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { handleWsEvent } from "./ws";

describe("handleWsEvent", () => {
  it("invalidates numbers and the affected thread on message.created", () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    handleWsEvent(queryClient, {
      type: "message.created",
      data: { number: "+15551234567", message: {} },
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["numbers"] });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["thread", "+15551234567"],
    });
  });

  it("invalidates all threads when everything is cleared", () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    handleWsEvent(queryClient, {
      type: "messages.cleared",
      data: { number: null },
    });

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["numbers"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["thread"] });
  });

  it("ignores unknown event types", () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    handleWsEvent(queryClient, { type: "something.else", data: {} });

    expect(invalidate).not.toHaveBeenCalled();
  });
});
