import type { CallState, CallStatus } from "./api/enums";
import type { Escalation } from "./api/types";
import { isEndState } from "./call-state";
import type { AssistantSpeech, ConnectionStatus, InterruptInfo, PartialInfo } from "./live/reducer";

/**
 * What the voice stage shows. Every mode is derived from real call events (connection status, `call.listening`,
 * `transcript.partial`, `assistant.speaking` / `.finished` / `.interrupted`, `state.changed`, `escalation.requested`,
 * `call.ended`) - never from random numbers.
 */
export type VoiceMode =
  | "offline"
  | "connecting"
  | "idle"
  | "listening"
  | "caller_speaking"
  | "thinking"
  | "assistant_speaking"
  | "interrupted"
  | "escalated"
  | "taken_over"
  | "ended"
  | "failed";

export interface VoiceModeInput {
  connection: ConnectionStatus;
  hydrated: boolean;
  status: CallStatus;
  state: CallState | null;
  listening: boolean;
  partial: PartialInfo | null;
  assistantSpeaking: AssistantSpeech | null;
  interrupted: InterruptInfo | null;
  escalation: Pick<Escalation, "status"> | null;
  /** The newest turn was spoken by the caller and the assistant has not answered yet. */
  awaitingAssistant: boolean;
  /**
   * The conversation reached its end state but the closing sentence has not been announced yet (`LiveCallState.closingPending`): the
   * server enters END_SPAM / END_SILENCE a few milliseconds BEFORE `assistant.speaking`. Optional, so callers without a live model can omit it.
   */
  closingPending?: boolean;
  /** Client clock in ms (injectable for tests). */
  now: number;
}

/** After `assistant.speaking` we trust est_duration_ms plus a short grace period even if `assistant.finished` never arrives. */
export const SPEAKING_GRACE_MS = 800;
export const INTERRUPT_FLASH_MS = 1400;
export const PARTIAL_ACTIVE_MS = 1800;

export function isAssistantSpeaking(speech: AssistantSpeech | null, now: number): boolean {
  if (!speech) return false;
  return now - speech.startedAt <= Math.max(0, speech.estDurationMs) + SPEAKING_GRACE_MS;
}

export function deriveVoiceMode(input: VoiceModeInput): VoiceMode {
  const { connection, hydrated, status, state, now } = input;
  if (status === "failed" || state === "FAILED") return "failed";
  const speaking = isAssistantSpeaking(input.assistantSpeaking, now);
  const finished = status === "ended" || isEndState(state);
  // The end state is reached before the closing sentence is announced: the call is over for the caller only after that sentence.
  // Without an open stream nothing more can arrive, so there is nothing to wait for.
  const closing = finished && !speaking && input.closingPending === true && connection === "open";
  if (finished && !speaking && !closing) return "ended";
  if (!hydrated) return connection === "connecting" || connection === "idle" ? "connecting" : "offline";
  if (connection === "reconnecting" || connection === "failed" || connection === "closed") {
    if (!finished) return "offline";
  }
  if (speaking) return "assistant_speaking";
  if (closing) return "thinking";
  if (input.interrupted && now - input.interrupted.at < INTERRUPT_FLASH_MS) return "interrupted";
  if (state === "OWNER_TAKEOVER") return "taken_over";
  if (state === "ESCALATE" || input.escalation?.status === "requested") return "escalated";
  if (input.partial && input.partial.speaker === "caller" && now - input.partial.updatedAt < PARTIAL_ACTIVE_MS) return "caller_speaking";
  if (input.awaitingAssistant && status === "active") return "thinking";
  if (input.listening) return "listening";
  return "idle";
}

export interface ModePresentation {
  label: string;
  detail: string;
  /** CSS variable for the bars / halo. */
  colorVar: string;
  /** `out`: assistant voice radiates outward from the shield; `in`: the caller's voice travels toward it. */
  direction: "out" | "in";
  animated: boolean;
}

