import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send, Trash2, X } from "lucide-react";

import {
  deleteMessage,
  fetchMessageDetail,
  releaseMessage,
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

  const release = useMutation({ mutationFn: () => releaseMessage(sid) });

  return (
    <aside
      data-testid="message-detail"
      className="fixed inset-0 z-50 flex flex-col overflow-y-auto bg-background md:static md:z-auto md:w-96 md:shrink-0 md:border-l md:bg-muted/20"
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
            <h4 className="mb-1 font-medium">Encoding check</h4>
            <p className="text-muted-foreground">
              {detail.data.encoding_check.encoding} ·{" "}
              {detail.data.encoding_check.length} chars ·{" "}
              {detail.data.encoding_check.num_segments} segment
              {detail.data.encoding_check.num_segments === 1 ? "" : "s"}
            </p>
            {detail.data.encoding_check.non_gsm_chars.length > 0 && (
              <div className="mt-1 space-y-1">
                <p className="text-muted-foreground">
                  Characters forcing UCS-2:{" "}
                  {detail.data.encoding_check.non_gsm_chars
                    .slice(0, 10)
                    .map((c) => `"${c.char}" (pos ${c.index})`)
                    .join(", ")}
                </p>
                {detail.data.encoding_check.smart_encoding_segments <
                  detail.data.encoding_check.num_segments && (
                  <p className="text-amber-600 dark:text-amber-400">
                    SmartEncoded=true would use{" "}
                    {detail.data.encoding_check.smart_encoding_would_use} (
                    {detail.data.encoding_check.smart_encoding_segments} segment
                    {detail.data.encoding_check.smart_encoding_segments === 1
                      ? ""
                      : "s"}
                    )
                  </p>
                )}
              </div>
            )}
          </section>
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
          <div className="flex flex-col gap-2">
            <Button
              variant="outline"
              size="sm"
              title="Re-send this message through REAL Twilio (allowlisted recipients only)"
              onClick={() => release.mutate()}
              disabled={release.isPending}
            >
              <Send />
              Release via real Twilio
            </Button>
            {release.isSuccess && release.data.released && (
              <p className="text-emerald-600 dark:text-emerald-400">
                Released to {release.data.to}
                {release.data.real_sid ? ` (${release.data.real_sid})` : ""}.
              </p>
            )}
            {release.isSuccess && !release.data.released && (
              <p className="text-destructive">
                Release failed:{" "}
                {release.data.error ??
                  `real Twilio returned ${release.data.response_status}`}
              </p>
            )}
            {release.isError && (
              <p className="text-destructive">
                {(release.error as Error).message}
              </p>
            )}
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
        </div>
      )}
    </aside>
  );
}
