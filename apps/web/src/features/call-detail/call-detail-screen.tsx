"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { FEEDBACK_KINDS, type FeedbackKind } from "@/lib/api/enums";
import { newIdempotencyKey } from "@/lib/api/client";
import { useApi } from "@/lib/api/provider";
import type { CallDetail, TimelineEntry, TimelineKind } from "@/lib/api/types";
import { formatDateTime, formatDuration } from "@/lib/format";
import { FEEDBACK_LABELS, actionLabel, stateLabel, timelineDetail, timelineLabel } from "@/lib/labels";
import { useBlockedCallers, useCall, useTrustedCallers } from "@/lib/query/hooks";
import { qk } from "@/lib/query/keys";
import { STORAGE_KEYS } from "@/lib/storage";
import { useStoredBoolean } from "@/lib/use-stored";
import { Badge } from "@/components/ui/badge";
import { Button, LinkButton } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { CopyButton, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Field, Switch, TextInput } from "@/components/ui/form";
import { Icon, type IconName } from "@/components/ui/icon";
import { Card, DefinitionRow, PageHeader, Section } from "@/components/ui/layout";
import { useToast } from "@/components/ui/toast";
import { LanguageList, RiskBadge, StateBadge } from "@/components/call/badges";
import { RiskPanel } from "@/components/call/risk-panel";
import { Transcript } from "@/components/call/transcript";
import { SimulationBadge } from "@/components/shell/provider-badge";
import { useCallActions } from "@/features/history/use-call-actions";

const TIMELINE_ICON: Record<TimelineKind, IconName> = {
  state: "wave",
  owner_action: "user",
  escalation: "bell",
  risk: "shield",
  language: "language",
  provider: "cpu",
  system: "info",
};

const TIMELINE_KIND_LABEL: Record<TimelineKind, string> = {
  state: "Conversation step",
  owner_action: "Owner action",
  escalation: "Escalation",
  risk: "Risk assessment",
  language: "Language",
  provider: "Provider",
  system: "System",
};

export function TimelineList({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) return <p className="text-sm text-muted">No timeline entries.</p>;
  return (
    <ol className="relative space-y-4 border-l border-line pl-6" aria-label="Action timeline" data-testid="timeline">
      {entries.map((entry, index) => (
        <li key={`${entry.at}-${index}`} className="relative" data-kind={entry.kind}>
          <span className="absolute -left-[2.15rem] flex size-7 items-center justify-center rounded-full border border-line bg-surface text-muted">
            <Icon name={TIMELINE_ICON[entry.kind] ?? "info"} size={14} />
          </span>
          <p className="text-sm font-medium text-fg">
            <span className="sr-only">{TIMELINE_KIND_LABEL[entry.kind]}: </span>
            {timelineLabel(entry)}
          </p>
          {entry.detail ? <p className="text-sm text-muted">{timelineDetail(entry.detail)}</p> : null}
          <time dateTime={entry.at} className="text-xs tabular-nums text-muted">
            {new Intl.DateTimeFormat(undefined, { timeStyle: "medium" }).format(new Date(entry.at))}
          </time>
        </li>
      ))}
    </ol>
  );
}

