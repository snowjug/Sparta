import { beforeEach, describe, expect, it } from "vitest";
import { modeFor } from "@/components/call/live-voice-stage";
import type { CallState } from "@/lib/api/enums";
import type { CallDetail, CallTurn, LiveEvent } from "@/lib/api/types";
import type { VoiceMode } from "@/lib/voice-activity";
import { makeCall, makeEvent, makeRisk, makeTurn, resetEventSeq } from "@/test/fixtures";
import { initialLiveState, liveReducer, type LiveAction, type LiveCallState } from "./reducer";

/**
 * The stage mode over the end of a real call.
 *
 * The event order and the gaps between events are those the API emitted for a scripted `bank-otp-en` call (captured from the running
 * server, `GET /calls/{id}/events`): the end state is entered about 10 ms BEFORE `assistant.speaking` announces the closing sentence, the
 * sentence is spoken for `est_duration_ms`, and only then do `assistant.finished`, `state.changed -> COMPLETED` and `call.ended` follow.
 * The mode is derived after EVERY event, which is the worst case of a browser that renders between any two WebSocket frames
 * (a slow machine, a busy tab): no interleaving of renders may show "ended" early, and once shown it must stay.
 */

const T0 = Date.parse("2026-11-17T10:00:00.000Z");
const iso = (offsetMs: number) => new Date(T0 + offsetMs).toISOString();

const plan = (text: string, estDurationMs: number) => ({ text, locale: "en-IN", voice_id: "en-IN-NeerjaNeural", rate: 1, style: null, ssml: null, transliteration: null, est_duration_ms: estDurationMs });
const said = (seq: number, text: string, estDurationMs: number, stateAfter: CallState): CallTurn =>
  makeTurn({ seq, speaker: "assistant", source: "assistant", text, speech: plan(text, estDurationMs), state_after: stateAfter, language_profile: null, created_at: iso(seq * 10) });
const heard = (seq: number, text: string): CallTurn => makeTurn({ seq, speaker: "caller", text, created_at: iso(seq * 10) });

/** What `GET /calls/{id}` would answer at that moment. */
interface Server {
  state: CallState;
  status: "active" | "ended";
  turns: CallTurn[];
  speaking: CallTurn | null;
}

interface Step {
  event: LiveEvent;
  at: number;
  server: Server;
}

function detailOf(server: Server): CallDetail {
  const ended = server.status === "ended";
  return makeCall({
    status: server.status,
    state: server.state,
    turns: server.turns,
    ended_at: ended ? iso(30_000) : null,
    duration_ms: ended ? 30_000 : null,
    summary: ended ? makeCall().summary : null,
    assistant_speaking: server.speaking !== null,
    speaking_turn_id: server.speaking?.id ?? null,
  });
}

type EventAction = Extract<LiveAction, { type: "event" }>;

const snapshotAction = (server: Server, seq: number, offsetMs: number): EventAction => ({
  type: "event",
  at: T0 + offsetMs,
  event: makeEvent("call.snapshot", { call: detailOf(server) }, { seq, ts: iso(offsetMs) }),
});

const step = (offsetMs: number, type: string, data: Record<string, unknown>, server: Server): Step => ({ event: makeEvent(type, data, { ts: iso(offsetMs) }), at: T0 + offsetMs, server });

const toAction = (item: Step): EventAction => ({ type: "event", event: item.event, at: item.at });

interface Scenario {
  start: Server;
  startSeq: number;
  steps: Step[];
}

