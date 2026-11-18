"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { CALL_CATEGORIES, CALL_STATUSES, RISK_LEVELS, type CallCategory, type CallStatus, type RiskLevel } from "@/lib/api/enums";
import type { CallListItem, CallListQuery } from "@/lib/api/types";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/format";
import { categoryLabel, stateLabel } from "@/lib/labels";
import { languageName } from "@/lib/language";
import { useCallsInfinite, useSystemStatus } from "@/lib/query/hooks";
import { riskVisual } from "@/lib/risk";
import { localDateToIso } from "@/lib/format";
import { Button, LinkButton } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/feedback";
import { Field, Select, Switch, TextInput } from "@/components/ui/form";
import { Icon } from "@/components/ui/icon";
import { Card, PageHeader } from "@/components/ui/layout";
import { CallBadges, CallRowHeader, callSummaryText } from "@/components/call/call-row";
import { ClaimSummary } from "@/components/call/risk-panel";
import { useCallActions } from "./use-call-actions";

const RISK_OPTIONS: Array<[RiskLevel, string]> = RISK_LEVELS.map((level) => [level, riskVisual(level).label]);
const SCAM_CATEGORIES = CALL_CATEGORIES.filter((c) => c.startsWith("possible_") || c === "prompt_injection_attempt" || c === "harassment" || c === "telemarketing");
const LEGIT_CATEGORIES = CALL_CATEGORIES.filter((c) => c.startsWith("legitimate_"));
const OTHER_CATEGORIES = CALL_CATEGORIES.filter((c) => !SCAM_CATEGORIES.includes(c) && !LEGIT_CATEGORIES.includes(c));

function isOneOf<T extends string>(values: readonly T[], value: string | null): value is T {
  return value !== null && (values as readonly string[]).includes(value);
}

export function parseFilters(params: URLSearchParams): CallListQuery {
  const risk = params.get("risk_level");
  const category = params.get("category");
  const status = params.get("status");
  const from = params.get("from");
  const to = params.get("to");
  const filters: CallListQuery = {};
  const q = params.get("q")?.trim();
  if (q) filters.q = q;
  if (isOneOf(RISK_LEVELS, risk)) filters.risk_level = risk;
  if (isOneOf(CALL_CATEGORIES, category)) filters.category = category as CallCategory;
  const language = params.get("language");
  if (language && /^[a-z]{2,3}(-[A-Za-z]{2,4})?$/.test(language)) filters.language = language;
  if (isOneOf(CALL_STATUSES, status)) filters.status = status as CallStatus;
  if (params.get("attention") === "1") filters.attention = true;
  if (from && /^\d{4}-\d{2}-\d{2}$/.test(from)) filters.from = localDateToIso(from, "start");
  if (to && /^\d{4}-\d{2}-\d{2}$/.test(to)) filters.to = localDateToIso(to, "end");
  return filters;
}

function activeFilterCount(params: URLSearchParams): number {
  return ["q", "risk_level", "category", "language", "status", "attention", "from", "to"].filter((key) => params.get(key)).length;
}