export const MODE_PRESENTATION: Record<VoiceMode, ModePresentation> = {
  offline: { label: "Reconnecting", detail: "The live stream dropped. Sparta is reconnecting and will fill in anything you missed.", colorVar: "var(--muted)", direction: "out", animated: false },
  connecting: { label: "Connecting", detail: "Opening the live stream for this call.", colorVar: "var(--muted)", direction: "out", animated: false },
  idle: { label: "Ready", detail: "Waiting for the next event on this call.", colorVar: "var(--muted)", direction: "out", animated: false },
  listening: { label: "Listening", detail: "Sparta is listening to the caller.", colorVar: "var(--accent)", direction: "in", animated: true },
  caller_speaking: { label: "Caller speaking", detail: "The caller is talking. Words appear as they are recognised.", colorVar: "var(--text)", direction: "in", animated: true },
  thinking: { label: "Thinking", detail: "Sparta is checking what was said and preparing a reply.", colorVar: "var(--accent)", direction: "out", animated: true },
  assistant_speaking: { label: "Sparta is speaking", detail: "The AI assistant is talking to the caller.", colorVar: "var(--accent)", direction: "out", animated: true },
  interrupted: { label: "Caller interrupted", detail: "The caller spoke over the assistant, so it stopped.", colorVar: "var(--warning)", direction: "in", animated: true },
  escalated: { label: "Waiting for you", detail: "This call may be genuine. Choose what happens next.", colorVar: "var(--warning)", direction: "out", animated: true },
  taken_over: { label: "You took over", detail: "You are handling this call now.", colorVar: "var(--info)", direction: "out", animated: false },
  ended: { label: "Call ended", detail: "The call is over. A summary is saved with the call.", colorVar: "var(--muted)", direction: "out", animated: false },
  failed: { label: "Call failed", detail: "Something went wrong with this call.", colorVar: "var(--danger)", direction: "out", animated: false },
};

// ----------------------------------------------------------------------------------------------------- speech envelope

export interface EnvelopeSegment {
  start: number;
  end: number;
  level: number;
}

export interface SpeechEnvelope {
  durationMs: number;
  segments: EnvelopeSegment[];
}

const SENTENCE_END = /[.!?।॥…]+$/u;
const CLAUSE_END = /[,;:\u2013\u2014、]+$/u;

/**
 * Deterministic loudness profile of one utterance, derived only from its text and the server's `est_duration_ms`:
 * words get time proportional to their length and punctuation adds pauses. Same input, same output.
 * It is an estimate of speech rhythm, not a measurement of audio (the simulator produces no audio).
 */
export function buildSpeechEnvelope(text: string, estDurationMs: number): SpeechEnvelope {
  const duration = Math.max(0, Math.round(estDurationMs));
  const words = text.split(/\s+/u).filter(Boolean);
  if (duration === 0 || words.length === 0) return { durationMs: duration, segments: [] };

  const units = words.map((word) => {
    const length = Array.from(word.replace(/[\p{P}\p{S}]/gu, "")).length;
    const pause = SENTENCE_END.test(word) ? 3 : CLAUSE_END.test(word) ? 1.6 : 0.4;
    return { length, speech: 1.5 + Math.min(12, length), pause };
  });
  const total = units.reduce((sum, unit) => sum + unit.speech + unit.pause, 0);
  const scale = duration / total;

  const segments: EnvelopeSegment[] = [];
  let cursor = 0;
  for (const unit of units) {
    const spoken = unit.speech * scale;
    segments.push({ start: cursor, end: cursor + spoken, level: 0.42 + 0.5 * Math.min(1, unit.length / 9) });
    cursor += spoken + unit.pause * scale;
  }
  return { durationMs: duration, segments };
}

/** Loudness 0..1 at `elapsedMs` into the utterance: a smooth swell inside each word, silence in pauses and after the end. */
export function envelopeLevel(envelope: SpeechEnvelope, elapsedMs: number): number {
  if (elapsedMs < 0 || elapsedMs > envelope.durationMs) return 0;
  const { segments } = envelope;
  let low = 0;
  let high = segments.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const segment = segments[mid]!;
    if (elapsedMs < segment.start) high = mid - 1;
    else if (elapsedMs > segment.end) low = mid + 1;
    else {
      const progress = (elapsedMs - segment.start) / Math.max(1, segment.end - segment.start);
      return segment.level * Math.pow(Math.sin(Math.PI * progress), 0.7);
    }
  }
  return 0;
}

// ----------------------------------------------------------------------------------------------------- stage frame

