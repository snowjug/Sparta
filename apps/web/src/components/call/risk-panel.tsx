"use client";

import { useRef } from "react";
import type { RiskLevel } from "@/lib/api/enums";
import type { CallerClaim, RiskAssessment, RiskSignal } from "@/lib/api/types";
import { formatPercent } from "@/lib/format";
import { actionLabel, categoryLabel, SEVERITY_LABELS, signalLabel } from "@/lib/labels";
import { profileLabel } from "@/lib/language";
import { riskMeterFill, riskVisual, severityTone } from "@/lib/risk";
import { useCssVar } from "@/lib/use-css-var";
import { Badge } from "@/components/ui/badge";
import { RiskBadge } from "./badges";

/** Horizontal meter. The fill is a transform driven by a CSS variable, and the level is always spelled out in text. */
export function RiskMeter({ level, score, confidence }: { level: RiskLevel; score: number | null | undefined; confidence: number | null | undefined }) {
  const visual = riskVisual(level);
  const fill = riskMeterFill(level, score);
  const ref = useRef<HTMLDivElement>(null);
  useCssVar(ref, "--fill", fill);
  const valueText =
    visual.level === "unknown"
      ? "Not enough evidence yet"
      : `${visual.label}. Risk score ${formatPercent(score)}. Confidence ${formatPercent(confidence)}.`;

  return (
    <div data-testid="risk-meter" data-risk={visual.level}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <RiskBadge level={level} />
        <span className="text-sm tabular-nums text-muted">
          {visual.level === "unknown" ? "No score yet" : `Score ${formatPercent(score)} · Confidence ${formatPercent(confidence)}`}
        </span>
      </div>
      <div
        role="meter"
        aria-label="Risk score"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(fill * 100)}
        aria-valuetext={valueText}
        className="mt-3 h-2.5 overflow-hidden rounded-full bg-sunken ring-1 ring-line"
      >
        <div ref={ref} className="sp-meter-fill h-full w-full rounded-full" data-risk={visual.level} />
      </div>
      <div aria-hidden="true" className="mt-1 flex justify-between text-xs text-muted">
        <span>Low</span>
        <span>Caution</span>
        <span>High</span>
      </div>
      <p className="mt-2 text-sm text-muted">{visual.description}</p>
    </div>
  );
}

function turnNumber(id: string): string {
  const match = /(\d+)$/.exec(id);
  return match ? match[1]! : id;
}

export function SignalList({ signals }: { signals: RiskSignal[] }) {
  if (signals.length === 0) {
    return <p className="text-sm text-muted">No warning signs or legitimacy signs so far.</p>;
  }
  return (
    <ul className="space-y-2" aria-label="Evidence signals">
      {signals.map((signal, index) => {
        const legitimate = signal.kind === "legitimate";
        return (
          <li key={`${signal.code}-${index}`} className="rounded-2xl border border-line bg-raised p-3" data-testid="signal-item" data-signal={signal.code}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={severityTone(signal.severity, signal.kind)} icon={legitimate ? "check" : "alert"}>
                {legitimate ? "Sign of a genuine call" : `${SEVERITY_LABELS[signal.severity]} signal`}
              </Badge>
              <span className="text-sm font-medium text-fg">{signalLabel(signal.code)}</span>
            </div>
            {signal.description ? <p className="mt-1 text-sm text-muted">{signal.description}</p> : null}
            {signal.evidence_excerpt ? (
              <blockquote className="mt-2 border-l-2 border-accent pl-3 text-sm text-fg">
                <q>{signal.evidence_excerpt}</q>
              </blockquote>
            ) : null}
            {signal.evidence_turn_ids.length > 0 ? (
              <p className="mt-1.5 text-xs text-muted">
                Evidence in{" "}
                {signal.evidence_turn_ids.map((id, i) => (
                  <span key={id}>
                    {i > 0 ? ", " : null}
                    <a href={`#turn-${id}`} className="font-semibold text-fg underline underline-offset-2">
                      turn {turnNumber(id)}
                    </a>
                  </span>
                ))}
              </p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

export function ClaimSummary({ claim, purpose, category }: { claim: CallerClaim | null | undefined; purpose: string | null | undefined; category?: string | null }) {
  const rows: Array<[string, string | null | undefined]> = [
    ["Says they are", claim?.name],
    ["From", claim?.organization],
    ["Role", claim?.role],
    ["Reason for calling", purpose],
    ["Sparta's read", category && category !== "unknown" ? categoryLabel(category) : null],
  ];
  const present = rows.filter(([, value]) => value);
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="claim-summary">
      {present.length === 0 ? (
        <>
          <dt className="text-muted">Caller</dt>
          <dd className="text-fg">Not identified yet</dd>
        </>
      ) : (
        present.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="min-w-0 break-words font-medium text-fg">{value}</dd>
          </div>
        ))
      )}
    </dl>
  );
}

export function RiskPanel({ risk, fallbackLevel, fallbackScore, fallbackConfidence }: {
  risk: RiskAssessment | null;
  fallbackLevel?: RiskLevel;
  fallbackScore?: number;
  fallbackConfidence?: number;
}) {
  const level = risk?.risk_level ?? fallbackLevel ?? "unknown";
  return (
    <div className="space-y-5">
      <RiskMeter level={level} score={risk?.risk_score ?? fallbackScore} confidence={risk?.confidence ?? fallbackConfidence} />
      {risk ? (
        <>
          <ClaimSummary claim={risk.caller_claim} purpose={risk.purpose} category={risk.category} />
          {risk.reasons.length > 0 ? (
            <div>
              <h3 className="mb-1.5 text-sm font-semibold text-fg">Why Sparta thinks so</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm text-fg">
                {risk.reasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted">Recommended:</span>
            <Badge tone="accent">{actionLabel(risk.recommended_action)}</Badge>
            {risk.additional_actions.map((action) => (
              <Badge key={action} tone="neutral">
                {actionLabel(action)}
              </Badge>
            ))}
            {risk.language_profile ? <Badge tone="neutral">{profileLabel(risk.language_profile)}</Badge> : null}
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold text-fg">Evidence</h3>
            <SignalList signals={risk.signals} />
          </div>
        </>
      ) : (
        <p className="text-sm text-muted">No assessment yet. Sparta is still finding out who is calling and why.</p>
      )}
    </div>
  );
}