function FeedbackPanel({ call }: { call: CallDetail }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [note, setNote] = useState("");
  const keys = useRef<Partial<Record<FeedbackKind, string>>>({});
  const submitted = new Set(call.feedback.map((f) => f.kind));
  const kinds = FEEDBACK_KINDS.filter((kind) => kind !== "trust_caller" && kind !== "block_caller");

  const send = useMutation({
    mutationFn: (kind: FeedbackKind) => {
      keys.current[kind] ??= newIdempotencyKey();
      return api.calls.feedback(call.id, kind, note.trim() || undefined, { idempotencyKey: keys.current[kind] });
    },
    onSuccess: (_record, kind) => {
      delete keys.current[kind];
      setNote("");
      toast.success(`Saved: “${FEEDBACK_LABELS[kind]}”. Feedback is stored apart from the call record and never retrains Sparta on its own.`, { title: "Thanks for the feedback" });
      void queryClient.invalidateQueries({ queryKey: qk.call(call.id) });
      void queryClient.invalidateQueries({ queryKey: qk.callsRoot });
      void queryClient.invalidateQueries({ queryKey: qk.home });
    },
  });

  return (
    <div className="space-y-3" data-testid="feedback-panel">
      <p className="text-sm text-muted">Was Sparta right? Your answer is stored separately from the call and is never used to retrain Sparta automatically.</p>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Feedback on this call">
        {kinds.map((kind) => {
          const done = submitted.has(kind);
          return (
            <Button
              key={kind}
              variant={done ? "primary" : "secondary"}
              size="sm"
              icon={done ? "check" : undefined}
              aria-pressed={done}
              loading={send.isPending && send.variables === kind}
              onClick={() => {
                if (!done) send.mutate(kind);
              }}
              data-testid={`feedback-${kind}`}
            >
              {FEEDBACK_LABELS[kind]}
            </Button>
          );
        })}
      </div>
      <Field label="Add a note (optional)" hint="Sent with your next feedback. Avoid personal details.">
        {(props) => <TextInput {...props} value={note} maxLength={280} onChange={(event) => setNote(event.target.value)} />}
      </Field>
    </div>
  );
}

function CallerPanel({ call }: { call: CallDetail }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const blocked = useBlockedCallers();
  const trusted = useTrustedCallers();
  const blockEntry = blocked.data?.find((entry) => entry.source_call_id === call.id);
  const trustEntry = trusted.data?.find((entry) => entry.source_call_id === call.id);
  const blockKey = useRef(newIdempotencyKey());
  const trustKey = useRef(newIdempotencyKey());

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: qk.call(call.id) });
    void queryClient.invalidateQueries({ queryKey: qk.callsRoot });
    void queryClient.invalidateQueries({ queryKey: qk.blocked });
    void queryClient.invalidateQueries({ queryKey: qk.trusted });
  };

  const block = useMutation({
    mutationFn: () => api.calls.block(call.id, undefined, { idempotencyKey: blockKey.current }),
    onSuccess: () => {
      blockKey.current = newIdempotencyKey();
      toast.success("Blocked. Future calls from this number are refused.", { title: "Caller blocked" });
      refresh();
    },
  });
  const trust = useMutation({
    mutationFn: () => api.calls.trust(call.id, undefined, { idempotencyKey: trustKey.current }),
    onSuccess: () => {
      trustKey.current = newIdempotencyKey();
      toast.success("Trusted. Calls from this number follow your trusted-contact setting.", { title: "Caller trusted" });
      refresh();
    },
  });
  const unblock = useMutation({
    mutationFn: () => api.safety.removeBlocked(blockEntry!.id),
    onSuccess: () => {
      toast.success("Unblocked.", { title: "Caller unblocked" });
      refresh();
    },
  });
  const untrust = useMutation({
    mutationFn: () => api.safety.removeTrusted(trustEntry!.id),
    onSuccess: () => {
      toast.success("Trust removed.", { title: "Caller no longer trusted" });
      refresh();
    },
  });

  return (
    <div className="space-y-3" data-testid="caller-panel">
      <p className="text-sm text-muted">
        Only the masked number <strong className="font-semibold text-fg">{call.caller_display}</strong> is shown. Blocking and trusting use a keyed fingerprint of the number, not the number itself.
      </p>
      <div className="flex flex-wrap gap-2">
        {call.trusted ? (
          <>
            <Badge tone="success" icon="user-check">
              Trusted caller
            </Badge>
            {trustEntry ? (
              <Button variant="secondary" size="sm" loading={untrust.isPending} onClick={() => untrust.mutate()}>
                Remove trust
              </Button>
            ) : null}
          </>
        ) : (
          <Button variant="secondary" size="sm" icon="user-check" loading={trust.isPending} onClick={() => trust.mutate()} data-testid="trust-caller">
            Trust this caller
          </Button>
        )}
        {call.blocked ? (
          <>
            <Badge tone="neutral" icon="ban">
              Blocked caller
            </Badge>
            {blockEntry ? (
              <Button variant="secondary" size="sm" loading={unblock.isPending} onClick={() => unblock.mutate()}>
                Unblock
              </Button>
            ) : null}
          </>
        ) : (
          <Button variant="secondary" size="sm" icon="ban" loading={block.isPending} onClick={() => block.mutate()} data-testid="block-caller">
            Block this caller
          </Button>
        )}
      </div>
    </div>
  );
}

