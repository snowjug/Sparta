"use client";

import { useEffect, useState } from "react";
import type { LiveCallState } from "@/lib/live/reducer";
import { deriveVoiceMode, type VoiceMode } from "@/lib/voice-activity";
import { VoiceStage } from "./voice-stage";

/** Client clock that only ticks while `intervalMs` is set, so finished calls and idle screens do not re-render. */
export function useNow(intervalMs: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (intervalMs === null) return;
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function modeFor(live: LiveCallState, now: number): VoiceMode {
  const last = live.turns[live.turns.length - 1];
  return deriveVoiceMode({
    connection: live.connection,
    hydrated: live.hydrated,
    status: live.status,
    state: live.state,
    listening: live.listening,
    partial: live.partial,
    assistantSpeaking: live.assistant.speaking,
    interrupted: live.assistant.interrupted,
    escalation: live.escalation,
    awaitingAssistant: last?.speaker === "caller",
    now,
  });
}

/**
 * The voice stage wired to a live call model. It owns a 250 ms clock (only while the call is active) so the
 * time-based parts of the mode - speaking window, barge-in flash, recent partial - settle without re-rendering the screen.
 */
export function LiveVoiceStage({
  live,
  readMicLevels,
  className,
}: {
  live: LiveCallState;
  readMicLevels?: () => ArrayLike<number> | null;
  className?: string;
}) {
  const now = useNow(live.status === "active" ? 250 : null);
  const mode = modeFor(live, now);
  return (
    <VoiceStage
      className={className}
      mode={mode}
      riskLevel={live.risk?.risk_level ?? live.call?.risk_level ?? "unknown"}
      assistant={live.assistant.speaking}
      partial={live.partial}
      interrupted={live.assistant.interrupted}
      readMicLevels={readMicLevels}
    />
  );
}
