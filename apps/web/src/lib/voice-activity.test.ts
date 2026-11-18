import { describe, expect, it } from "vitest";
import {
  buildSpeechEnvelope,
  computeStageFrame,
  deriveVoiceMode,
  envelopeLevel,
  INTERRUPT_FLASH_MS,
  isAssistantSpeaking,
  MODE_PRESENTATION,
  PARTIAL_ACTIVE_MS,
  SPEAKING_GRACE_MS,
  type VoiceModeInput,
} from "./voice-activity";
import type { AssistantSpeech } from "./live/reducer";

const NOW = 1_000_000;

const speech = (overrides: Partial<AssistantSpeech> = {}): AssistantSpeech => ({
  turnId: "turn_3",
  text: "Hello, I'm Atharv's AI call assistant. May I know who's calling?",
  locale: "en-IN",
  voiceId: "v",
  estDurationMs: 4000,
  startedAt: NOW,
  ...overrides,
});

const base: VoiceModeInput = {
  connection: "open",
  hydrated: true,
  status: "active",
  state: "IDENTIFY_CALLER",
  listening: false,
  partial: null,
  assistantSpeaking: null,
  interrupted: null,
  escalation: null,
  awaitingAssistant: false,
  now: NOW,
};

describe("deriveVoiceMode (state-driven, never random)", () => {
  it("is offline/connecting before the model is hydrated", () => {
    expect(deriveVoiceMode({ ...base, hydrated: false, connection: "connecting" })).toBe("connecting");
    expect(deriveVoiceMode({ ...base, hydrated: false, connection: "reconnecting" })).toBe("offline");
  });

  it("follows the real events: listening, caller speaking, thinking, assistant speaking", () => {
    expect(deriveVoiceMode({ ...base, listening: true })).toBe("listening");
    expect(deriveVoiceMode({ ...base, partial: { speaker: "caller", text: "hi", language: null, startedAt: NOW, updatedAt: NOW - 200 } })).toBe("caller_speaking");
    expect(deriveVoiceMode({ ...base, awaitingAssistant: true })).toBe("thinking");
    expect(deriveVoiceMode({ ...base, assistantSpeaking: speech() })).toBe("assistant_speaking");
  });

  it("lets stale signals expire: the assistant stops after est_duration_ms + grace, partials after ~2 s", () => {
    const speaking = speech({ estDurationMs: 1000 });
    expect(isAssistantSpeaking(speaking, NOW + 1000 + SPEAKING_GRACE_MS)).toBe(true);
    expect(isAssistantSpeaking(speaking, NOW + 1000 + SPEAKING_GRACE_MS + 1)).toBe(false);
    expect(deriveVoiceMode({ ...base, now: NOW + 5000, assistantSpeaking: speaking })).toBe("idle");
    const partial = { speaker: "caller" as const, text: "x", language: null, startedAt: NOW, updatedAt: NOW };
    expect(deriveVoiceMode({ ...base, now: NOW + PARTIAL_ACTIVE_MS - 1, partial })).toBe("caller_speaking");
    expect(deriveVoiceMode({ ...base, now: NOW + PARTIAL_ACTIVE_MS + 1, partial })).toBe("idle");
  });

  it("shows barge-in briefly, then returns to normal", () => {
    const interrupted = { turnId: "turn_3", spokenFraction: 0.6, interruptionMs: 200, at: NOW };
    expect(deriveVoiceMode({ ...base, interrupted })).toBe("interrupted");
    expect(deriveVoiceMode({ ...base, interrupted, now: NOW + INTERRUPT_FLASH_MS + 1, listening: true })).toBe("listening");
  });

  it("shows owner escalation and takeover, and the ending of the call", () => {
    expect(deriveVoiceMode({ ...base, state: "ESCALATE" })).toBe("escalated");
    expect(deriveVoiceMode({ ...base, escalation: { status: "requested" } })).toBe("escalated");
    expect(deriveVoiceMode({ ...base, state: "OWNER_TAKEOVER" })).toBe("taken_over");
    expect(deriveVoiceMode({ ...base, status: "ended", state: "COMPLETED" })).toBe("ended");
    expect(deriveVoiceMode({ ...base, status: "failed", state: "FAILED" })).toBe("failed");
  });

  it("keeps showing the assistant while it says goodbye after the end state was reached", () => {
    expect(deriveVoiceMode({ ...base, state: "END_SPAM", status: "active", assistantSpeaking: speech() })).toBe("assistant_speaking");
    expect(deriveVoiceMode({ ...base, state: "END_SPAM", status: "ended" })).toBe("ended");
  });

  it("is not 'ended' while the closing sentence is still on its way: the end state arrives a few ms before assistant.speaking", () => {
    const closing: VoiceModeInput = { ...base, state: "END_SPAM", status: "active", closingPending: true };
    expect(deriveVoiceMode(closing)).toBe("thinking");
    expect(deriveVoiceMode({ ...closing, state: "END_SILENCE" })).toBe("thinking");
    // once the sentence is announced it is the sentence that is shown, and when it has been spoken the call is over
    expect(deriveVoiceMode({ ...closing, closingPending: false, assistantSpeaking: speech() })).toBe("assistant_speaking");
    expect(deriveVoiceMode({ ...closing, closingPending: false })).toBe("ended");
    // a failed call is never "thinking"
    expect(deriveVoiceMode({ ...closing, status: "failed", state: "FAILED" })).toBe("failed");
  });

  it("does not wait for a closing sentence when the stream cannot deliver it any more", () => {
    const closing: VoiceModeInput = { ...base, state: "END_SPAM", status: "active", closingPending: true };
    for (const connection of ["reconnecting", "closed", "failed", "idle"] as const) {
      expect(deriveVoiceMode({ ...closing, connection }), connection).toBe("ended");
    }
  });

  it("has a label, detail text and colour for every mode (state is never colour only)", () => {
    for (const [mode, presentation] of Object.entries(MODE_PRESENTATION)) {
      expect(presentation.label.length, mode).toBeGreaterThan(2);
      expect(presentation.detail.length, mode).toBeGreaterThan(10);
    }
  });
});

