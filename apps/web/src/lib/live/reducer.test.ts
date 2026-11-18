import { beforeEach, describe, expect, it } from "vitest";
import { inferSpeaking, initialLiveState, liveReducer, MAX_LOGGED_EVENTS, staleEscalationId, type LiveAction, type LiveCallState } from "./reducer";
import { makeCall, makeEvent, makeRisk, makeTurn, resetEventSeq } from "@/test/fixtures";
import type { LiveEvent } from "@/lib/api/types";

const T0 = Date.parse("2026-11-17T10:00:00.000Z");

function run(actions: LiveAction[], start: LiveCallState = initialLiveState("call_1")): LiveCallState {
  return actions.reduce(liveReducer, start);
}

const ev = (event: LiveEvent, at = T0): LiveAction => ({ type: "event", event, at });

beforeEach(() => resetEventSeq(0));

describe("liveReducer: snapshot first", () => {
  it("hydrates turns, risk, status and the last caller language from call.snapshot", () => {
    const call = makeCall();
    const state = run([ev(makeEvent("call.snapshot", { call }, { seq: 4 }))]);
    expect(state.hydrated).toBe(true);
    expect(state.turns.map((t) => t.id)).toEqual(["turn_1", "turn_2"]);
    expect(state.risk?.risk_level).toBe("high");
    expect(state.status).toBe("ended");
    expect(state.language.code).toBe("en-IN");
    expect(state.lastSeq).toBe(4);
    expect(state.simulated).toBe(true);
  });

  it("ignores a late REST snapshot once the websocket snapshot arrived, unless forced", () => {
    const base = run([ev(makeEvent("call.snapshot", { call: makeCall() }, { seq: 4 }))]);
    const stale = makeCall({ turns: [] });
    expect(liveReducer(base, { type: "snapshot", call: stale, at: T0 }).turns).toHaveLength(2);
    expect(liveReducer(base, { type: "snapshot", call: stale, at: T0, force: true }).turns).toHaveLength(0);
  });
});