function DataPanel({ call }: { call: CallDetail }) {
  const router = useRouter();
  const { exportCall, downloadReport, deleteContent, deleteCall } = useCallActions();
  const [confirm, setConfirm] = useState<"content" | "call" | null>(null);
  const active = call.status === "active";

  return (
    <div className="space-y-4" data-testid="data-panel">
      <dl>
        <DefinitionRow label="Diagnostic trace ID" mono>
          <span data-testid="trace-id" className="break-all">
            {call.trace_id || "—"}
          </span>
        </DefinitionRow>
      </dl>
      <div className="flex flex-wrap gap-2">
        {call.trace_id ? <CopyButton text={call.trace_id} label="Copy trace ID" /> : null}
        <Button variant="secondary" size="sm" icon="download" loading={downloadReport.isPending} onClick={() => downloadReport.mutate(call.id)} data-testid="download-report">
          Diagnostic report
        </Button>
        <Button variant="secondary" size="sm" icon="download" loading={exportCall.isPending} onClick={() => exportCall.mutate(call.id)} data-testid="export-call">
          Export JSON
        </Button>
      </div>
      <p className="text-sm text-muted">
        The diagnostic report has no transcript text and no phone numbers. The export contains everything about this call and is only for you.
      </p>
      <div className="flex flex-wrap gap-2 border-t border-line pt-4">
        {call.has_content ? (
          <Button variant="danger" size="sm" icon="trash" disabled={active} onClick={() => setConfirm("content")} data-testid="delete-content">
            Delete content
          </Button>
        ) : null}
        <Button variant="danger" size="sm" icon="trash" disabled={active} onClick={() => setConfirm("call")} data-testid="delete-call">
          Delete call
        </Button>
      </div>
      {active ? <p className="text-sm text-muted">Deletion is available once the call has ended.</p> : null}

      <ConfirmDialog
        open={confirm === "content"}
        onClose={() => setConfirm(null)}
        title="Delete this call's content?"
        description="The transcript, translations, caller claims and summary text are removed. The time, risk level and category stay."
        confirmLabel="Delete content"
        tone="danger"
        onConfirm={() => deleteContent.mutateAsync(call.id)}
      />
      <ConfirmDialog
        open={confirm === "call"}
        onClose={() => setConfirm(null)}
        title="Delete this call completely?"
        description="The call disappears from your history. This cannot be undone."
        confirmLabel="Delete call"
        tone="danger"
        onConfirm={async () => {
          await deleteCall.mutateAsync(call.id);
          router.push("/calls");
        }}
      />
    </div>
  );
}