describe("speech envelope", () => {
  const text = "Hello, I'm Atharv's AI call assistant. May I know who's calling and what this is regarding?";

  it("is deterministic: the same text and duration always give the same envelope", () => {
    expect(buildSpeechEnvelope(text, 6000)).toEqual(buildSpeechEnvelope(text, 6000));
  });

  it("fits inside the utterance duration, in order, with pauses after sentences", () => {
    const envelope = buildSpeechEnvelope(text, 6000);
    expect(envelope.durationMs).toBe(6000);
    expect(envelope.segments.length).toBe(text.split(/\s+/).length);
    let previousEnd = -1;
    for (const segment of envelope.segments) {
      expect(segment.start).toBeGreaterThanOrEqual(previousEnd);
      expect(segment.end).toBeGreaterThan(segment.start);
      expect(segment.end).toBeLessThanOrEqual(6000 + 1);
      previousEnd = segment.end;
    }
    // "assistant." ends a sentence, so the gap before the next word is longer than between ordinary words
    const sentenceGap = envelope.segments[6]!.start - envelope.segments[5]!.end;
    const wordGap = envelope.segments[1]!.start - envelope.segments[0]!.end;
    expect(sentenceGap).toBeGreaterThan(wordGap);
  });

  it("is loud inside words, silent in pauses and outside the utterance", () => {
    const envelope = buildSpeechEnvelope("Hi there.", 2000);
    const first = envelope.segments[0]!;
    expect(envelopeLevel(envelope, (first.start + first.end) / 2)).toBeGreaterThan(0.2);
    expect(envelopeLevel(envelope, -5)).toBe(0);
    expect(envelopeLevel(envelope, 2001)).toBe(0);
    const gap = (first.end + envelope.segments[1]!.start) / 2;
    expect(envelopeLevel(envelope, gap)).toBe(0);
  });

  it("handles empty text, zero duration and non-Latin scripts", () => {
    expect(buildSpeechEnvelope("", 3000).segments).toEqual([]);
    expect(buildSpeechEnvelope("hello", 0).segments).toEqual([]);
    const hindi = buildSpeechEnvelope("नमस्ते, मैं एआई सहायक हूँ।", 3000);
    expect(hindi.segments.length).toBe(5);
    expect(hindi.segments.every((s) => s.level > 0)).toBe(true);
  });
});

describe("stage frames", () => {
  const assistant = speech({ estDurationMs: 4000 });
  const envelope = buildSpeechEnvelope(assistant.text, assistant.estDurationMs);
  const input = (mode: Parameters<typeof computeStageFrame>[0]["mode"], now: number, extra = {}) =>
    computeStageFrame({ mode, now, bars: 24, assistant, envelope, partial: null, interrupted: null, ...extra });

  it("is a pure function of state and time (no randomness)", () => {
    expect(input("assistant_speaking", NOW + 1234)).toEqual(input("assistant_speaking", NOW + 1234));
  });

  it("reports spoken progress from est_duration_ms and finishes at 100%", () => {
    expect(input("assistant_speaking", NOW + 1000).progress).toBeCloseTo(0.25, 5);
    expect(input("assistant_speaking", NOW + 9000).progress).toBe(1);
  });

  it("is silent between words and moves while speaking", () => {
    const quiet = input("assistant_speaking", NOW + 5000); // after the utterance ended
    expect(Math.max(...quiet.bars)).toBeLessThan(0.1);
    const loud = Array.from({ length: 40 }, (_, i) => input("assistant_speaking", NOW + 100 + i * 90)).map((f) => f.energy);
    expect(Math.max(...loud)).toBeGreaterThan(0.25);
  });

  it("drives the caller bars from real microphone levels when they exist, and otherwise from partial activity", () => {
    const mic = Array.from({ length: 16 }, () => 0.8);
    const fromMic = computeStageFrame({ mode: "caller_speaking", now: NOW, bars: 24, assistant: null, envelope: null, partial: null, interrupted: null, micLevels: mic });
    expect(fromMic.energy).toBeGreaterThan(0.7);
    const fresh = computeStageFrame({ mode: "caller_speaking", now: NOW + 50, bars: 24, assistant: null, envelope: null, partial: { speaker: "caller", text: "a", language: null, startedAt: NOW, updatedAt: NOW }, interrupted: null });
    const old = computeStageFrame({ mode: "caller_speaking", now: NOW + 1700, bars: 24, assistant: null, envelope: null, partial: { speaker: "caller", text: "a", language: null, startedAt: NOW, updatedAt: NOW }, interrupted: null });
    expect(fresh.energy).toBeGreaterThan(old.energy);
  });

  it("decays the barge-in flash and exposes where the assistant was cut off", () => {
    const interrupted = { turnId: "turn_3", spokenFraction: 0.62, interruptionMs: 150, at: NOW };
    const start = input("interrupted", NOW, { interrupted });
    const later = input("interrupted", NOW + INTERRUPT_FLASH_MS, { interrupted });
    expect(start.energy).toBeGreaterThan(later.energy);
    expect(start.progress).toBe(0.62);
  });

  it("is flat and low for states that make no sound claim (ended, offline, idle)", () => {
    for (const mode of ["ended", "offline", "idle", "connecting", "failed"] as const) {
      const frame = input(mode, NOW);
      expect(frame.energy).toBe(0);
      expect(new Set(frame.bars).size).toBe(1);
    }
  });
});