describe("liveReducer: live events", () => {
  it("shows partial text, then replaces it with the final turn", () => {
    let state = run([
      ev(makeEvent("transcript.partial", { speaker: "caller", text: "please sha", language: "en-IN" }), T0),
      ev(makeEvent("transcript.partial", { speaker: "caller", text: "please share the o" }), T0 + 300),
    ]);
    expect(state.partial?.text).toBe("please share the o");
    expect(state.partial?.startedAt).toBe(T0);
    expect(state.partial?.updatedAt).toBe(T0 + 300);

    state = liveReducer(state, ev(makeEvent("transcript.final", { turn: makeTurn({ seq: 2, text: "please share the otp" }) }), T0 + 600));
    expect(state.partial).toBeNull();
    expect(state.turns).toHaveLength(1);
    expect(state.language.code).toBe("en-IN");
  });

  it("tracks the call state, risk, escalation and owner actions", () => {
    const risk = makeRisk({ risk_level: "medium", risk_score: 0.5 });
    const escalation = { id: "esc_1", call_id: "call_1", reason: "Delivery at the gate", status: "requested" as const, created_at: "2026-11-17T10:00:01Z", resolved_at: null, important_lines: ["I'm at your gate"] };
    let state = run([
      ev(makeEvent("state.changed", { from: "IDENTIFY_PURPOSE", to: "ESCALATE" })),
      ev(makeEvent("risk.updated", { risk })),
      ev(makeEvent("escalation.requested", { escalation, risk })),
    ]);
    expect(state.state).toBe("ESCALATE");
    expect(state.risk?.risk_level).toBe("medium");
    expect(state.escalation?.status).toBe("requested");

    const action = { id: "act_1", call_id: "call_1", action: "takeover" as const, created_at: "2026-11-17T10:00:09Z", simulated: true, result: "ok", detail: null };
    state = liveReducer(state, ev(makeEvent("owner.takeover", { action, simulated: true })));
    expect(state.ownerActions).toHaveLength(1);
    expect(state.escalation?.status).toBe("taken_over");
    // The same action delivered again (REST + WebSocket) is not duplicated.
    state = liveReducer(state, ev(makeEvent("owner.action", { action })));
    expect(state.ownerActions).toHaveLength(1);
  });

  it("an owner timeout is not announced as an event: the call leaves ESCALATE while the escalation still reads 'requested' (stale), and the REST record resolves it", () => {
    const escalation = { id: "esc_1", call_id: "call_1", reason: "Delivery at the gate", status: "requested" as const, created_at: "2026-11-17T10:00:01Z", resolved_at: null, important_lines: [] };
    let state = run([
      ev(makeEvent("state.changed", { from: "IDENTIFY_PURPOSE", to: "ESCALATE" })),
      ev(makeEvent("escalation.requested", { escalation })),
    ]);
    expect(staleEscalationId(state)).toBeNull(); // still waiting for the owner
    state = liveReducer(state, ev(makeEvent("state.changed", { from: "ESCALATE", to: "SAFE_CONTINUE" })));
    expect(state.escalation?.status).toBe("requested"); // nothing said otherwise yet
    expect(staleEscalationId(state)).toBe("esc_1");

    const action = { id: "act_9", call_id: "call_1", action: "continue" as const, created_at: "2026-11-17T10:00:05Z", simulated: true, result: "ok", detail: null };
    state = liveReducer(state, { type: "escalations", escalations: [{ ...escalation, status: "expired", resolved_at: "2026-11-17T10:00:31Z" }], ownerActions: [action] });
    expect(state.escalation).toMatchObject({ id: "esc_1", status: "expired", resolved_at: "2026-11-17T10:00:31Z" });
    expect(state.ownerActions.map((entry) => entry.id)).toEqual(["act_9"]);
    expect(staleEscalationId(state)).toBeNull();

    // A late reply that still says "requested" cannot undo a resolution that is already known.
    expect(liveReducer(state, { type: "escalations", escalations: [escalation], ownerActions: [action] }).escalation?.status).toBe("expired");
    // Merging the same owner action again does not duplicate it.
    expect(liveReducer(state, { type: "escalations", escalations: [], ownerActions: [action] }).ownerActions).toHaveLength(1);
  });

  it("an ended call is never 'stale': the outcome is read from the finished call instead", () => {
    const escalation = { id: "esc_1", call_id: "call_1", reason: "r", status: "requested" as const, created_at: "2026-11-17T10:00:01Z", resolved_at: null, important_lines: [] };
    const state = run([
      ev(makeEvent("escalation.requested", { escalation })),
      ev(makeEvent("call.ended", { reason: "caller_hung_up", state: "COMPLETED", duration_ms: 5000 })),
    ]);
    expect(state.status).toBe("ended");
    expect(staleEscalationId(state)).toBeNull();
  });

  it("follows assistant speaking, finishing and barge-in", () => {
    let state = run([ev(makeEvent("assistant.speaking", { turn_id: "turn_3", text: "Hello", locale: "en-IN", voice_id: "v", est_duration_ms: 2400 }), T0)]);
    expect(state.assistant.speaking).toMatchObject({ turnId: "turn_3", estDurationMs: 2400, startedAt: T0 });
    expect(state.listening).toBe(false);

    state = liveReducer(state, ev(makeEvent("assistant.finished", { turn_id: "other" })));
    expect(state.assistant.speaking?.turnId).toBe("turn_3"); // a different turn finishing does not stop this one
    state = liveReducer(state, ev(makeEvent("assistant.finished", { turn_id: "turn_3" })));
    expect(state.assistant.speaking).toBeNull();

    state = run([
      ev(makeEvent("assistant.speaking", { turn_id: "turn_5", text: "Long sentence", locale: "en-IN", est_duration_ms: 5000 }), T0),
      ev(makeEvent("assistant.interrupted", { turn_id: "turn_5", spoken_fraction: 0.4, interruption_ms: 180 }), T0 + 2000),
    ]);
    expect(state.assistant.speaking).toBeNull();
    expect(state.assistant.interrupted).toMatchObject({ turnId: "turn_5", spokenFraction: 0.4, at: T0 + 2000 });
  });

  it("marks the interrupted assistant turn in the transcript, from the event and from a REST turn result", () => {
    const assistant = makeTurn({ seq: 3, speaker: "assistant", source: "assistant", text: "Hi, I'm the AI assistant." });
    const afterEvent = run([
      ev(makeEvent("transcript.final", { turn: assistant }, { seq: 1 })),
      ev(makeEvent("assistant.interrupted", { turn_id: assistant.id, spoken_fraction: 0.4, interruption_ms: 180 }, { seq: 2 }), T0 + 1000),
    ]);
    expect(afterEvent.turns[0]).toMatchObject({ interrupted: true, spoken_fraction: 0.4 });

    const caller = makeTurn({ seq: 4, text: "Hello?" });
    const viaRest = liveReducer(run([ev(makeEvent("transcript.final", { turn: assistant }, { seq: 1 }))]), {
      type: "turn-result",
      at: T0,
      result: { caller_turn: caller, assistant_turn: null, interrupted_turn_id: assistant.id, call: makeCall(), risk: makeRisk(), state: "IDENTIFY_CALLER", ended: false, escalation: null },
    });
    expect(viaRest.turns.find((turn) => turn.id === assistant.id)?.interrupted).toBe(true);
    // A caller turn id is never marked, and an unknown id changes nothing.
    expect(viaRest.turns.find((turn) => turn.id === caller.id)?.interrupted).toBe(false);
  });

  it("settles the assistant when the caller speaks after the utterance's estimated end (no assistant.finished needed)", () => {
    const speaking = ev(makeEvent("assistant.speaking", { turn_id: "turn_3", text: "Hello", est_duration_ms: 2000 }, { seq: 1 }), T0);
    const early = run([speaking, ev(makeEvent("transcript.partial", { speaker: "caller", text: "wait" }, { seq: 2 }), T0 + 500)]);
    expect(early.assistant.speaking).not.toBeNull(); // barge-in territory: the server reports it with assistant.interrupted
    const late = run([speaking, ev(makeEvent("transcript.partial", { speaker: "caller", text: "yes" }, { seq: 2 }), T0 + 2600)]);
    expect(late.assistant.speaking).toBeNull();
    expect(late.assistant.lastFinishedTurnId).toBe("turn_3");
  });

  it("records language changes, provider errors, summary and the end of the call", () => {
    const state = run([
      ev(makeEvent("language.changed", { from: "en-IN", to: "hi-IN", profile: "hinglish", confidence: 0.91 })),
      ev(makeEvent("provider.error", { provider: "stt", stage: "transcribe", message: "timeout", degraded: true })),
      ev(makeEvent("summary.created", { summary: makeCall().summary })),
      ev(makeEvent("call.ended", { reason: "refused", state: "END_SPAM", duration_ms: 12000 }), T0 + 5),
    ]);
    expect(state.language).toEqual({ code: "hi-IN", profile: "hinglish", confidence: 0.91 });
    expect(state.languageEvents).toHaveLength(1);
    expect(state.providerErrors[0]).toMatchObject({ provider: "stt", degraded: true });
    expect(state.summary?.text).toMatch(/bank/);
    expect(state.status).toBe("ended");
    expect(state.state).toBe("END_SPAM");
    expect(state.ended?.durationMs).toBe(12000);
    expect(state.listening).toBe(false);
  });

  it("folds a REST turn result in idempotently with the matching websocket event", () => {
    const caller = makeTurn({ seq: 2, text: "Hello" });
    const assistant = makeTurn({ seq: 3, speaker: "assistant", text: "Who is calling?", source: "assistant" });
    let state = run([ev(makeEvent("transcript.final", { turn: caller }))]);
    state = liveReducer(state, {
      type: "turn-result",
      at: T0,
      result: { caller_turn: caller, assistant_turn: assistant, interrupted_turn_id: null, call: makeCall(), risk: makeRisk(), state: "IDENTIFY_PURPOSE", ended: false, escalation: null },
    });
    expect(state.turns.map((t) => t.id)).toEqual(["turn_2", "turn_3"]);
    expect(state.state).toBe("IDENTIFY_PURPOSE");
    expect(state.risk?.risk_level).toBe("high");
  });

  it("keeps the event log capped", () => {
    const events = Array.from({ length: MAX_LOGGED_EVENTS + 25 }, (_, i) => ev(makeEvent("call.listening", {}, { seq: i + 1 })));
    const state = run(events);
    expect(state.events).toHaveLength(MAX_LOGGED_EVENTS);
    expect(state.eventCount).toBe(MAX_LOGGED_EVENTS + 25);
    expect(state.events[0]?.seq).toBe(26);
  });
});

