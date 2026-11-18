"use client";

import { useRef } from "react";
import type { CallDetail, CallTurn, LatencyBreakdown } from "@/lib/api/types";
import { formatMs } from "@/lib/format";
import type { LiveCallState } from "@/lib/live/reducer";
import { useCssVar } from "@/lib/use-css-var";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DefinitionRow, Disclosure } from "@/components/ui/layout";
import { CopyButton } from "@/components/ui/feedback";

const STAGES: Array<[keyof Omit<LatencyBreakdown, "simulated_stages">, string]> = [
  ["audio_input_ms", "Audio input"],
  ["vad_ms", "Voice activity detection"],
  ["stt_ms", "Speech recognition"],
  ["language_detect_ms", "Language detection"],
  ["policy_ms", "Safety policy"],
  ["model_ms", "Reply generation"],
  ["tts_first_audio_ms", "Speech synthesis (first audio)"],
  ["playback_start_ms", "Playback start"],
  ["interruption_ms", "Interruption response"],
];

export function latestLatency(turns: ReadonlyArray<CallTurn>): LatencyBreakdown | null {
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const latency = turns[i]!.latency;
    if (latency) return latency;
  }
  return null;
}

export function averageTotal(turns: ReadonlyArray<CallTurn>): number | null {
  const seen = new Set<number>();
  const values: number[] = [];
  for (const turn of turns) {
    const total = turn.latency?.total_ms;
    if (typeof total === "number" && !seen.has(turn.seq) && turn.speaker === "assistant") {
      seen.add(turn.seq);
      values.push(total);
    }
  }
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

function StageBar({ label, value, simulated, max }: { label: string; value: number; simulated: boolean; max: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useCssVar(ref, "--fill", max > 0 ? Math.min(1, value / max) : 0);
  return (
    <li className="py-1.5" data-testid="latency-stage" data-simulated={simulated}>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="min-w-0 text-fg">
          {label}
          {simulated ? (
            <Badge tone="info" className="ml-2" title="This value comes from the simulated network profile, not a measurement">
              simulated
            </Badge>
          ) : null}
        </span>
        <span className="tabular-nums text-fg">{formatMs(value)}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-sunken" aria-hidden="true">
        <div ref={ref} className="sp-bar-fill h-full w-full rounded-full" data-simulated={simulated} />
      </div>
    </li>
  );
}

const CONNECTION_TEXT: Record<LiveCallState["connection"], string> = {
  idle: "Not connected",
  connecting: "Connecting…",
  open: "Connected",
  reconnecting: "Reconnecting…",
  closed: "Closed",
  failed: "Failed (will not retry)",
};

/** Collapsible diagnostics: live connection, latency per stage (simulated ones flagged), versions and trace id. */
export function DiagnosticsPanel({
  live,
  call,
  onReconnect,
}: {
  live: LiveCallState;
  call: CallDetail | null;
  onReconnect?: () => void;
}) {
  const latency = latestLatency(live.turns);
  const average = averageTotal(live.turns);
  const simulatedStages = new Set(latency?.simulated_stages ?? []);
  const max = Math.max(1, ...STAGES.map(([key]) => latency?.[key] ?? 0));
  const traceId = call?.trace_id ?? "";

  return (
    <Disclosure summary="Diagnostics" className="bg-surface" summaryClassName="text-base">
      <div className="space-y-5" data-testid="diagnostics">
        <section aria-label="Connection">
          <h3 className="mb-1 text-sm font-semibold text-fg">Live connection</h3>
          <dl>
            <DefinitionRow label="Status">
              <span data-testid="connection-status">{CONNECTION_TEXT[live.connection]}</span>
            </DefinitionRow>
            <DefinitionRow label="Reconnect attempts">{live.reconnectAttempt}</DefinitionRow>
            <DefinitionRow label="Last event sequence">{live.lastSeq}</DefinitionRow>
            <DefinitionRow label="Events received">{live.eventCount}</DefinitionRow>
            <DefinitionRow label="Resync requests">{live.resyncCount}</DefinitionRow>
          </dl>
          {live.connection !== "open" && live.connection !== "connecting" && onReconnect ? (
            <Button variant="secondary" size="sm" icon="refresh" onClick={onReconnect} className="mt-2">
              Reconnect now
            </Button>
          ) : null}
        </section>

        <section aria-label="Latency">
          <h3 className="mb-1 text-sm font-semibold text-fg">Latency per stage (latest reply)</h3>
          {latency ? (
            <>
              <ul>
                {STAGES.filter(([key]) => typeof latency[key] === "number").map(([key, label]) => (
                  <StageBar key={key} label={label} value={latency[key] as number} simulated={simulatedStages.has(key)} max={max} />
                ))}
              </ul>
              <dl className="mt-1 border-t border-line pt-1">
                <DefinitionRow label="Total for this reply">{formatMs(latency.total_ms)}</DefinitionRow>
                <DefinitionRow label="Average total (all replies)">{formatMs(average)}</DefinitionRow>
              </dl>
              {simulatedStages.size > 0 ? (
                <p className="mt-1 text-sm text-muted">Stages marked “simulated” come from the chosen network profile, not from a real network.</p>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-muted">No timings yet. They appear after the first reply.</p>
          )}
        </section>

        {live.providerErrors.length > 0 ? (
          <section aria-label="Provider errors">
            <h3 className="mb-1 text-sm font-semibold text-fg">Provider errors</h3>
            <ul className="space-y-1.5 text-sm">
              {live.providerErrors.map((error, index) => (
                <li key={index} className="rounded-xl bg-warning-bg px-3 py-2 text-fg">
                  <strong className="font-semibold">
                    {error.provider} · {error.stage}
                  </strong>
                  : {error.message} {error.degraded ? "(running in a degraded mode)" : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section aria-label="Versions">
          <h3 className="mb-1 text-sm font-semibold text-fg">Provider and model versions</h3>
          {call ? (
            <dl>
              <DefinitionRow label="App">{call.versions.app_version || "—"}</DefinitionRow>
              <DefinitionRow label="Policy">{call.versions.policy_version || "—"}</DefinitionRow>
              <DefinitionRow label="Telephony">{call.versions.telephony_provider || "—"}</DefinitionRow>
              <DefinitionRow label="Speech to text">{call.versions.stt_provider || "—"}</DefinitionRow>
              <DefinitionRow label="Text to speech">{call.versions.tts_provider || "—"}</DefinitionRow>
              <DefinitionRow label="Reasoning">
                {call.versions.llm_provider || "—"}
                {call.versions.llm_model ? ` · ${call.versions.llm_model}` : ""}
              </DefinitionRow>
            </dl>
          ) : (
            <p className="text-sm text-muted">Loading…</p>
          )}
        </section>

        <section aria-label="Trace">
          <h3 className="mb-1 text-sm font-semibold text-fg">Diagnostic trace ID</h3>
          {traceId ? (
            <div className="flex flex-wrap items-center gap-2">
              <code className="break-all rounded-lg bg-sunken px-2 py-1 font-mono text-xs text-fg" data-testid="trace-id">
                {traceId}
              </code>
              <CopyButton text={traceId} label="Copy trace ID" />
            </div>
          ) : (
            <p className="text-sm text-muted">Available once the call has loaded.</p>
          )}
        </section>
      </div>
    </Disclosure>
  );
}