/** The refusal: caller asks for the OTP, Sparta refuses (END_SPAM) and says one closing sentence, then the call ends. */
function refusalCall(): Scenario {
  const intro = said(1, "Hi, I'm Atharv's AI call assistant.", 4717, "IDENTIFY_CALLER");
  const start: Server = {
    state: "IDENTIFY_PURPOSE",
    status: "active",
    turns: [intro, heard(2, "Good afternoon, this is Rahul calling from State Bank of India."), said(3, "Thanks. And what is this call regarding?", 2051, "IDENTIFY_PURPOSE")],
    speaking: null,
  };
  const asked = { ...start, turns: [...start.turns, heard(4, "To secure it I just need the OTP that was sent to your phone.")] };
  const refusal = said(5, "I'm sorry, I can't share or accept any personal, financial or security information on this call.", 6717, "END_SPAM");
  const closed: Server = { ...asked, state: "END_SPAM", turns: [...asked.turns, refusal] }; // END_SPAM and the closing turn are persisted together
  const spoken = { ...closed, speaking: refusal };
  const ended: Server = { ...closed, state: "COMPLETED", status: "ended" };
  const speakingAt = 18;
  const finishedAt = speakingAt + 6728;
  return {
    start,
    startSeq: 20,
    steps: [
      step(0, "transcript.final", { turn: asked.turns[3] }, asked),
      step(3, "state.changed", { from: "IDENTIFY_PURPOSE", to: "ASSESSING" }, closed),
      step(5, "state.changed", { from: "ASSESSING", to: "REFUSE_SENSITIVE_REQUEST" }, closed),
      step(7, "state.changed", { from: "REFUSE_SENSITIVE_REQUEST", to: "END_SPAM" }, closed),
      step(11, "risk.updated", { risk: makeRisk() }, closed),
      step(16, "transcript.final", { turn: refusal }, closed),
      step(speakingAt, "assistant.speaking", { turn_id: "turn_5", text: refusal.text, locale: "en-IN", voice_id: "en-IN-NeerjaNeural", est_duration_ms: 6717 }, spoken),
      step(finishedAt, "assistant.finished", { turn_id: "turn_5" }, closed),
      step(finishedAt + 13, "state.changed", { from: "END_SPAM", to: "COMPLETED" }, ended),
      step(finishedAt + 15, "call.ended", { reason: "refused_and_ended", state: "COMPLETED", duration_ms: 30_000 }, ended),
      step(finishedAt + 18, "summary.created", { summary: makeCall().summary }, ended),
    ],
  };
}

/** Two silences: the second one closes the call (END_SILENCE). The previous assistant turn is a finished re-prompt. */
function silenceCall(): Scenario {
  const reprompt = said(3, "Hello? Are you still there?", 2400, "IDENTIFY_CALLER");
  const start: Server = {
    state: "IDENTIFY_CALLER",
    status: "active",
    turns: [said(1, "Hi, I'm Atharv's AI call assistant.", 4717, "IDENTIFY_CALLER"), heard(2, "Hello."), reprompt],
    speaking: null,
  };
  const goodbye = said(4, "I haven't heard anything, so I'll end the call now. Goodbye.", 4200, "END_SILENCE");
  const closed: Server = { ...start, state: "END_SILENCE", turns: [...start.turns, goodbye] };
  const spoken = { ...closed, speaking: goodbye };
  const ended: Server = { ...closed, state: "COMPLETED", status: "ended" };
  return {
    start,
    startSeq: 12,
    steps: [
      step(0, "call.listening", {}, start),
      step(8_000, "state.changed", { from: "IDENTIFY_CALLER", to: "END_SILENCE" }, closed),
      step(8_004, "risk.updated", { risk: makeRisk({ risk_level: "low", signals: [] }) }, closed),
      step(8_009, "transcript.final", { turn: goodbye }, closed),
      step(8_011, "assistant.speaking", { turn_id: "turn_4", text: goodbye.text, locale: "en-IN", voice_id: "en-IN-NeerjaNeural", est_duration_ms: 4200 }, spoken),
      step(12_230, "assistant.finished", { turn_id: "turn_4" }, closed),
      step(12_243, "state.changed", { from: "END_SILENCE", to: "COMPLETED" }, ended),
      step(12_245, "call.ended", { reason: "silence", state: "COMPLETED", duration_ms: 30_000 }, ended),
      step(12_248, "summary.created", { summary: makeCall().summary }, ended),
    ],
  };
}

interface Replay {
  /** Distinct consecutive modes, as a MutationObserver on the stage's `data-mode` would record them. */
  modes: VoiceMode[];
  /** Mode after each action, with what caused it. */
  trail: string[];
  final: LiveCallState;
}

/** Opens the call (connected, snapshot) and applies every action in order, deriving the stage mode after each one. */
function replay(scenario: Scenario, actions: LiveAction[]): Replay {
  let state = liveReducer(initialLiveState("call_1"), { type: "connection", status: "open" });
  state = liveReducer(state, snapshotAction(scenario.start, scenario.startSeq, -1_000));
  const modes: VoiceMode[] = [];
  const trail: string[] = [];
  const observe = (mode: VoiceMode, label: string) => {
    trail.push(`${label} -> ${mode}`);
    if (modes.at(-1) !== mode) modes.push(mode);
  };
  observe(modeFor(state, T0 - 1_000), "snapshot");
  for (const action of actions) {
    state = liveReducer(state, action);
    const label = action.type === "event" ? `${action.event.type}#${action.event.seq}` : action.type;
    const at = "at" in action ? action.at : T0;
    observe(modeFor(state, at), label);
  }
  return { modes, trail, final: state };
}

