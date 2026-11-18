import type { LiveEvent } from "../api/types";

export interface PingFrame {
  type: "ping";
}

/**
 * Parse one WebSocket text frame. Returns null for anything that is not a well-formed envelope, so a malformed
 * or hostile frame can never reach the reducer. Missing optional fields are normalised, not trusted.
 */
export function parseFrame(raw: unknown): LiveEvent | PingFrame | null {
  let value: unknown = raw;
  if (typeof raw === "string") {
    if (raw.length > 2_000_000) return null;
    try {
      value = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const frame = value as Record<string, unknown>;
  if (typeof frame.type !== "string" || frame.type.length === 0 || frame.type.length > 64) return null;
  if (frame.type === "ping") return { type: "ping" };
  if (typeof frame.call_id !== "string") return null;
  const seq = typeof frame.seq === "number" && Number.isFinite(frame.seq) && frame.seq >= 0 ? Math.floor(frame.seq) : 0;
  const data = frame.data && typeof frame.data === "object" && !Array.isArray(frame.data) ? (frame.data as Record<string, unknown>) : {};
  return {
    type: frame.type,
    call_id: frame.call_id,
    seq,
    ts: typeof frame.ts === "string" ? frame.ts : new Date().toISOString(),
    simulated: frame.simulated === true,
    data,
  };
}

export function isPing(frame: LiveEvent | PingFrame): frame is PingFrame {
  return frame.type === "ping";
}

/** One-line description for the event log viewer. Never includes transcript text longer than a short excerpt. */
export function describeEvent(event: LiveEvent): string {
  const data = event.data as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  switch (event.type) {
    case "call.snapshot":
      return `snapshot · state ${data.call?.state ?? "?"} · ${data.call?.turns?.length ?? data.turn_count ?? 0} turns`;
    case "call.connected":
      return `connected · ${data.state ?? ""}`;
    case "state.changed":
      return `${data.from ?? "?"} → ${data.to ?? "?"}`;
    case "transcript.partial":
      return `${data.speaker ?? "caller"} partial · ${excerpt(data.text)}`;
    case "transcript.final":
      return `${data.turn?.speaker ?? "turn"} final · ${excerpt(data.turn?.text)}`;
    case "language.changed":
      return `${data.from ?? "?"} → ${data.to ?? "?"}${data.profile ? ` (${data.profile})` : ""}`;
    case "risk.updated":
      return `risk ${data.risk?.risk_level ?? "?"} · score ${Number(data.risk?.risk_score ?? 0).toFixed(2)}`;
    case "assistant.speaking":
      return `speaking ${data.turn_id ?? ""} · ~${data.est_duration_ms ?? 0} ms`;
    case "assistant.finished":
      return `finished ${data.turn_id ?? ""}`;
    case "assistant.interrupted":
      return `interrupted ${data.turn_id ?? ""} at ${Math.round(Number(data.spoken_fraction ?? 0) * 100)}%`;
    case "escalation.requested":
      return `escalation · ${excerpt(data.escalation?.reason)}`;
    case "owner.takeover":
    case "owner.action":
      return `${data.action?.action ?? "action"}${data.action?.simulated || data.simulated ? " (simulated)" : ""}`;
    case "call.ended":
      return `ended · ${data.reason ?? ""} · ${data.state ?? ""}`;
    case "summary.created":
      return `summary · ${excerpt(data.summary?.text)}`;
    case "provider.error":
      return `${data.provider ?? "provider"} ${data.stage ?? ""} · ${excerpt(data.message)}`;
    case "stream.resync":
      return "server asked the client to resync";
    default:
      return event.type;
  }
}

function excerpt(value: unknown, max = 60): string {
  if (typeof value !== "string") return "";
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}
