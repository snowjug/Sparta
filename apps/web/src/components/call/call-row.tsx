import Link from "next/link";
import type { CallListItem } from "@/lib/api/types";
import { formatDuration, formatRelative } from "@/lib/format";
import { categoryLabel } from "@/lib/labels";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/badge";
import { Icon } from "@/components/ui/icon";
import { SimulationBadge } from "@/components/shell/provider-badge";
import { LanguageList, RiskBadge, StateBadge } from "./badges";

/** Summary text, or an honest reason why there is none. */
export function callSummaryText(call: CallListItem): string {
  if (call.summary_text) return call.summary_text;
  if (!call.has_content) return "Call content was deleted. Only the time, risk level and category are kept.";
  if (call.status === "active") return "This call is in progress.";
  if (call.mode === "screening_only") return "Screened on the phone. Native screening cannot listen to the call, so there is no transcript.";
  return "No summary was created for this call.";
}

export function CallBadges({ call, showState = false }: { call: CallListItem; showState?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <RiskBadge level={call.risk_level} />
      {call.category !== "unknown" ? <Badge tone="neutral">{categoryLabel(call.category)}</Badge> : null}
      {showState ? <StateBadge state={call.state} /> : null}
      {call.owner_attention_required ? (
        <Badge tone="warning" icon="bell">
          Needs you
        </Badge>
      ) : null}
      {call.blocked ? (
        <Badge tone="neutral" icon="ban">
          Blocked
        </Badge>
      ) : null}
      {call.trusted ? (
        <Badge tone="success" icon="user-check">
          Trusted
        </Badge>
      ) : null}
      <LanguageList languages={call.languages} profile={call.language_profile} />
    </div>
  );
}

export function CallRowHeader({ call }: { call: CallListItem }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="text-base font-semibold text-fg" data-testid="caller-display">
        {call.caller_display}
      </span>
      <SimulationBadge simulated={call.simulated} provider={call.provider} />
      <span className="text-sm tabular-nums text-muted">
        <time dateTime={call.started_at}>{formatRelative(call.started_at)}</time>
        {call.duration_ms !== null ? ` · ${formatDuration(call.duration_ms)}` : call.status === "active" ? " · live" : ""}
      </span>
    </div>
  );
}

/** A call as a link row (Home). */
export function CallLinkRow({ call, href, className }: { call: CallListItem; href?: string; className?: string }) {
  const target = href ?? (call.status === "active" ? `/live/${call.id}` : `/calls/${call.id}`);
  return (
    <li>
      <Link
        href={target}
        data-testid="call-row"
        className={cn(
          "group block rounded-3xl border border-line bg-surface p-4 transition-colors hover:bg-raised sm:p-5",
          call.owner_attention_required && "border-warning/50",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-2">
            <CallRowHeader call={call} />
            <p className="line-clamp-2 text-base text-fg">{callSummaryText(call)}</p>
            <CallBadges call={call} />
          </div>
          <Icon name="chevron-right" size={20} className="mt-1 shrink-0 text-muted transition-transform group-hover:translate-x-0.5" />
        </div>
      </Link>
    </li>
  );
}