describe("liveReducer: sequence, gaps and resync", () => {
  it("ignores duplicates and old sequence numbers", () => {
    const first = ev(makeEvent("state.changed", { from: "A", to: "B" }, { seq: 5 }));
    const state = run([first, first, ev(makeEvent("state.changed", { from: "B", to: "OLD" }, { seq: 4 }))]);
    expect(state.state).toBe("B");
    expect(state.lastSeq).toBe(5);
    expect(state.eventCount).toBe(1);
  });

  it("holds live events when a seq gap appears and drains them after the backfill, in order", () => {
    let state = run([ev(makeEvent("state.changed", { from: "A", to: "B" }, { seq: 5 }))]);
    // seq 6 and 7 are missing: 8 arrives first
    state = liveReducer(state, ev(makeEvent("state.changed", { from: "D", to: "E" }, { seq: 8 })));
    expect(state.gapAfterSeq).toBe(5);
    expect(state.state).toBe("B"); // not applied yet
    expect(state.pending).toHaveLength(1);

    const backfill = [
      makeEvent("state.changed", { from: "B", to: "C" }, { seq: 6 }),
      makeEvent("state.changed", { from: "C", to: "D" }, { seq: 7 }),
      makeEvent("state.changed", { from: "D", to: "E" }, { seq: 8 }),
    ];
    state = liveReducer(state, { type: "backfill", events: [...backfill].reverse(), at: T0 });
    expect(state.state).toBe("E");
    expect(state.lastSeq).toBe(8);
    expect(state.gapAfterSeq).toBeNull();
    expect(state.pending).toHaveLength(0);
    expect(state.events.map((e) => e.seq)).toEqual([5, 6, 7, 8]);
  });

  it("treats stream.resync as a gap from the last applied seq and queues events until the backfill", () => {
    let state = run([ev(makeEvent("state.changed", { from: "A", to: "B" }, { seq: 3 }))]);
    state = liveReducer(state, ev(makeEvent("stream.resync", {}, { seq: 3 })));
    expect(state.gapAfterSeq).toBe(3);
    expect(state.resyncCount).toBe(1);

    state = liveReducer(state, ev(makeEvent("transcript.final", { turn: makeTurn({ seq: 9 }) }, { seq: 9 })));
    expect(state.turns).toHaveLength(0); // held
    state = liveReducer(state, { type: "backfill", events: [makeEvent("state.changed", { from: "B", to: "C" }, { seq: 4 })], at: T0 });
    expect(state.state).toBe("C");
    expect(state.turns).toHaveLength(1); // the held event was applied after the backfill
    expect(state.gapAfterSeq).toBeNull();
  });

  it("only logs backfilled events the model already has, without re-applying them", () => {
    const state0 = run([ev(makeEvent("state.changed", { from: "A", to: "B" }, { seq: 2 })), ev(makeEvent("state.changed", { from: "B", to: "C" }, { seq: 3 }))]);
    const state = liveReducer(state0, { type: "backfill", at: T0, events: [makeEvent("state.changed", { from: "A", to: "STALE" }, { seq: 1 }), makeEvent("state.changed", { from: "B", to: "C" }, { seq: 3 })] });
    expect(state.state).toBe("C");
    expect(state.events.map((e) => e.seq)).toEqual([2, 3, 1]);
  });

  it("falls back to a forced REST snapshot and re-applies held events on top", () => {
    let state = run([ev(makeEvent("state.changed", { from: "A", to: "B" }, { seq: 5 }))]);
    state = liveReducer(state, ev(makeEvent("transcript.final", { turn: makeTurn({ seq: 20, text: "late" }) }, { seq: 12 })));
    expect(state.gapAfterSeq).toBe(5);
    state = liveReducer(state, { type: "snapshot", call: makeCall(), at: T0, force: true });
    expect(state.gapAfterSeq).toBeNull();
    expect(state.turns.some((t) => t.text === "late")).toBe(true);
  });
});

