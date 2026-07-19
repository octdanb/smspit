import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";

import { fetchVerifications } from "@/api/client";
import { CopyChip } from "@/components/copy-chip";
import { Badge } from "@/components/ui/badge";

const statusVariant = (
  status: string,
): "default" | "secondary" | "destructive" | "outline" => {
  if (status === "approved") return "default";
  if (status === "pending") return "secondary";
  return "destructive";
};

export function VerificationsPanel({ number }: { number: string }) {
  const verifications = useQuery({
    queryKey: ["verifications", number],
    queryFn: () => fetchVerifications(number),
  });

  const items = verifications.data ?? [];
  if (items.length === 0) return null;

  return (
    <div className="border-b bg-muted/30 px-4 py-2">
      <p className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground">
        <ShieldCheck className="size-3.5" />
        Verify verifications
      </p>
      <div className="flex flex-col gap-1">
        {items.slice(0, 3).map((verification) => (
          <div
            key={verification.sid}
            className="flex flex-wrap items-center gap-2 text-xs"
          >
            <span className="text-muted-foreground">
              {verification.service_name}
            </span>
            <CopyChip value={verification.code} />
            <Badge variant={statusVariant(verification.status)}>
              {verification.status}
            </Badge>
            {verification.status === "pending" && (
              <span className="text-muted-foreground">
                {verification.check_attempts}/5 checks · expires in{" "}
                {Math.ceil(verification.expires_in_seconds / 60)}m
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
