"use client";

import type { CallDetail } from "@/lib/api/types";
import { formatDuration, formatDurationSpoken } from "@/lib/format";
import { useCall, usePreferences } from "@/lib/query/hooks";
import type { ConnectionStatus, LiveCallState } from "@/lib/live/reducer";
import { useLiveCall } from "@/lib/live/use-live-call";
import { STORAGE_KEYS } from "@/lib/storage";
import { useStoredBoolean } from "@/lib/use-stored";
import { Badge } from "@/components/ui/badge";
import { Button, LinkButton } from "@/components/ui/button";
import { ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Icon } from "@/components/ui/icon";
import { Card, PageHeader, Section } from "@/components/ui/layout";
import { Switch } from "@/components/ui/form";
import { LanguageChip, StateBadge } from "@/components/call/badges";
import { DiagnosticsPanel } from "@/components/call/diagnostics";
import { LiveVoiceStage, useNow } from "@/components/call/live-voice-stage";
import { OwnerControls } from "@/components/call/owner-controls";
import { ClaimSummary, RiskPanel } from "@/components/call/risk-panel";
import { StateStepper } from "@/components/call/state-stepper";
import { Transcript } from "@/components/call/transcript";
import { SimulationBadge } from "@/components/shell/provider-badge";

const CONNECTION_VIEW: Record<ConnectionStatus, { label: string; tone: "success" | "warning" | "neutral" | "danger" | "info" }> = {
  idle: { label: "Not connected", tone: "neutral" },
  connecting: { label: "Connecting", tone: "neutral" },
  open: { label: "Live", tone: "info" },
  reconnecting: { label: "Reconnecting", tone: "warning" },
  closed: { label: "Stream closed", tone: "neutral" },
  failed: { label: "Offline", tone: "danger" },
};

export function ConnectionPill({ live, onReconnect }: { live: LiveCallState; onReconnect: () => void }) {
  const base = CONNECTION_VIEW[live.connection];
  // After the call ends the socket may stay open only to deliver the summary: do not call that "Live".
  const view = live.connection === "open" && live.status !== "active" ? { label: "Connected", tone: "neutral" as const } : base;
  const retrying = live.connection === "reconnecting" || live.connection === "failed";
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="connection-pill" data-connection={live.connection}>
      <Badge tone={view.tone} icon={live.connection === "open" ? "wave" : "refresh"}>
        {view.label}
        {live.connection === "reconnecting" && live.reconnectAttempt > 0 ? ` · attempt ${live.reconnectAttempt}` : ""}
      </Badge>
      {retrying ? (
        <Button variant="secondary" size="sm" onClick={onReconnect}>
          Reconnect now
        </Button>
      ) : null}
    </span>
  );
}

export function CallTimer({ call, live }: { call: CallDetail | null; live: LiveCallState }) {
  const running = live.status === "active" && Boolean(call);
  const now = useNow(running ? 1000 : null);
  const startedAt = call ? Date.parse(call.started_at) : NaN;
  const elapsed = running && !Number.isNaN(startedAt) ? Math.max(0, now - startedAt) : (live.ended?.durationMs ?? call?.duration_ms ?? null);
  return (
    <span className="tabular-nums text-fg" data-testid="call-timer">
      <span className="sr-only">Call duration {formatDurationSpoken(elapsed)}</span>
      <span aria-hidden="true">{formatDuration(elapsed)}</span>
    </span>
  );
}

function EscalationNotice({ live, timeoutS }: { live: LiveCallState; timeoutS: number | undefined }) {
  const escalation = live.escalation;
  const waiting = escalation?.status === "requested" && live.status === "active";
  const created = escalation ? Date.parse(escalation.created_at) : NaN;
  const now = useNow(waiting && timeoutS ? 1000 : null);
  if (!escalation) return null;

  if (waiting) {
    const left = timeoutS && !Number.isNaN(created) ? Math.max(0, Math.ceil(timeoutS - (now - created) / 1000)) : null;
    return (
      <div role="alert" className="rounded-3xl border-2 border-warning bg-warning-bg p-5" data-testid="escalation-banner">
        <p className="flex items-center gap-2 text-lg font-semibold text-fg">
          <Icon name="bell" size={22} className="text-warning" />
          This call may be genuine, and it needs you
        </p>
        <p className="mt-1 text-base text-fg">{escalation.reason}</p>
        {escalation.important_lines.length > 0 ? (
          <ul className="mt-3 space-y-1.5" aria-label="Latest important lines">
            {escalation.important_lines.map((line, index) => (
              <li key={index} className="rounded-xl bg-surface px-3 py-2 text-sm text-fg">
                <q>{line}</q>
              </li>
            ))}
          </ul>
        ) : null}
        <p className="mt-3 text-sm text-fg">
          Choose Take over, Let Sparta continue, or End call below.
          {timeoutS ? (
            <>
              {" "}
              <span className="sr-only">If you do not choose within {timeoutS} seconds, Sparta takes a message.</span>
              <span aria-hidden="true" className="tabular-nums">
                Sparta takes a message in about {left}s.
              </span>
            </>
          ) : null}
        </p>
      </div>
    );
  }

  const text: Record<string, string> = {
    taken_over: "You took over this call.",
    continued: "You asked Sparta to continue handling this call.",
    ended: "The call was ended after the escalation.",
    expired: "You did not answer in time, so Sparta took a message.",
  };
  return (
    <p className="flex items-center gap-2 rounded-2xl bg-raised px-4 py-3 text-sm text-fg" data-testid="escalation-resolved">
      <Icon name="check" size={16} className="text-accent" />
      {text[escalation.status] ?? "The escalation was resolved."}
    </p>
  );
}

