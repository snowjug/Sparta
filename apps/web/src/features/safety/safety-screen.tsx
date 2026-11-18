"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRef, useState } from "react";
import { newIdempotencyKey } from "@/lib/api/client";
import { fieldErrors } from "@/lib/api/errors";
import { useApi } from "@/lib/api/provider";
import type { AuditEntry, BlockedCaller, RetentionPolicy, SafetyEvent, TrustedCaller, UserPreferences } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { actionLabel, categoryLabel, signalLabel, SEVERITY_LABELS } from "@/lib/labels";
import {
  useAudit,
  useBlockedCallers,
  usePreferences,
  useSafetyEvents,
  useSafetyPolicies,
  useTrustedCallers,
  useVoiceStatus,
} from "@/lib/query/hooks";
import { qk } from "@/lib/query/keys";
import { severityTone } from "@/lib/risk";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Field, RangeField, Switch, TextInput } from "@/components/ui/form";
import { Icon } from "@/components/ui/icon";
import { Card, Disclosure, PageHeader, Section } from "@/components/ui/layout";
import { useToast } from "@/components/ui/toast";
import { RiskBadge } from "@/components/call/badges";

// ------------------------------------------------------------------------------------------ policy explanations

function ProtectedInformation() {
  const policy = useSafetyPolicies();
  return (
    <Section title="What Sparta never shares" description="Sparta refuses to give out or confirm any of these, however the caller asks, however urgent it sounds, and whoever they claim to be.">
      {policy.isPending ? <LoadingBlock label="Loading the protected list" lines={3} /> : null}
      {policy.isError ? <ErrorState error={policy.error} onRetry={() => void policy.refetch()} title="Couldn't load the safety policy" /> : null}
      {policy.data ? (
        <Card>
          <ul className="flex flex-wrap gap-2" aria-label="Protected information" data-testid="protected-list">
            {policy.data.protected_information.map((item) => (
              <li key={item.code}>
                <Badge tone="accent" icon="lock">
                  {item.label}
                </Badge>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-sm text-muted">
            Safety policy <span className="font-mono text-xs text-fg">{policy.data.name}</span> · version <span className="tabular-nums text-fg">{policy.data.version}</span>. The rules are fixed and reviewed; Sparta never changes them on its own.
          </p>
        </Card>
      ) : null}
    </Section>
  );
}

function PromptInjection() {
  const policy = useSafetyPolicies();
  if (!policy.data) return null;
  const { summary, examples } = policy.data.prompt_injection;
  return (
    <Section title="When a caller tries to talk Sparta out of its rules" description="Sometimes a caller says things meant to trick an AI assistant. This is what that means, in plain words.">
      <Card data-testid="prompt-injection">
        <p className="text-pretty text-base text-fg">{summary}</p>
        {examples.length > 0 ? (
          <>
            <h3 className="mb-2 mt-4 text-sm font-semibold text-fg">Things a caller might say</h3>
            <ul className="space-y-2">
              {examples.map((example, index) => (
                <li key={index} className="rounded-2xl bg-raised px-4 py-2 text-sm text-fg">
                  <q>{example}</q>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        <p className="mt-4 flex items-start gap-2 text-sm text-muted">
          <Icon name="shield-check" size={16} className="mt-0.5 shrink-0 text-accent" />
          Everything a caller says is treated as untrusted text to read, never as an instruction to follow. Sparta flags the attempt and ends the call.
        </p>
      </Card>
    </Section>
  );
}

function SignalCatalog() {
  const policy = useSafetyPolicies();
  if (!policy.data) return null;
  return (
    <Disclosure summary={`What Sparta looks for (${policy.data.signals.length} signals)`} className="bg-surface">
      <ul className="divide-y divide-line">
        {policy.data.signals.map((signal) => (
          <li key={signal.code} className="flex flex-wrap items-start justify-between gap-2 py-2.5">
            <div className="min-w-0">
              <p className="text-sm font-medium text-fg">{signalLabel(signal.code)}</p>
              <p className="text-sm text-muted">{signal.description}</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Badge tone={severityTone(signal.severity, signal.kind)}>{signal.kind === "legitimate" ? "Genuine sign" : SEVERITY_LABELS[signal.severity]}</Badge>
              {signal.protected ? (
                <Badge tone="accent" icon="lock">
                  Protected
                </Badge>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}

// ------------------------------------------------------------------------------------------------ safety events

function SafetyEvents() {
  const events = useSafetyEvents(20);
  return (
    <Section title="Recent safety events" description="Never includes what was said: only when, how risky, what kind, and what Sparta did.">
      {events.isPending ? <LoadingBlock label="Loading safety events" lines={3} /> : null}
      {events.isError ? <ErrorState error={events.error} onRetry={() => void events.refetch()} title="Couldn't load safety events" /> : null}
      {events.data && events.data.length === 0 ? <EmptyState icon="shield-check" title="No safety events yet" description="When a call shows warning signs, it is listed here." /> : null}
      {events.data && events.data.length > 0 ? (
        <ul className="space-y-2" data-testid="safety-events">
          {events.data.map((event, index) => (
            <EventRow key={`${event.call_id}-${event.at}-${index}`} event={event} />
          ))}
        </ul>
      ) : null}
    </Section>
  );
}

function EventRow({ event }: { event: SafetyEvent }) {
  return (
    <li className="rounded-2xl border border-line bg-surface p-4" data-testid="safety-event">
      <div className="flex flex-wrap items-center gap-2">
        <RiskBadge level={event.risk_level} />
        <span className="text-sm font-medium text-fg">{categoryLabel(event.category)}</span>
        {event.action ? <Badge tone="accent">{actionLabel(event.action)}</Badge> : null}
        <time dateTime={event.at} className="ml-auto text-sm tabular-nums text-muted">
          {formatDateTime(event.at)}
        </time>
      </div>
      {event.signal_codes.length > 0 ? (
        <p className="mt-2 flex flex-wrap gap-1.5">
          {event.signal_codes.map((code) => (
            <Badge key={code} tone="neutral">
              {signalLabel(code)}
            </Badge>
          ))}
        </p>
      ) : null}
      <Link href={`/calls/${event.call_id}`} className="mt-2 inline-flex min-h-11 items-center text-sm font-semibold text-fg underline underline-offset-4">
        Open the call
      </Link>
    </li>
  );
}

// ---------------------------------------------------------------------------------------- blocked / trusted lists

type ListKind = "blocked" | "trusted";

function CallerLists({ kind }: { kind: ListKind }) {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const blocked = useBlockedCallers();
  const trusted = useTrustedCallers();
  const list = kind === "blocked" ? blocked : trusted;
  const [number, setNumber] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const key = useRef(newIdempotencyKey());

  const add = useMutation<BlockedCaller | TrustedCaller, Error>({
    mutationFn: async () =>
      kind === "blocked"
        ? await api.safety.addBlocked({ number: number.trim(), reason: note.trim() || undefined }, { idempotencyKey: key.current })
        : await api.safety.addTrusted({ number: number.trim(), label: note.trim() || undefined }, { idempotencyKey: key.current }),
    onSuccess: (entry) => {
      key.current = newIdempotencyKey();
      setNumber("");
      setNote("");
      setErrors({});
      void queryClient.invalidateQueries({ queryKey: kind === "blocked" ? qk.blocked : qk.trusted });
      toast.success(`${entry.number_display} was ${kind === "blocked" ? "blocked" : "added to your trusted callers"}.`, {
        title: kind === "blocked" ? "Caller blocked" : "Caller trusted",
      });
    },
    onError: (error) => setErrors(fieldErrors(error, "number")),
  });

  const remove = useMutation({
    mutationFn: (id: string) => (kind === "blocked" ? api.safety.removeBlocked(id) : api.safety.removeTrusted(id)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: kind === "blocked" ? qk.blocked : qk.trusted });
      toast.success(kind === "blocked" ? "Unblocked." : "No longer trusted.");
    },
  });

  const title = kind === "blocked" ? "Blocked callers" : "Trusted callers";
  const description =
    kind === "blocked"
      ? "Calls from these numbers are refused. Sparta shows a masked number and keeps a fingerprint to match future calls."
      : "Trusted callers follow your trusted-contact setting in Assistant Studio (by default they ring straight through).";
  const items: Array<BlockedCaller | TrustedCaller> = list.data ?? [];

  return (
    <Section title={title} description={description}>
      <Card className="space-y-5" data-testid={`${kind}-card`}>
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (number.trim()) add.mutate();
          }}
        >
          <Field label="Phone number" error={errors.number} hint="Only used to match future calls. It is not shown again.">
            {(props) => (
              <TextInput {...props} type="tel" inputMode="tel" autoComplete="off" value={number} onChange={(event) => setNumber(event.target.value)} placeholder="+91 98765 43210" maxLength={32} />
            )}
          </Field>
          <Field label={kind === "blocked" ? "Reason (optional)" : "Label (optional)"} error={errors.reason ?? errors.label}>
            {(props) => <TextInput {...props} autoComplete="off" value={note} maxLength={kind === "blocked" ? 200 : 80} onChange={(event) => setNote(event.target.value)} />}
          </Field>
          <div className="sm:col-span-2">
            <Button type="submit" variant="primary" icon="plus" loading={add.isPending} disabled={number.trim().length < 3}>
              {kind === "blocked" ? "Block number" : "Trust number"}
            </Button>
          </div>
        </form>

        {list.isPending ? <LoadingBlock label={`Loading ${title.toLowerCase()}`} lines={2} /> : null}
        {list.isError ? <ErrorState error={list.error} onRetry={() => void list.refetch()} /> : null}
        {list.data && items.length === 0 ? <p className="text-sm text-muted">{kind === "blocked" ? "You have not blocked anyone." : "You have not trusted anyone yet."}</p> : null}
        {items.length > 0 ? (
          <ul className="divide-y divide-line" aria-label={title} data-testid={`${kind}-list`}>
            {items.map((entry) => (
              <li key={entry.id} className="flex flex-wrap items-center justify-between gap-3 py-3" data-testid={`${kind}-item`}>
                <div className="min-w-0">
                  <p className="text-base font-semibold text-fg">{entry.number_display}</p>
                  <p className="text-sm text-muted">
                    {"reason" in entry ? entry.reason : (entry as TrustedCaller).label}
                    {("reason" in entry ? entry.reason : (entry as TrustedCaller).label) ? " · " : ""}
                    <time dateTime={entry.created_at}>{formatDateTime(entry.created_at)}</time>
                  </p>
                </div>
                <Button variant="secondary" size="sm" icon="trash" loading={remove.isPending && remove.variables === entry.id} onClick={() => remove.mutate(entry.id)} aria-label={`Remove ${entry.number_display}`}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>
    </Section>
  );
}

// ------------------------------------------------------------------------------------------- retention and deletion

function Retention() {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const prefs = usePreferences();
  const [draft, setDraft] = useState<RetentionPolicy | null>(null);
  const saved = prefs.data?.retention;
  const value = draft ?? saved;
  const dirty = Boolean(draft && saved && JSON.stringify(draft) !== JSON.stringify(saved));

  const save = useMutation({
    mutationFn: () => api.preferences.put({ ...(prefs.data as UserPreferences), retention: draft as RetentionPolicy }),
    onSuccess: (next) => {
      queryClient.setQueryData(qk.preferences, next);
      setDraft(null);
      toast.success("Retention settings saved. Older content is removed by the retention job.", { title: "Retention updated" });
    },
  });

  return (
    <Section title="Data retention" description="Sparta keeps as little as possible. Raw call audio is never stored.">
      <Card className="space-y-4" data-testid="retention-card">
        {prefs.isPending ? <LoadingBlock label="Loading retention settings" lines={3} /> : null}
        {prefs.isError ? <ErrorState error={prefs.error} onRetry={() => void prefs.refetch()} /> : null}
        {value ? (
          <>
            <Switch
              checked={value.store_transcripts}
              onChange={(checked) => setDraft({ ...value, store_transcripts: checked })}
              label="Keep call transcripts"
              description="Off: Sparta still saves the one-sentence summary, risk level and category."
            />
            <RangeField
              label="Delete transcripts after"
              value={value.transcript_retention_days}
              min={0}
              max={365}
              step={1}
              onChange={(transcript_retention_days) => setDraft({ ...value, transcript_retention_days })}
              format={(days) => (days === 0 ? "Immediately after the call" : `${days} day${days === 1 ? "" : "s"}`)}
            />
            <RangeField
              label="Delete summaries after"
              value={value.summary_retention_days}
              min={1}
              max={730}
              step={1}
              onChange={(summary_retention_days) => setDraft({ ...value, summary_retention_days })}
              format={(days) => `${days} day${days === 1 ? "" : "s"}`}
            />
            <Switch checked={false} disabled onChange={() => {}} label="Store raw call audio" description="Not available. Sparta does not store raw audio in this release." />
            <Switch
              checked={value.store_full_caller_number}
              onChange={(checked) => setDraft({ ...value, store_full_caller_number: checked })}
              label="Keep the full caller number (encrypted)"
              description="Off by default. Even when on, the app only ever shows a masked number."
            />
            {dirty ? (
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" icon="check" loading={save.isPending} onClick={() => save.mutate()}>
                  Save retention settings
                </Button>
                <Button variant="secondary" onClick={() => setDraft(null)}>
                  Discard
                </Button>
              </div>
            ) : null}
          </>
        ) : null}
      </Card>
    </Section>
  );
}

function DeleteData() {
  const api = useApi();
  const queryClient = useQueryClient();
  const toast = useToast();
  const voice = useVoiceStatus();
  const [confirm, setConfirm] = useState<"calls" | "voice" | null>(null);

  const deleteAll = useMutation({
    mutationFn: () => api.calls.removeAll(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.callsRoot });
      void queryClient.invalidateQueries({ queryKey: qk.home });
      void queryClient.invalidateQueries({ queryKey: ["safety"] });
      toast.success("All your call content was deleted.", { title: "Call content deleted" });
    },
  });
  const deleteVoice = useMutation({
    mutationFn: () => api.voice.remove(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.voiceStatus });
      toast.success("Your personal voice record was deleted.", { title: "Voice deleted" });
    },
  });

  const enrolled = voice.data && voice.data.status !== "not_enrolled" && voice.data.status !== "deleted";

  return (
    <Section title="Delete my data" description="These actions are permanent.">
      <Card className="space-y-4" data-testid="delete-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-base font-semibold text-fg">Delete all call content</p>
            <p className="text-sm text-muted">Removes every transcript, translation, claim and summary text. Times, risk levels and categories stay.</p>
          </div>
          <Button variant="danger" icon="trash" onClick={() => setConfirm("calls")} data-testid="delete-all-content">
            Delete all call content
          </Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <div className="min-w-0">
            <p className="text-base font-semibold text-fg">Delete my personal voice</p>
            <p className="text-sm text-muted">{enrolled ? "Removes your consent record and any voice created for you." : "No personal voice is enrolled, so there is nothing to delete."}</p>
          </div>
          <Button variant="danger" icon="trash" disabled={!enrolled} onClick={() => setConfirm("voice")} data-testid="delete-voice">
            Delete personal voice
          </Button>
        </div>
      </Card>
      <ConfirmDialog
        open={confirm === "calls"}
        onClose={() => setConfirm(null)}
        title="Delete all call content?"
        description="Every transcript, translation, caller claim and summary text is removed for good. This cannot be undone."
        confirmLabel="Delete everything"
        tone="danger"
        requireText="delete"
        onConfirm={() => deleteAll.mutateAsync()}
      />
      <ConfirmDialog
        open={confirm === "voice"}
        onClose={() => setConfirm(null)}
        title="Delete your personal voice?"
        description="Sparta goes back to a predefined voice. You can enrol again later with fresh consent."
        confirmLabel="Delete voice"
        tone="danger"
        onConfirm={() => deleteVoice.mutateAsync()}
      />
    </Section>
  );
}

// -------------------------------------------------------------------------------------------------------- audit log

function detailText(detail: AuditEntry["detail"]): string {
  if (!detail) return "";
  return Object.entries(detail)
    .filter(([, value]) => value !== null && value !== undefined && typeof value !== "object")
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value)}`)
    .join(" · ");
}

function AuditLog() {
  const audit = useAudit(50);
  return (
    <Disclosure summary="Audit log of sensitive actions" className="bg-surface">
      {audit.isPending ? <LoadingBlock label="Loading the audit log" lines={3} /> : null}
      {audit.isError ? <ErrorState error={audit.error} onRetry={() => void audit.refetch()} /> : null}
      {audit.data && audit.data.length === 0 ? <p className="text-sm text-muted">Nothing recorded yet.</p> : null}
      {audit.data && audit.data.length > 0 ? (
        <ul className="divide-y divide-line" data-testid="audit-list">
          {audit.data.map((entry, index) => (
            <li key={`${entry.at}-${index}`} className="py-2.5">
              <p className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <span className="font-medium text-fg">{entry.action.replace(/[._]/g, " ")}</span>
                <time dateTime={entry.at} className="tabular-nums text-muted">
                  {formatDateTime(entry.at)}
                </time>
              </p>
              <p className="text-sm text-muted">
                {entry.target_type}
                {entry.target_id ? ` · ${entry.target_id}` : ""}
                {detailText(entry.detail) ? ` · ${detailText(entry.detail)}` : ""}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-3 text-xs text-muted">The audit log records what happened, never what was said.</p>
    </Disclosure>
  );
}

export function SafetyScreen() {
  return (
    <div className="space-y-10">
      <PageHeader
        title="Safety Center"
        description="See what Sparta protects, what it noticed, who you have blocked or trusted, and how your data is kept. You are always in control."
      />
      <div className="grid gap-10 xl:grid-cols-2">
        <div className="space-y-10">
          <ProtectedInformation />
          <PromptInjection />
          <SignalCatalog />
          <SafetyEvents />
        </div>
        <div className="space-y-10">
          <CallerLists kind="blocked" />
          <CallerLists kind="trusted" />
          <Retention />
          <DeleteData />
          <AuditLog />
        </div>
      </div>
    </div>
  );
}
