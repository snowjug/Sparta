"use client";

import { useState } from "react";
import type { LiveEvent } from "@/lib/api/types";
import { downloadBlob } from "@/lib/download";
import { describeEvent } from "@/lib/live/events";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyButton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";

const GROUPS: Array<[string, string, (type: string) => boolean]> = [
  ["all", "All events", () => true],
  ["transcript", "Transcript", (t) => t.startsWith("transcript.")],
  ["assistant", "Assistant speech", (t) => t.startsWith("assistant.")],
  ["risk", "Risk and language", (t) => t === "risk.updated" || t === "language.changed"],
  ["state", "Call state", (t) => t.startsWith("call.") || t === "state.changed" || t === "summary.created"],
  ["owner", "Owner and escalation", (t) => t.startsWith("owner.") || t.startsWith("escalation.")],
  ["problems", "Problems", (t) => t === "provider.error" || t === "stream.resync"],
];

function toneFor(type: string): Tone {
  if (type.startsWith("assistant.")) return "accent";
  if (type.startsWith("transcript.")) return "neutral";
  if (type === "risk.updated" || type === "language.changed") return "info";
  if (type === "provider.error" || type === "stream.resync") return "warning";
  if (type.startsWith("escalation.") || type.startsWith("owner.")) return "warning";
  return "neutral";
}

function clock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}.${pad(date.getMilliseconds(), 3)}`;
}

function EventRow({ event }: { event: LiveEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-line last:border-0" data-testid="event-row" data-type={event.type}>
      <details onToggle={(toggle) => setOpen((toggle.currentTarget as HTMLDetailsElement).open)}>
        <summary className="flex min-h-11 cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm [&::-webkit-details-marker]:hidden">
          <span className="w-10 shrink-0 tabular-nums text-muted">#{event.seq}</span>
          <span className="w-24 shrink-0 font-mono text-xs tabular-nums text-muted">{clock(event.ts)}</span>
          <Badge tone={toneFor(event.type)}>{event.type}</Badge>
          <span className="min-w-0 flex-1 break-words text-fg">{describeEvent(event)}</span>
        </summary>
        {open ? (
          <pre className="sp-scroll mb-3 max-h-64 overflow-auto rounded-xl bg-sunken p-3 text-xs text-fg" tabIndex={0} aria-label={`Raw data of event ${event.seq}`}>
            {JSON.stringify({ type: event.type, seq: event.seq, ts: event.ts, simulated: event.simulated, data: event.data }, null, 2)}
          </pre>
        ) : null}
      </details>
    </li>
  );
}

/** Event log viewer: every live event the console received, newest first, with raw JSON on demand. */
export function EventLog({ events, total, callId }: { events: LiveEvent[]; total: number; callId: string }) {
  const [group, setGroup] = useState("all");
  const [showAll, setShowAll] = useState(false);
  const match = GROUPS.find(([id]) => id === group)?.[2] ?? (() => true);
  const filtered = events.filter((event) => match(event.type)).reverse();
  const shown = showAll ? filtered : filtered.slice(0, 80);
  const json = JSON.stringify(events, null, 2);

  return (
    <div className="space-y-3" data-testid="event-log">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="w-56 max-w-full">
          <label htmlFor="event-filter" className="mb-1 block text-sm font-medium text-fg">
            Show
          </label>
          <Select id="event-filter" value={group} onChange={(event) => setGroup(event.target.value)}>
            {GROUPS.map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-wrap gap-2">
          <CopyButton text={json} label="Copy JSON" />
          <Button variant="secondary" size="sm" icon="download" onClick={() => downloadBlob(new Blob([json], { type: "application/json" }), `sparta-events-${callId}.json`)}>
            Download events
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted" aria-live="polite" data-testid="event-count">
        {filtered.length} of {events.length} logged events shown ({total} received in total). Events include what was said: keep downloads private.
      </p>
      {filtered.length === 0 ? (
        <p className="rounded-2xl bg-raised px-4 py-6 text-center text-sm text-muted">No events yet.</p>
      ) : (
        <ol className="sp-scroll max-h-[28rem] overflow-y-auto rounded-2xl border border-line bg-surface px-4" aria-label="Event log">
          {shown.map((event) => (
            <EventRow key={`${event.seq}-${event.type}-${event.ts}`} event={event} />
          ))}
        </ol>
      )}
      {filtered.length > shown.length ? (
        <Button variant="secondary" size="sm" onClick={() => setShowAll(true)}>
          Show all {filtered.length}
        </Button>
      ) : null}
    </div>
  );
}