export interface StageFrameInput {
  mode: VoiceMode;
  now: number;
  bars: number;
  assistant: AssistantSpeech | null;
  envelope: SpeechEnvelope | null;
  partial: PartialInfo | null;
  interrupted: InterruptInfo | null;
  /** Real analyser data from the microphone (Simulator Lab), one value 0..1 per bar. When set it wins over estimates. */
  micLevels?: ArrayLike<number> | null;
}

export interface StageFrame {
  /** 0..1 per bar. */
  bars: number[];
  /** Spoken fraction of the current assistant utterance (null when the assistant is not speaking). */
  progress: number | null;
  /** Overall energy 0..1 (used for the halo). */
  energy: number;
}

/** Fixed spatial texture so bars differ from each other smoothly; amplitude always comes from state, never from chance. */
function texture(index: number, bars: number, nowMs: number, speed = 1): number {
  const phase = (index / bars) * Math.PI * 2;
  return 0.58 + 0.28 * Math.sin(phase * 3 + (nowMs / 1100) * speed) + 0.14 * Math.sin(phase * 5 - (nowMs / 700) * speed);
}

function resample(levels: ArrayLike<number>, bars: number): number[] {
  const out: number[] = [];
  const count = levels.length;
  if (count === 0) return new Array<number>(bars).fill(0);
  for (let i = 0; i < bars; i += 1) {
    // Mirror the spectrum so the ring is symmetric: low frequencies at the top and bottom.
    const folded = i < bars / 2 ? i / (bars / 2) : (bars - 1 - i) / (bars / 2);
    const value = levels[Math.min(count - 1, Math.floor(folded * (count - 1)))] ?? 0;
    out.push(Math.min(1, Math.max(0, value)));
  }
  return out;
}

export function computeStageFrame(input: StageFrameInput): StageFrame {
  const { mode, now, bars } = input;
  const floor = 0.05;
  const shaped = (amplitude: number, speed = 1) =>
    Array.from({ length: bars }, (_, i) => Math.min(1, floor + amplitude * texture(i, bars, now, speed)));

  switch (mode) {
    case "assistant_speaking": {
      const speech = input.assistant;
      if (!speech || !input.envelope) return { bars: shaped(0.1), progress: null, energy: 0.1 };
      const elapsed = now - speech.startedAt;
      const level = envelopeLevel(input.envelope, elapsed);
      const progress = speech.estDurationMs > 0 ? Math.min(1, Math.max(0, elapsed / speech.estDurationMs)) : null;
      return { bars: shaped(level * 0.95, 1.4), progress, energy: level };
    }
    case "caller_speaking": {
      if (input.micLevels && input.micLevels.length > 0) {
        const levels = resample(input.micLevels, bars);
        const energy = levels.reduce((sum, value) => sum + value, 0) / bars;
        return { bars: levels.map((value) => Math.min(1, floor + value * 0.95)), progress: null, energy };
      }
      // Each `transcript.partial` is a real burst of caller speech: energy decays smoothly after the latest one.
      const age = input.partial ? Math.max(0, now - input.partial.updatedAt) : Number.POSITIVE_INFINITY;
      const energy = 0.22 + 0.55 * Math.exp(-age / 520);
      return { bars: shaped(energy, 1.8), progress: null, energy };
    }
    case "interrupted": {
      const age = input.interrupted ? Math.max(0, now - input.interrupted.at) : INTERRUPT_FLASH_MS;
      const energy = 0.6 * Math.max(0, 1 - age / INTERRUPT_FLASH_MS);
      return { bars: shaped(energy, 2.4), progress: input.interrupted ? input.interrupted.spokenFraction : null, energy };
    }
    case "listening": {
      const energy = 0.07 + 0.035 * (0.5 + 0.5 * Math.sin((now / 4200) * Math.PI * 2));
      return { bars: shaped(energy, 0.6), progress: null, energy };
    }
    case "thinking": {
      // A slow travelling swell: "working", with no claim about loudness.
      return { bars: shaped(0.14, 2.2), progress: null, energy: 0.14 };
    }
    case "escalated":
      return { bars: shaped(0.06, 0.4), progress: null, energy: 0.06 };
    default:
      return { bars: new Array<number>(bars).fill(floor), progress: null, energy: 0 };
  }
}