beforeEach(() => resetEventSeq(20));

describe("the voice stage over the end of a call", () => {
  it("shows 'ended' only after the closing sentence was spoken, however renders fall between the frames (refusal / END_SPAM)", () => {
    const scenario = refusalCall();
    const { modes, trail } = replay(scenario, scenario.steps.map(toAction));
    // Before the fix: [..., "thinking", "ended", "assistant_speaking", "ended"] - "ended" right after `state.changed -> END_SPAM`.
    expect(modes, trail.join("\n")).toEqual(["idle", "thinking", "assistant_speaking", "ended"]);
  });

  it("does the same when the call is closed by silence (END_SILENCE), where the previous turn is a finished re-prompt", () => {
    resetEventSeq(12);
    const scenario = silenceCall();
    const { modes, trail } = replay(scenario, scenario.steps.map(toAction));
    expect(modes, trail.join("\n")).toEqual(["idle", "listening", "thinking", "assistant_speaking", "ended"]);
  });

  it("keeps showing the assistant until the closing sentence has finished, then ends exactly once", () => {
    const scenario = refusalCall();
    const { trail, final } = replay(scenario, scenario.steps.map(toAction));
    const speakingUntil = trail.findIndex((line) => line.startsWith("assistant.finished"));
    expect(trail.slice(0, speakingUntil).filter((line) => line.endsWith("-> ended")), trail.join("\n")).toEqual([]);
    expect(trail.slice(speakingUntil).every((line) => line.endsWith("-> ended")), trail.join("\n")).toBe(true);
    expect(final.status).toBe("ended");
    expect(final.closingPending).toBe(false);
  });

  it("does not wait for a closing sentence that cannot arrive: when the stream is not open the call is simply shown as ended", () => {
    const scenario = refusalCall();
    const upToEndState = scenario.steps.slice(0, 4).map(toAction); // ... state.changed -> END_SPAM, nothing after it
    const open = replay(scenario, upToEndState);
    expect(open.modes.at(-1)).toBe("thinking");
    const dropped = replay(scenario, [...upToEndState, { type: "connection", status: "closed" }]);
    expect(dropped.modes.at(-1)).toBe("ended");
  });

  it("a REST turn result that arrives before the WebSocket frames does not end the stage early either (typed caller in the Lab)", () => {
    const scenario = refusalCall();
    const steps = scenario.steps;
    const turnResult: LiveAction = {
      type: "turn-result",
      at: T0 + 2,
      result: { caller_turn: steps[0]!.server.turns[3]!, assistant_turn: steps[5]!.server.turns[4]!, interrupted_turn_id: null, call: makeCall(), risk: makeRisk(), state: "END_SPAM", ended: true, escalation: null },
    };
    // The HTTP response beats every WebSocket frame of that turn except the first one.
    const { modes, trail, final } = replay(scenario, [toAction(steps[0]!), turnResult, ...steps.slice(1).map(toAction)]);
    expect(modes, trail.join("\n")).toEqual(["idle", "thinking", "assistant_speaking", "ended"]);
    expect(final.status).toBe("ended");
  });

  it("a REST turn result that arrives after the whole call has ended does not move the call back to an earlier state", () => {
    const scenario = refusalCall();
    const steps = scenario.steps;
    const refusal = steps[5]!.server.turns[4]!;
    const late: LiveAction = {
      type: "turn-result",
      at: T0 + 30_000,
      result: { caller_turn: steps[0]!.server.turns[3]!, assistant_turn: refusal, interrupted_turn_id: null, call: makeCall(), risk: makeRisk(), state: "END_SPAM", ended: false, escalation: null },
    };
    const { modes, final } = replay(scenario, [...steps.map(toAction), late]);
    expect(final.status).toBe("ended");
    expect(final.state).toBe("COMPLETED");
    expect(modes.at(-1)).toBe("ended");
    expect(modes.filter((mode) => mode === "ended")).toHaveLength(1);
  });
});