describe("connection status", () => {
  it("records connection transitions and resets the attempt counter when open", () => {
    let state = liveReducer(initialLiveState("c"), { type: "connection", status: "reconnecting", attempt: 3 });
    expect(state).toMatchObject({ connection: "reconnecting", reconnectAttempt: 3 });
    state = liveReducer(state, { type: "connection", status: "open" });
    expect(state).toMatchObject({ connection: "open", reconnectAttempt: 0 });
  });
});

describe("inferSpeaking", () => {
  const assistantTurn = (createdAt: string, extra = {}) =>
    makeTurn({ seq: 1, speaker: "assistant", source: "assistant", created_at: createdAt, speech: { text: "Hi there", locale: "en-IN", voice_id: "v", rate: 1, style: null, ssml: null, transliteration: null, est_duration_ms: 6000 }, ...extra });

  it("treats a fresh assistant turn as still speaking for late joiners", () => {
    const turns = [assistantTurn("2026-11-17T10:00:00.000Z")];
    expect(inferSpeaking(turns, T0 + 2000)).toMatchObject({ turnId: "turn_1", estDurationMs: 6000, startedAt: T0 });
    expect(inferSpeaking(turns, T0 + 7000)).toBeNull();
  });

  it("does not guess for caller turns, interrupted turns or turns without a speech plan", () => {
    expect(inferSpeaking([makeTurn({ seq: 1 })], T0)).toBeNull();
    expect(inferSpeaking([assistantTurn("2026-11-17T10:00:00.000Z", { interrupted: true })], T0)).toBeNull();
    expect(inferSpeaking([assistantTurn("2026-11-17T10:00:00.000Z", { speech: null })], T0)).toBeNull();
  });
});

