import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Paperclip, Send } from "lucide-react";

import { sendReply } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function ReplyBox({ number }: { number: string }) {
  const [body, setBody] = useState("");
  const [mediaUrl, setMediaUrl] = useState("");
  const [showMedia, setShowMedia] = useState(false);

  const reply = useMutation({
    mutationFn: () =>
      sendReply(number, {
        body,
        media_urls: mediaUrl.trim() ? [mediaUrl.trim()] : [],
      }),
    onSuccess: () => {
      setBody("");
      setMediaUrl("");
      setShowMedia(false);
    },
  });

  const canSend = (body.trim() || mediaUrl.trim()) && !reply.isPending;

  return (
    <form
      className="flex flex-col gap-2 border-t p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSend) reply.mutate();
      }}
    >
      {showMedia && (
        <Input
          placeholder="Media URL (simulates an MMS attachment)"
          value={mediaUrl}
          onChange={(event) => setMediaUrl(event.target.value)}
        />
      )}
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          title="Attach media URL"
          onClick={() => setShowMedia((value) => !value)}
        >
          <Paperclip />
        </Button>
        <Input
          placeholder={`Reply as ${number}…`}
          value={body}
          onChange={(event) => setBody(event.target.value)}
        />
        <Button type="submit" disabled={!canSend}>
          <Send />
          Send
        </Button>
      </div>
      {reply.isError && (
        <p className="text-xs text-destructive">
          Failed to send reply: {(reply.error as Error).message}
        </p>
      )}
    </form>
  );
}
