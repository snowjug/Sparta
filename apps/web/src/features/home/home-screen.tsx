"use client";

import { useHome, useMe } from "@/lib/query/hooks";
import type { HomeSummary, ProtectionStatus } from "@/lib/api/types";
import { formatMinutes } from "@/lib/format";
import { safeRoute } from "@/lib/routes";
import { Badge, type Tone } from "@/components/ui/badge";
import { LinkButton } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Icon, type IconName } from "@/components/ui/icon";
import { Card, PageHeader, Section } from "@/components/ui/layout";
import { CallLinkRow } from "@/components/call/call-row";
import { SimulationBadge } from "@/components/shell/provider-badge";

const PROTECTION: Record<ProtectionStatus, { label: string; tone: Tone; icon: IconName }> = {
  active: { label: "Protection on", tone: "accent", icon: "shield-check" },
  attention: { label: "Needs your attention", tone: "warning", icon: "bell" },
  degraded: { label: "Not screening right now", tone: "danger", icon: "alert" },
  setup_needed: { label: "Setup needed", tone: "info", icon: "sliders" },
};

function Stat({ label, value, icon }: { label: string; value: string | number; icon: IconName }) {
  return (
    <li className="flex items-center gap-3">
      <span aria-hidden="true" className="flex size-10 shrink-0 items-center justify-center rounded-full bg-raised text-muted">
        <Icon name={icon} size={20} />
      </span>
      <p className="flex min-w-0 flex-col-reverse">
        <span className="mt-1 text-sm text-muted">{label}</span>
        <span className="text-2xl font-semibold leading-none tabular-nums text-fg">{value}</span>
      </p>
    </li>
  );
}

function ProtectionCard({ data }: { data: HomeSummary }) {
  const { protection } = data;
  const view = PROTECTION[protection.status];
  return (
    <Card aria-labelledby="protection-heading" data-testid="protection-card">
      <div className="flex items-start gap-4">
        <span className="flex size-16 shrink-0 items-center justify-center rounded-full border-2 border-line-strong bg-accent-soft text-accent">
          <Icon name={view.icon} size={30} />
        </span>
        <div className="min-w-0">
          <Badge tone={view.tone} icon={view.icon} strong>
            {view.label}
          </Badge>
          <h2 id="protection-heading" className="mt-2 text-balance text-xl font-semibold tracking-tight text-fg sm:text-2xl">
            {protection.headline}
          </h2>
          <p className="mt-1 text-pretty text-base text-muted">{protection.detail}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <SimulationBadge simulated={protection.simulated} provider={protection.provider} />
            {!protection.live_calls_supported ? (
              <Badge tone="neutral" icon="phone">
                Real phone calls not connected
              </Badge>
            ) : null}
          </div>
        </div>
      </div>
    </Card>
  );
}

export function HomeScreen() {
  const { data: me } = useMe();
  const home = useHome();
  const data = home.data;

  return (
    <div className="space-y-8">
      <PageHeader title={me ? `Hello, ${me.display_name}` : "Hello"} description="Your calls, handled by an AI assistant that always says it is an AI." />

      {home.isPending ? <LoadingBlock label="Loading your protection status" lines={4} /> : null}
      {home.isError ? <ErrorState error={home.error} onRetry={() => void home.refetch()} title="Couldn't load your home screen" /> : null}

      {data ? (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-8">
            <ProtectionCard data={data} />

            {data.next_action.kind !== "none" ? (
              <Card className="flex flex-wrap items-center justify-between gap-4" aria-label="Next step" data-testid="next-action">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">Next step</p>
                  <p className="mt-1 text-lg font-semibold text-fg">{data.next_action.label}</p>
                </div>
                <LinkButton href={safeRoute(data.next_action.route)} variant="primary" trailingIcon="arrow-right">
                  {data.next_action.label}
                </LinkButton>
              </Card>
            ) : (
              <p className="flex items-center gap-2 rounded-2xl bg-raised px-4 py-3 text-base text-muted" data-testid="all-caught-up">
                <Icon name="check" size={18} className="text-accent" />
                You are all caught up.
              </p>
            )}

            {data.attention.length > 0 ? (
              <Section title="Needs you" description="Calls Sparta could not decide alone.">
                <ul className="space-y-3" data-testid="attention-list">
                  {data.attention.map((call) => (
                    <CallLinkRow key={call.id} call={call} />
                  ))}
                </ul>
              </Section>
            ) : null}

            <Section
              title="Recent calls"
              description="The last five, each with a one-sentence summary."
              actions={
                data.recent.length > 0 ? (
                  <LinkButton href="/calls" variant="ghost" size="sm" trailingIcon="arrow-right">
                    All calls
                  </LinkButton>
                ) : undefined
              }
            >
              {data.recent.length === 0 ? (
                <EmptyState
                  icon="flask"
                  title="No calls yet"
                  description="Run a simulated scam call to watch Sparta screen it live. No real phone call is involved."
                  action={
                    <LinkButton href="/simulator" variant="primary" icon="play">
                      Open the Simulator Lab
                    </LinkButton>
                  }
                />
              ) : (
                <ul className="space-y-3" data-testid="recent-list">
                  {data.recent.map((call) => (
                    <CallLinkRow key={call.id} call={call} />
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <aside aria-label="Today" className="space-y-6">
            <Card aria-labelledby="today-heading" data-testid="today-card">
              <h2 id="today-heading" className="text-lg font-semibold tracking-tight text-fg">
                Today
              </h2>
              <ul className="mt-4 grid grid-cols-2 gap-x-4 gap-y-5 lg:grid-cols-1" aria-label="Today's counters">
                <Stat label="Calls handled" value={data.today.handled} icon="phone" />
                <Stat label="High-risk calls" value={data.today.high_risk} icon="shield" />
                <Stat label="Escalated to you" value={data.today.escalations} icon="bell" />
                <Stat label="Spam ended" value={data.today.ended_spam} icon="ban" />
              </ul>
              <p className="mt-4 text-sm tabular-nums text-muted">{formatMinutes(data.today.minutes_handled)} minutes of calls handled</p>
            </Card>
          </aside>
        </div>
      ) : null}
    </div>
  );
}