describe("a snapshot older than the stream cannot revive a finished call (ended is terminal)", () => {
  it("call.ended, then a snapshot fetched earlier that still says assistant_speaking, then a repeat of assistant.finished", () => {
    const scenario = refusalCall();
    const steps = scenario.steps;
    const speaking = steps[6]!;
    const callEnded = steps[9]!;
    const stale = snapshotAction(speaking.server, speaking.event.seq, speaking.at - T0 + 40); // built while the sentence was playing
    const { modes, trail, final } = replay(scenario, [
      ...steps.slice(0, 10).map(toAction), // up to and including call.ended
      { ...stale, at: callEnded.at + 120 }, // delivered late (slow network / a reconnect that was answered before the call ended)
      { type: "event", at: callEnded.at + 125, event: steps[7]!.event }, // assistant.finished again
      toAction(steps[10]!),
    ]);
    expect(modes, trail.join("\n")).toEqual(["idle", "thinking", "assistant_speaking", "ended"]);
    expect(final.status).toBe("ended");
    expect(final.assistant.speaking).toBeNull();
    expect(final.state).toBe("COMPLETED");
  });

  it("is ignored wherever it arrives: a snapshot built at any earlier point leaves the stage exactly as it was", () => {
    const scenario = refusalCall();
    const steps = scenario.steps;
    const builtAfter = [0, 6, 7]; // the asked question, while the closing sentence plays, right after it was spoken
    const baseline = replay(scenario, steps.map(toAction));
    for (const built of builtAfter) {
      for (let arrives = built + 1; arrives < steps.length; arrives += 1) {
        const stale = snapshotAction(steps[built]!.server, steps[built]!.event.seq, steps[built]!.at - T0 + 1);
        const actions = steps.map(toAction);
        actions.splice(arrives + 1, 0, { ...stale, at: steps[arrives]!.at + 1 });
        const { modes, trail, final } = replay(scenario, actions);
        const label = `snapshot built after ${steps[built]!.event.type}#${steps[built]!.event.seq}, delivered after ${steps[arrives]!.event.type}#${steps[arrives]!.event.seq}`;
        expect(modes, `${label}\n${trail.join("\n")}`).toEqual(baseline.modes);
        expect(final.status, label).toBe("ended");
        expect(final.state, label).toBe("COMPLETED");
        expect(final.turns.map((turn) => turn.id), label).toEqual(baseline.final.turns.map((turn) => turn.id));
      }
    }
  });

  it("is ignored when it comes from REST (refresh or the gap fallback) after the server confirmed the end", () => {
    const scenario = refusalCall();
    const steps = scenario.steps;
    const staleRest: LiveAction = { type: "snapshot", call: detailOf(steps[6]!.server), at: T0 + 30_000, force: true };
    const { modes, final } = replay(scenario, [...steps.map(toAction), staleRest]);
    expect(modes).toEqual(["idle", "thinking", "assistant_speaking", "ended"]);
    expect(final.status).toBe("ended");
    expect(final.assistant.speaking).toBeNull();
  });

  it("a REST snapshot that says the call is over still applies (it is the truth, not a stale reply)", () => {
    const scenario = refusalCall();
    const steps = scenario.steps;
    const early = steps.slice(0, 7).map(toAction); // ... while the closing sentence is still playing
    const finishedRest: LiveAction = { type: "snapshot", call: detailOf(steps[9]!.server), at: T0 + 20_000, force: true };
    const { final, modes } = replay(scenario, [...early, finishedRest]);
    expect(final.status).toBe("ended");
    expect(final.assistant.speaking).toBeNull();
    expect(modes.at(-1)).toBe("ended");
  });

  it("a fresh snapshot (same sequence number as the model, or newer) is still applied: reconnects keep working", () => {
    const scenario = refusalCall();
    const steps = scenario.steps;
    const upToSpeaking = steps.slice(0, 7);
    const fresh = snapshotAction(steps[6]!.server, steps[6]!.event.seq, steps[6]!.at - T0 + 5);
    const { final } = replay(scenario, [...upToSpeaking.map(toAction), fresh]);
    expect(final.assistant.speaking?.turnId).toBe("turn_5");
    expect(final.status).toBe("active");
    const newer = snapshotAction(steps[9]!.server, steps[9]!.event.seq, steps[9]!.at - T0 + 5);
    expect(replay(scenario, [...upToSpeaking.map(toAction), newer]).final.status).toBe("ended");
  });
});
