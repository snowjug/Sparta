"use client";

import { useProviders } from "@/lib/query/hooks";
import type { ProviderOption } from "@/lib/api/types";
import { Badge } from "@/components/ui/badge";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Icon } from "@/components/ui/icon";

const KIND_LABEL: Record<ProviderOption["kind"], string> = {
  telephony: "Telephony",
  stt: "Speech to text",
  tts: "Text to speech",
  llm: "Reasoning",
};

/** Which providers are configured and active. Providers are chosen by server configuration, not in the browser. */
export function ProviderList() {
  const providers = useProviders();
  if (providers.isPending) return <LoadingBlock label="Loading providers" lines={3} />;
  if (providers.isError) return <ErrorState error={providers.error} onRetry={() => void providers.refetch()} title="Couldn't load the providers" />;
  const kinds = (Object.keys(KIND_LABEL) as Array<ProviderOption["kind"]>).filter((kind) => providers.data.some((p) => p.kind === kind));
  return (
    <div className="space-y-4" data-testid="provider-list">
      <p className="flex items-start gap-2 text-sm text-muted">
        <Icon name="info" size={16} className="mt-0.5 shrink-0" />
        Providers are selected by server configuration (for example TELEPHONY_PROVIDER), so this list shows what is active and what is missing.
      </p>
      {kinds.map((kind) => (
        <section key={kind} aria-label={KIND_LABEL[kind]}>
          <h3 className="mb-2 text-sm font-semibold text-fg">{KIND_LABEL[kind]}</h3>
          <ul className="space-y-2">
            {providers.data
              .filter((provider) => provider.kind === kind)
              .map((provider) => (
                <li key={provider.id} className="rounded-2xl border border-line bg-raised p-3" data-testid="provider-item" data-active={provider.active}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium text-fg">{provider.label}</span>
                    <Badge tone={provider.active ? "accent" : "neutral"} icon={provider.active ? "check" : undefined}>
                      {provider.active ? "Active" : "Not active"}
                    </Badge>
                    <Badge tone={provider.available ? "neutral" : "warning"}>{provider.available ? "Available" : "Not configured"}</Badge>
                    {provider.simulated ? (
                      <Badge tone="info" icon="flask">
                        Simulated
                      </Badge>
                    ) : null}
                  </div>
                  {provider.reason ? <p className="mt-1 text-sm text-muted">{provider.reason}</p> : null}
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