function HistoryRow({ call }: { call: CallListItem }) {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState<"content" | "call" | null>(null);
  const panelId = useId();
  const { exportCall, deleteContent, deleteCall } = useCallActions();
  const live = call.status === "active";

  return (
    <li
      data-testid="history-row"
      data-call-id={call.id}
      className={cn("rounded-3xl border border-line bg-surface transition-colors", call.owner_attention_required && "border-warning/50")}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start justify-between gap-3 rounded-3xl p-4 text-left hover:bg-raised sm:p-5"
      >
        <span className="min-w-0 space-y-2">
          <CallRowHeader call={call} />
          <span className={cn("block text-base text-fg", !open && "line-clamp-2")}>{callSummaryText(call)}</span>
          <CallBadges call={call} />
        </span>
        <Icon name="chevron-down" size={20} className={cn("mt-1 shrink-0 text-muted transition-transform duration-200", open && "rotate-180")} />
      </button>

      {open ? (
        <div id={panelId} className="space-y-4 border-t border-line p-4 sm:p-5" data-testid="history-details">
          <ClaimSummary claim={call.caller_claim} purpose={call.purpose} category={call.category} />
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-muted">Status</dt>
            <dd className="text-fg">{stateLabel(call.state)}</dd>
            <dt className="text-muted">Duration</dt>
            <dd className="tabular-nums text-fg">{formatDuration(call.duration_ms)}</dd>
            <dt className="text-muted">Action taken</dt>
            <dd className="text-fg">{call.action_taken ? call.action_taken.replace(/_/g, " ") : "None recorded"}</dd>
          </dl>
          <div className="flex flex-wrap gap-2">
            <LinkButton href={live ? `/live/${call.id}` : `/calls/${call.id}`} variant="primary" size="sm" trailingIcon="arrow-right">
              {live ? "Open live view" : "Open call"}
            </LinkButton>
            <Button variant="secondary" size="sm" icon="download" loading={exportCall.isPending} onClick={() => exportCall.mutate(call.id)}>
              Export JSON
            </Button>
            {call.has_content && !live ? (
              <Button variant="danger" size="sm" icon="trash" onClick={() => setConfirm("content")}>
                Delete content
              </Button>
            ) : null}
            {!live ? (
              <Button variant="danger" size="sm" icon="trash" onClick={() => setConfirm("call")}>
                Delete call
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirm === "content"}
        onClose={() => setConfirm(null)}
        title="Delete this call's content?"
        description="The transcript, translations, caller claims and summary text are removed. The time, risk level and category stay so your history still adds up."
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
        onConfirm={() => deleteCall.mutateAsync(call.id)}
      />
    </li>
  );
}

export function HistoryScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { data: status } = useSystemStatus();
  const filters = useMemo(() => parseFilters(new URLSearchParams(params.toString())), [params]);
  const query = useCallsInfinite(filters);
  const active = activeFilterCount(new URLSearchParams(params.toString()));
  const urlQuery = params.get("q") ?? "";
  const [draft, setDraft] = useState(urlQuery);

  // Several filters can change before the router has committed the first new URL (quick keyboard changes, a slow device). Each
  // change builds on the newest URL that was *requested* as long as the committed one has not moved yet, so no change is lost.
  const requested = useRef<{ from: string; to: string } | null>(null);
  const committed = useRef(params);
  useEffect(() => {
    committed.current = params;
  });
  const baseParams = useCallback((): URLSearchParams => {
    const current = committed.current.toString();
    const pending = requested.current;
    return new URLSearchParams(pending && pending.from === current ? pending.to : current);
  }, []);
  const navigate = useCallback(
    (next: URLSearchParams) => {
      const qs = next.toString();
      requested.current = { from: committed.current.toString(), to: qs };
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  function update(patch: Record<string, string | null>) {
    const next = baseParams();
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "") next.delete(key);
      else next.set(key, value);
    }
    navigate(next);
  }

  function clearFilters() {
    setDraft("");
    navigate(new URLSearchParams());
  }

  // Debounced search: the URL (and so the request) updates 300 ms after typing stops.
  useEffect(() => {
    if (draft === urlQuery) return;
    const timer = setTimeout(() => {
      const next = baseParams();
      if (draft.trim()) next.set("q", draft.trim());
      else next.delete("q");
      navigate(next);
    }, 300);
    return () => clearTimeout(timer);
  }, [draft, urlQuery, baseParams, navigate]);

  const calls = query.data?.pages.flatMap((page) => page.items) ?? [];
  const languages = (status?.languages ?? []).filter((l) => l.status === "supported");

  return (
    <div className="space-y-6">
      <PageHeader title="Call history" description="Every call Sparta handled, with a short summary. Open one to see the transcript and the evidence." />

      <Card className="p-4 sm:p-5">
        <form role="search" aria-label="Filter calls" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(event) => event.preventDefault()}>
          <Field label="Search" className="sm:col-span-2 lg:col-span-2">
            {(props) => (
              <div className="relative">
                <Icon name="search" size={18} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
                <TextInput
                  {...props}
                  type="search"
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  placeholder="Caller, organisation, reason or summary"
                  className="pl-10"
                  autoComplete="off"
                />
              </div>
            )}
          </Field>
          <Field label="Risk">
            {(props) => (
              <Select {...props} value={params.get("risk_level") ?? ""} onChange={(event) => update({ risk_level: event.target.value || null })}>
                <option value="">Any risk</option>
                {RISK_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Status">
            {(props) => (
              <Select {...props} value={params.get("status") ?? ""} onChange={(event) => update({ status: event.target.value || null })}>
                <option value="">Any status</option>
                {CALL_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {value.charAt(0).toUpperCase() + value.slice(1)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Category" className="sm:col-span-2">
            {(props) => (
              <Select {...props} value={params.get("category") ?? ""} onChange={(event) => update({ category: event.target.value || null })}>
                <option value="">Any category</option>
                <optgroup label="Warning signs">
                  {SCAM_CATEGORIES.map((value) => (
                    <option key={value} value={value}>
                      {categoryLabel(value)}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="Likely genuine">
                  {LEGIT_CATEGORIES.map((value) => (
                    <option key={value} value={value}>
                      {categoryLabel(value)}
                    </option>
                  ))}
                </optgroup>
                <optgroup label="Other">
                  {OTHER_CATEGORIES.map((value) => (
                    <option key={value} value={value}>
                      {categoryLabel(value)}
                    </option>
                  ))}
                </optgroup>
              </Select>
            )}
          </Field>
          <Field label="Language">
            {(props) => (
              <Select {...props} value={params.get("language") ?? ""} onChange={(event) => update({ language: event.target.value || null })}>
                <option value="">Any language</option>
                {(languages.length > 0 ? languages.map((l) => l.code) : ["en-IN", "hi-IN", "kn-IN"]).map((code) => (
                  <option key={code} value={code}>
                    {languageName(code)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="From">
            {(props) => <TextInput {...props} type="date" value={params.get("from") ?? ""} onChange={(event) => update({ from: event.target.value || null })} />}
          </Field>
          <Field label="To">
            {(props) => <TextInput {...props} type="date" value={params.get("to") ?? ""} onChange={(event) => update({ to: event.target.value || null })} />}
          </Field>
          <div className="flex items-end sm:col-span-2 lg:col-span-1">
            <Switch className="w-full" label="Needs my attention" checked={params.get("attention") === "1"} onChange={(checked) => update({ attention: checked ? "1" : null })} />
          </div>
          {active > 0 ? (
            <div className="flex items-end sm:col-span-2 lg:col-span-1 lg:justify-end">
              <Button variant="secondary" icon="x" onClick={clearFilters}>
                Clear filters ({active})
              </Button>
            </div>
          ) : null}
        </form>
      </Card>

      <div aria-live="polite" className="sr-only" data-testid="history-count">
        {query.isSuccess ? `${calls.length} call${calls.length === 1 ? "" : "s"} shown${query.hasNextPage ? ", more available" : ""}` : ""}
      </div>

      {query.isPending ? <LoadingBlock label="Loading calls" lines={5} /> : null}
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} title="Couldn't load your calls" /> : null}

      {query.isSuccess && calls.length === 0 ? (
        active > 0 ? (
          <EmptyState
            headingLevel={2}
            icon="search"
            title="No calls match these filters"
            description="Try a broader search, a different date range, or clear the filters."
            action={
              <Button variant="primary" onClick={clearFilters}>
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState
            headingLevel={2}
            icon="history"
            title="No calls yet"
            description="When someone calls, Sparta answers as your AI assistant and the summary appears here. Try a simulated call to see how it looks."
            action={
              <LinkButton href="/simulator" variant="primary" icon="flask">
                Run a simulated call
              </LinkButton>
            }
          />
        )
      ) : null}

      {calls.length > 0 ? (
        <>
          <ul className="space-y-3" data-testid="history-list" aria-label="Calls">
            {calls.map((call) => (
              <HistoryRow key={call.id} call={call} />
            ))}
          </ul>
          {query.hasNextPage ? (
            <div className="flex justify-center">
              <Button variant="secondary" loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()} data-testid="load-more">
                Load more
              </Button>
            </div>
          ) : (
            <p className="text-center text-sm text-muted">That&apos;s every call that matches.</p>
          )}
        </>
      ) : null}
    </div>
  );
}
