"use client";

import { useSystemStatus } from "@/lib/query/hooks";
import { describeError } from "@/lib/api/errors";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/feedback";

const PROVIDER_NAMES: Record<string, string> = {
  simulator: "Simulator",
  azure: "Azure",
  asterisk: "Asterisk",
  android_screening: "Android screening",
  other: "Other provider",
};

export function providerName(provider: string): string {
  return PROVIDER_NAMES[provider] ?? provider;
}

const CONNECTION_NAMES: Record<string, string> = {
  simulated: "Simulated",
  local_sip: "Local SIP",
  pstn: "Phone network",
};

const PSTN_NAMES: Record<string, string> = {
  not_applicable: "Not applicable",
  not_configured: "Not configured",
  provider: "Through the provider",
};

const TAKEOVER_NAMES: Record<string, string> = {
  none: "Not available",
  simulated: "Simulated",
  phone_number: "Your phone number",
  sip_extension: "SIP extension",
};

/** How calls reach Sparta (`TelephonyView.connection`): Simulated, Local SIP or Phone network. */
export function connectionName(connection: string): string {
  return CONNECTION_NAMES[connection] ?? connection;
}

/** Whether ordinary phone numbers can reach Sparta (`TelephonyView.pstn`). */
export function pstnName(pstn: string): string {
  return PSTN_NAMES[pstn] ?? pstn;
}

/** What Take over does with this provider (`TelephonyView.takeover`). */
export function takeoverName(takeover: string): string {
  return TAKEOVER_NAMES[takeover] ?? takeover;
}

/** Voice over IP on a trusted network, with no phone-network (PSTN) connection. Call lists carry no `connection`, so the provider decides there. */
export function isLocalSip(provider?: string, connection?: string): boolean {
  return connection !== undefined ? connection === "local_sip" : provider === "asterisk";
}

/** What a speech provider's meta name means to an owner: `local-piper` is Local, `azure-speech` Azure, `fake-tone` a test double. */
function speechProviderName(provider: string): string {
  const name = provider.trim().toLowerCase();
  if (name === "") return "Unknown";
  if (name === "simulator") return "Simulated";
  if (/^local(-|$)/.test(name)) return "Local";
  if (/^azure(-|$)/.test(name)) return "Azure";
  if (/^fake(-|$)/.test(name)) return "Fake (test)";
  return provider;
}

/** One value for "Speech": the shared name when hearing and speaking agree, otherwise both. */
export function speechName(stt: string, tts: string): string {
  const hearing = speechProviderName(stt);
  const speaking = speechProviderName(tts);
  return hearing === speaking ? hearing : `Hearing: ${hearing} · Speaking: ${speaking}`;
}

/** REAL vs SIMULATED, always explicit. `simulated` comes from /system/status or CallDetail. Local SIP is never called "Real". */
export function SimulationBadge({
  simulated,
  provider,
  connection,
  className,
}: {
  simulated: boolean;
  provider?: string;
  connection?: string;
  className?: string;
}) {
  if (simulated) {
    return (
      <Badge tone="info" icon="flask" strong className={className} title="No real phone call or audio is involved">
        Simulated
      </Badge>
    );
  }
  if (isLocalSip(provider, connection)) {
    return (
      <Badge
        tone="accent"
        icon="phone"
        strong
        className={className}
        title="Calls reach Sparta over SIP on your local network. Ordinary phone numbers cannot call it this way."
      >
        Local SIP
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
  const { telephony } = data;
  return (
    <span className="inline-flex items-center gap-2">
      <SimulationBadge simulated={telephony.simulated} provider={telephony.provider} connection={telephony.connection} className={className} />
      <span className="sr-only">
        Telephony provider: {providerName(telephony.provider)}.{" "}
        {telephony.simulated
          ? "Calls are simulated; no real phone call is involved."
          : isLocalSip(telephony.provider, telephony.connection)
            ? "Calls arrive over local SIP from phones on your network. Ordinary phone numbers cannot reach Sparta."
            : "Real phone calls are handled by this provider."}
      </span>
    </span>
  );
}