export function CallDetailView({ call }: { call: CallDetail }) {
  const [showTranslation, setShowTranslation] = useStoredBoolean(STORAGE_KEYS.showTranslation, false);
  const live = call.status === "active";

  return (
    <div className="space-y-6" data-testid="call-detail" data-call-id={call.id}>
      <div>
        <LinkButton href="/calls" variant="ghost" size="sm" icon="arrow-left" className="-ml-3">
          Call history
        </LinkButton>
      </div>

      <PageHeader
        eyebrow="Call"
        title={call.caller_display}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <SimulationBadge simulated={call.simulated} provider={call.provider} />
            <RiskBadge level={call.risk_level} />
            <StateBadge state={call.state} />
            <LanguageList languages={call.languages} profile={call.language_profile} />
          </span>
        }
        actions={
          live ? (
            <LinkButton href={`/live/${call.id}`} variant="primary" icon="wave">
              Open live view
            </LinkButton>
          ) : undefined
        }
      />

      <Card aria-labelledby="summary-heading" data-testid="summary-card">
        <h2 id="summary-heading" className="text-lg font-semibold tracking-tight text-fg">
          Summary
        </h2>
        {call.summary ? (
          <>
            <p className="mt-2 text-pretty text-lg text-fg" data-testid="summary-text">
              {call.summary.text}
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
              {call.summary.action_taken ? <Badge tone="accent">{actionLabel(call.summary.action_taken)}</Badge> : null}
              <Badge tone={call.summary.owner_action_required ? "warning" : "neutral"} icon={call.summary.owner_action_required ? "bell" : "check"}>
                {call.summary.owner_action_required ? "Needs your decision" : "No action needed from you"}
              </Badge>
            </div>
          </>
        ) : (
          <p className="mt-2 text-base text-muted">
            {!call.has_content
              ? "This call's content was deleted, so there is no summary. The time, risk level and category are kept."
              : live
                ? "A summary is created when the call ends."
                : "No summary was created for this call."}
          </p>
        )}
        <dl className="mt-4 grid grid-cols-1 gap-x-8 sm:grid-cols-2">
          <DefinitionRow label="Started">{formatDateTime(call.started_at)}</DefinitionRow>
          <DefinitionRow label="Duration">{formatDuration(call.duration_ms)}</DefinitionRow>
          <DefinitionRow label="Outcome">{stateLabel(call.state)}</DefinitionRow>
          <DefinitionRow label="Action taken">{call.action_taken ? call.action_taken.replace(/_/g, " ") : "None recorded"}</DefinitionRow>
        </dl>
        {call.capabilities.audio_note ? (
          <p className="mt-3 flex items-start gap-2 text-sm text-muted">
            <Icon name="info" size={16} className="mt-0.5 shrink-0" />
            {call.capabilities.audio_note}
          </p>
        ) : null}
      </Card>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-8">
          <Section
            title="Transcript"
            description={call.has_content ? "In the order it was said. Warning signs are underlined and labelled." : undefined}
            actions={
              call.has_content ? (
                <div className="w-64 max-w-full">
                  <Switch checked={showTranslation} onChange={setShowTranslation} label="Show English translation" />
                </div>
              ) : undefined
            }
          >
            {call.has_content ? (
              <Card className="p-4 sm:p-5">
                <Transcript turns={call.turns} signals={call.risk?.signals ?? []} showTranslation={showTranslation} />
              </Card>
            ) : (
              <Card className="text-base text-muted">The transcript was deleted. Only timestamps, risk level and category remain.</Card>
            )}
          </Section>

          <Section title="What happened" description="Each step Sparta took, with the time it happened.">
            <Card>
              <TimelineList entries={call.timeline} />
            </Card>
          </Section>
        </div>

        <div className="space-y-8">
          <Section title="Risk and evidence">
            <Card>
              <RiskPanel risk={call.risk} fallbackLevel={call.risk_level} fallbackScore={call.risk_score} fallbackConfidence={call.confidence} />
            </Card>
          </Section>
          <Section title="Your feedback">
            <Card>
              <FeedbackPanel call={call} />
            </Card>
          </Section>
          <Section title="This caller">
            <Card>
              <CallerPanel call={call} />
            </Card>
          </Section>
          <Section title="Data and diagnostics">
            <Card>
              <DataPanel call={call} />
            </Card>
          </Section>
        </div>
      </div>
    </div>
  );
}

export function CallDetailScreen({ callId }: { callId: string }) {
  const query = useCall(callId);
  if (query.isPending) return <LoadingBlock label="Loading call" lines={6} />;
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't load this call" />;
  }
  return <CallDetailView call={query.data} />;
}