function RiskAnnouncer({ live }: { live: LiveCallState }) {
  const level = live.risk?.risk_level;
  return (
    <p className="sr-only" role="status" aria-live="polite" data-testid="risk-announcer">
      {level && level !== "unknown" ? `Risk level is now ${level}.` : ""}
    </p>
  );
}

export function LiveCallView({ callId, initialCall }: { callId: string; initialCall: CallDetail | null }) {
  const { state: live, reconnect } = useLiveCall(callId);
  const prefs = usePreferences();
  const [showTranslation, setShowTranslation] = useStoredBoolean(STORAGE_KEYS.showTranslation, false);
  const call = live.call ?? initialCall;
  const caps = call?.capabilities ?? null;
  const waiting = live.escalation?.status === "requested" && live.status === "active";

  return (
    <div className="space-y-6" data-testid="live-call" data-call-id={callId} data-status={live.status} data-state={live.state ?? ""}>
      <div>
        <LinkButton href="/live" variant="ghost" size="sm" icon="arrow-left" className="-ml-3">
          Live calls
        </LinkButton>
      </div>

      <PageHeader
        eyebrow={live.status === "active" ? "Live call" : "Call ended"}
        title={call?.caller_display ?? "Call"}
        description={
          <span className="flex flex-wrap items-center gap-2">
            {call ? <SimulationBadge simulated={call.simulated} provider={call.provider} /> : null}
            <StateBadge state={live.state ?? call?.state ?? null} />
            <ConnectionPill live={live} onReconnect={reconnect} />
            <span className="text-sm text-muted">
              <CallTimer call={call} live={live} />
            </span>
            {live.language.code ? <LanguageChip code={live.language.code} variant={live.language.profile} confidence={live.language.confidence} /> : null}
          </span>
        }
        actions={
          live.status !== "active" ? (
            <LinkButton href={`/calls/${callId}`} variant="primary" trailingIcon="arrow-right" data-testid="open-detail">
              Open full call detail
            </LinkButton>
          ) : undefined
        }
      />

      <RiskAnnouncer live={live} />
      <EscalationNotice live={live} timeoutS={prefs.data?.escalation.owner_response_timeout_s} />

      {live.status !== "active" && (live.summary ?? call?.summary) ? (
        <Card aria-labelledby="live-summary" data-testid="live-summary">
          <h2 id="live-summary" className="text-lg font-semibold tracking-tight text-fg">
            Summary
          </h2>
          <p className="mt-2 text-lg text-fg">{(live.summary ?? call?.summary)?.text}</p>
        </Card>
      ) : null}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Card>
            <LiveVoiceStage live={live} />
            <div className="mt-6">
              <StateStepper state={live.state} status={live.status} />
            </div>
          </Card>

          <Section title="Who is calling" headingLevel={2}>
            <Card>
              <ClaimSummary claim={live.risk?.caller_claim ?? call?.caller_claim} purpose={live.risk?.purpose ?? call?.purpose} category={live.risk?.category ?? call?.category} />
            </Card>
          </Section>

          <Section title="Your controls">
            <Card>
              <OwnerControls
                callId={callId}
                status={live.status}
                capabilities={caps}
                needsDecision={waiting}
                blocked={call?.blocked}
              />
            </Card>
          </Section>
        </div>

        <div className="space-y-8">
          <Section
            title={live.status === "active" ? "Live transcript" : "Transcript"}
            actions={
              <div className="w-64 max-w-full">
                <Switch checked={showTranslation} onChange={setShowTranslation} label="Show English translation" />
              </div>
            }
          >
            <Card className="p-4 sm:p-5">
              <Transcript
                live
                turns={live.turns}
                partial={live.partial}
                signals={live.risk?.signals ?? []}
                showTranslation={showTranslation}
                empty={<p className="text-sm text-muted">Waiting for the first words. Sparta introduces itself as an AI assistant, then asks who is calling.</p>}
              />
            </Card>
          </Section>

          <Section title="Risk and evidence">
            <Card>
              <RiskPanel risk={live.risk} fallbackLevel={call?.risk_level} fallbackScore={call?.risk_score} fallbackConfidence={call?.confidence} />
            </Card>
          </Section>

          <DiagnosticsPanel live={live} call={call} onReconnect={reconnect} />
        </div>
      </div>
    </div>
  );
}

export function LiveCallScreen({ callId }: { callId: string }) {
  const query = useCall(callId);
  if (query.isPending) return <LoadingBlock label="Loading call" lines={6} />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't open this call" />;
  return <LiveCallView key={callId} callId={callId} initialCall={query.data} />;
}
