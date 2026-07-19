import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, X } from "lucide-react";

import {
  deleteMessage,
  fetchMessageDetail,
  setMessageTags,
} from "@/api/client";
import { CopyChip } from "@/components/copy-chip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function MessageDetail({
  sid,
  onClose,
}: {
  sid: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const detail = useQuery({
    queryKey: ["message-detail", sid],
    queryFn: () => fetchMessageDetail(sid),
  });

  const [tagsDraft, setTagsDraft] = useState("");
  useEffect(() => {
    if (detail.data) setTagsDraft(detail.data.message.tags.join(", "));
  }, [detail.data]);

  const saveTags = useMutation({
    mutationFn: () =>
      setMessageTags(
        sid,
        tagsDraft
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      ),
  });

  const remove = useMutation({
    mutationFn: () => deleteMessage(sid),
    onSuccess: () => {
      queryClient.invalidateQueries();
      onClose();
    },
  });

  return (
    <aside
      data-testid="message-detail"
      className="flex w-96 shrink-0 flex-col overflow-y-auto border-l bg-muted/20"
    >
      <header className="flex items-center justify-between border-b px-3 py-2">
        <h3 className="text-sm font-semibold">Message detail</h3>
        <Button variant="ghost" size="icon" onClick={onClose} title="Close">
          <X />
        </Button>
      </header>
      {detail.data && (
        <div className="flex flex-col gap-3 p-3 text-xs">
          <div className="flex items-center gap-2">
            <CopyChip value={detail.data.message.sid} />
          </div>
          <label className="grid gap-1">
            <span className="font-medium">Tags (comma-separated)</span>
            <div className="flex gap-1">
              <Input
                className="h-8 text-xs"
                value={tagsDraft}
                placeholder="otp, smoke-test"
                onChange={(event) => setTagsDraft(event.target.value)}
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => saveTags.mutate()}
                disabled={saveTags.isPending}
              >
                Save
              </Button>
            </div>
          </label>
          <section>
            <h4 className="mb-1 font-medium">Twilio resource</h4>
            <pre className="max-h-64 overflow-auto rounded bg-background p-2">
              {JSON.stringify(detail.data.twilio, null, 2)}
            </pre>
          </section>
          <section>
            <h4 className="mb-1 font-medium">Original request params</h4>
            <pre className="max-h-40 overflow-auto rounded bg-background p-2">
              {JSON.stringify(detail.data.raw_params, null, 2)}
            </pre>
          </section>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
          >
            <Trash2 />
            Delete message
          </Button>
        </div>
      )}
    </aside>
  );
}
