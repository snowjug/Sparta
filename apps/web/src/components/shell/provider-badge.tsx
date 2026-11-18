"use client";

import { useSystemStatus } from "@/lib/query/hooks";
import { describeError } from "@/lib/api/errors";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/feedback";

const PROVIDER_NAMES: Record<string, string> = {
  simulator: "Simulator",
  azure: "Azure",
  android_screening: "Android screening",
  other: "Other provider",
};

export function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider;
}

/** REAL vs SIMULATED, always explicit. `simulated` comes from /system/status or CallDetail. */
export function SimulationBadge({ simulated, provider, className }: { simulated: boolean; provider?: string; className?: string }) {
  if (simulated) {
    return (
      <Badge tone="info" icon="flask" strong className={className} title="No real phone call or audio is involved">
        Simulated
      </Badge>
    );
  }
  return (
    <Badge tone="accent" icon="phone" strong className={className} title="A real telephony provider is handling this call">
      Real{provider ? ` · ${providerName(provider)}` : ""}
    </Badge>
  );
}

/** Active telephony provider for the whole app. */
export function SystemProviderBadge({ className }: { className?: string }) {
  const { data, isPending, error } = useSystemStatus();
  if (isPending) return <Skeleton className={`h-6 w-24 ${className ?? ""}`} />;
  if (error || !data) {
    return (
      <Badge tone="warning" icon="alert" strong className={className} title={describeError(error).message}>
        API offline
      </Badge>
    );
  }
  return (
    <span className="inline-flex items-center gap-2">
      <SimulationBadge simulated={data.telephony.simulated} provider={data.telephony.provider} className={className} />
      <span className="sr-only">
        Telephony provider: {providerName(data.telephony.provider)}.{" "}
        {data.telephony.simulated ? "Calls are simulated; no real phone call is involved." : "Real phone calls are handled by this provider."}
      </span>
    </span>
  );
}