describe("speaking state reported by the server snapshot", () => {
  const assistantTurn = (createdAt: string) =>
    makeTurn({ seq: 1, speaker: "assistant", source: "assistant", created_at: createdAt, speech: { text: "Hi there", locale: "en-IN", voice_id: "v", rate: 1, style: null, ssml: null, transliteration: null, est_duration_ms: 6000 } });
  const activeCall = (extra: Parameters<typeof makeCall>[0] = {}) => makeCall({ status: "active", ended_at: null, duration_ms: null, turns: [assistantTurn("2026-11-17T10:00:00.000Z")], ...extra });

  it("trusts assistant_speaking and speaking_turn_id, with elapsed time taken from the snapshot's own timestamp (no clock skew)", () => {
    const call = activeCall({ assistant_speaking: true, speaking_turn_id: "turn_1" });
    const clientNow = T0 + 90_000 + 2000; // the client clock is 90 s ahead of the server
    const state = run([ev(makeEvent("call.snapshot", { call }, { seq: 1, ts: new Date(T0 + 2000).toISOString() }), clientNow)]);
    expect(state.assistant.speaking).toMatchObject({ turnId: "turn_1", estDurationMs: 6000, startedAt: clientNow - 2000 });
  });

  it("assistant_speaking: false wins over the created_at inference", () => {
    const state = run([ev(makeEvent("call.snapshot", { call: activeCall({ assistant_speaking: false, speaking_turn_id: null }) }, { seq: 1 }), T0 + 1000)]);
    expect(state.assistant.speaking).toBeNull();
  });

  it("falls back to the created_at inference when an older server omits the fields", () => {
    const call: Partial<ReturnType<typeof activeCall>> = activeCall();
    delete call.assistant_speaking;
    delete call.speaking_turn_id;
    const state = run([ev(makeEvent("call.snapshot", { call }, { seq: 1 }), T0 + 1000)]);
    expect(state.assistant.speaking).toMatchObject({ turnId: "turn_1", startedAt: T0 });
  });

  it("also applies to a forced REST snapshot, and never marks an ended call as speaking", () => {
    const live = run([], initialLiveState("call_1"));
    const speaking = liveReducer(live, { type: "snapshot", call: activeCall({ assistant_speaking: true, speaking_turn_id: "turn_1" }), at: T0 + 1000, force: true });
    expect(speaking.assistant.speaking?.turnId).toBe("turn_1");
    const ended = liveReducer(speaking, { type: "snapshot", call: makeCall({ status: "ended", assistant_speaking: true, speaking_turn_id: "turn_1", turns: [assistantTurn("2026-11-17T10:00:00.000Z")] }), at: T0 + 1000, force: true });
    expect(ended.assistant.speaking).toBeNull();
  });
});
