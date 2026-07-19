import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";

import {
  clearAllMessages,
  fetchSettings,
  updateSettings,
  type SettingsData,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export const Route = createFileRoute("/settings")({
  component: SettingsPage,
});

function SettingsPage() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: fetchSettings });
  const [draft, setDraft] = useState<Partial<SettingsData>>({});

  useEffect(() => {
    if (settings.data) setDraft(settings.data);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => updateSettings(draft),
    onSuccess: (data) => {
      queryClient.setQueryData(["settings"], data);
      setDraft(data);
    },
  });

  const clearAll = useMutation({
    mutationFn: clearAllMessages,
    onSuccess: () => queryClient.invalidateQueries(),
  });

  if (!settings.data) {
    return (
      <p className="p-6 text-sm text-muted-foreground">
        {settings.isError ? "Failed to load settings." : "Loading…"}
      </p>
    );
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4 p-6">
      <Card>
        <CardHeader>
          <CardTitle>Webhooks</CardTitle>
          <CardDescription>
            Where simulated inbound messages are delivered (phase 5). Webhooks
            are signed with the auth token below.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <label className="grid gap-1.5 text-sm">
            Inbound webhook URL
            <Input
              placeholder="https://localhost:3000/sms/inbound"
              value={draft.inbound_webhook_url ?? ""}
              onChange={(e) =>
                setDraft({
                  ...draft,
                  inbound_webhook_url: e.target.value || null,
                })
              }
            />
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="grid gap-1.5 text-sm">
              Account SID
              <Input
                value={draft.account_sid ?? ""}
                onChange={(e) =>
                  setDraft({ ...draft, account_sid: e.target.value })
                }
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              Auth token (signs webhooks)
              <Input
                value={draft.auth_token ?? ""}
                onChange={(e) =>
                  setDraft({ ...draft, auth_token: e.target.value })
                }
              />
            </label>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Delivery simulation</CardTitle>
          <CardDescription>
            Messages advance queued → sending → sent → delivered, firing status
            callbacks along the way.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={draft.simulate_delivery ?? true}
              onChange={(e) =>
                setDraft({ ...draft, simulate_delivery: e.target.checked })
              }
            />
            Simulate delivery lifecycle
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="grid gap-1.5 text-sm">
              Delay between statuses (ms)
              <Input
                type="number"
                min={0}
                value={draft.status_delay_ms ?? 300}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    status_delay_ms: Number(e.target.value),
                  })
                }
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              Random failure rate (0–1)
              <Input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={draft.failure_rate ?? 0}
                onChange={(e) =>
                  setDraft({ ...draft, failure_rate: Number(e.target.value) })
                }
              />
            </label>
          </div>
          <p className="text-xs text-muted-foreground">
            Deterministic failures: PUT /api/settings with forced_rules, e.g.{" "}
            <code className="rounded bg-muted px-1">
              {
                '{"forced_rules": [{"to_suffix": "0000", "status": "undelivered", "error_code": 30007}]}'
              }
            </code>
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Strict mode</CardTitle>
          <CardDescription>
            Permissive by default. Turn these on to validate like real Twilio
            and test your app's error handling (real Twilio error codes).
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={draft.strict_auth ?? false}
              onChange={(e) =>
                setDraft({ ...draft, strict_auth: e.target.checked })
              }
            />
            Validate credentials (wrong SID/token → 401 / 20003)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={draft.strict_validation ?? false}
              onChange={(e) =>
                setDraft({ ...draft, strict_validation: e.target.checked })
              }
            />
            Validate numbers (bad To → 21211, bad From → 21212, landline per
            Lookup overrides → 21614)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={draft.enforce_optouts ?? false}
              onChange={(e) =>
                setDraft({ ...draft, enforce_optouts: e.target.checked })
              }
            />
            Enforce opt-outs (send to STOPped number → 21610)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="size-4"
              checked={draft.trial_mode ?? false}
              onChange={(e) =>
                setDraft({ ...draft, trial_mode: e.target.checked })
              }
            />
            Trial mode (sends only to verified numbers, otherwise 21608)
          </label>
          <div className="grid grid-cols-2 gap-4">
            <label className="grid gap-1.5 text-sm">
              Verified numbers (comma-separated)
              <Input
                placeholder="+64211234567, +15551234567"
                value={(draft.verified_numbers ?? []).join(", ")}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    verified_numbers: e.target.value
                      .split(",")
                      .map((value) => value.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
            <label className="grid gap-1.5 text-sm">
              Rate limit per minute (0 = off, over → 429 / 20429)
              <Input
                type="number"
                min={0}
                value={draft.rate_limit_per_minute ?? 0}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    rate_limit_per_minute: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center justify-between">
        <Button
          variant="destructive"
          onClick={() => clearAll.mutate()}
          disabled={clearAll.isPending}
        >
          Clear all messages
        </Button>
        <div className="flex items-center gap-3">
          {save.isSuccess && (
            <span className="text-xs text-muted-foreground">Saved.</span>
          )}
          <Button onClick={() => save.mutate()} disabled={save.isPending}>
            Save settings
          </Button>
        </div>
      </div>
    </div>
  );
}
