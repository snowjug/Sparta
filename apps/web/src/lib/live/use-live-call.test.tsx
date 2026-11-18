import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { ApiClient } from "@/lib/api/client";
import { ApiProvider } from "@/lib/api/provider";
import { AuthProvider } from "@/lib/auth/provider";
import { modeFor } from "@/components/call/live-voice-stage";
import { createFakeApi, json } from "@/test/fake-fetch";
import { makeCall, makeEvent, makeRisk, makeTurn, resetEventSeq } from "@/test/fixtures";
import type { CallDetail, LiveEvent } from "@/lib/api/types";
import { useLiveCall } from "./use-live-call";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readyState = 0;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  emit(event: LiveEvent | { type: "ping" }) {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }
  drop(code = 1006) {
    this.readyState = 3;
    this.onclose?.({ code, reason: "" } as CloseEvent);
  }
  close() {
    this.readyState = 3;
  }
}

function setup(eventsByAfter: (after: number) => LiveEvent[] = () => [], detail?: () => CallDetail) {
  let tickets = 0;
  const api = createFakeApi({
    "GET /api/v1/calls/call_1": () => (detail ? detail() : makeCall({ status: "active", state: "IDENTIFY_CALLER", ended_at: null, duration_ms: null, summary: null, turns: [makeTurn({ seq: 1, speaker: "assistant", source: "assistant", language_profile: null })], risk: null })),
    "POST /api/v1/live/ticket": () => json({ ticket: `t${++tickets}`, expires_in: 60, ws_url: "ws://ignored" }),
    "GET /api/v1/calls/call_1/events": (req) => eventsByAfter(Number(req.query.get("after_seq"))),
  });
  const client = new ApiClient({ baseUrl: "http://api.test", fetchImpl: api.fetch });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <AuthProvider>
      <ApiProvider client={client}>{children}</ApiProvider>
    </AuthProvider>
  );
  const view = renderHook(() => useLiveCall("call_1"), { wrapper });
  return { api, ...view };
}

const socket = (index = FakeWebSocket.instances.length - 1) => FakeWebSocket.instances[index]!;

beforeEach(() => {
  FakeWebSocket.instances = [];
  resetEventSeq(0);
  vi.stubGlobal("WebSocket", FakeWebSocket);
});
afterEach(() => vi.useRealTimers());

describe("useLiveCall", () => {
  it("renders from REST immediately, then follows the websocket: ticket -> snapshot -> events", async () => {
    const { result, api } = setup();
    await waitFor(() => expect(result.current.state.hydrated).toBe(true)); // REST snapshot
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(FakeWebSocket.instances[0]!.url).toBe("ws://api.test/api/v1/live/call_1?ticket=t1"); // built from the trusted base
    expect(api.callsTo("POST /api/v1/live/ticket")[0]?.body).toEqual({ call_id: "call_1" });

    act(() => socket().open());
    expect(result.current.state.connection).toBe("open");
    act(() => socket().emit(makeEvent("call.snapshot", { call: makeCall({ status: "active", state: "IDENTIFY_CALLER" }) }, { seq: 3 })));
    act(() => socket().emit({ type: "ping" }));
    act(() => socket().emit(makeEvent("transcript.partial", { speaker: "caller", text: "hello there" }, { seq: 4 })));
    expect(result.current.state.partial?.text).toBe("hello there");
    act(() => socket().emit(makeEvent("risk.updated", { risk: makeRisk({ risk_level: "medium" }) }, { seq: 5 })));
    expect(result.current.state.risk?.risk_level).toBe("medium");
    expect(result.current.state.lastSeq).toBe(5);
  });

  it("fills a sequence gap from GET /calls/{id}/events?after_seq= before applying later events", async () => {
    const missing = [makeEvent("state.changed", { from: "DISCLOSURE", to: "IDENTIFY_CALLER" }, { seq: 4 }), makeEvent("state.changed", { from: "IDENTIFY_CALLER", to: "ASSESSING" }, { seq: 5 })];
    const { result, api } = setup((after) => (after === 3 ? missing : []));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => socket().open());
    act(() => socket().emit(makeEvent("call.snapshot", { call: makeCall({ status: "active" }) }, { seq: 3 })));
    act(() => socket().emit(makeEvent("state.changed", { from: "ASSESSING", to: "SAFE_CONTINUE" }, { seq: 6 }))); // 4 and 5 were lost
    expect(result.current.state.gapAfterSeq).toBe(3);
    await waitFor(() => expect(api.callsTo("GET /api/v1/calls/call_1/events").some((c) => c.query.get("after_seq") === "3")).toBe(true));
    await waitFor(() => expect(result.current.state.gapAfterSeq).toBeNull());
    expect(result.current.state.state).toBe("SAFE_CONTINUE");
    expect(result.current.state.lastSeq).toBe(6);
    expect(result.current.state.events.map((e) => e.seq)).toEqual([3, 4, 5, 6]);
  });

  it("handles stream.resync by refetching the persisted event log", async () => {
    const { result, api } = setup((after) => (after === 3 ? [makeEvent("transcript.final", { turn: makeTurn({ seq: 9, text: "caught up" }) }, { seq: 4 })] : []));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => socket().open());
    act(() => socket().emit(makeEvent("call.snapshot", { call: makeCall({ status: "active" }) }, { seq: 3 })));
    act(() => socket().emit(makeEvent("stream.resync", {}, { seq: 3 })));
    await waitFor(() => expect(result.current.state.turns.some((t) => t.text === "caught up")).toBe(true));
    expect(result.current.state.resyncCount).toBe(1);
    expect(api.callsTo("GET /api/v1/calls/call_1/events").length).toBeGreaterThan(0);
  });

  it("reconnects after a drop with a fresh ticket and resumes from the last sequence", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const resumed: number[] = [];
    const { result } = setup((after) => {
      resumed.push(after);
      return after === 4 ? [makeEvent("transcript.final", { turn: makeTurn({ seq: 7, text: "said while offline" }) }, { seq: 5 })] : [];
    });
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => socket().open());
    act(() => socket().emit(makeEvent("call.snapshot", { call: makeCall({ status: "active" }) }, { seq: 3 })));
    act(() => socket().emit(makeEvent("state.changed", { from: "A", to: "B" }, { seq: 4 })));

    act(() => socket().drop(1006));
    expect(result.current.state.connection).toBe("reconnecting");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    expect(socket().url).toContain("ticket=t2");
    act(() => socket().open());
    await vi.waitFor(() => expect(resumed).toContain(4)); // GET events?after_seq=4
    await vi.waitFor(() => expect(result.current.state.turns.some((t) => t.text === "said while offline")).toBe(true));
    expect(result.current.state.connection).toBe("open");
  });

  it("learns from REST that an escalation expired: when the owner does not answer in time the server only reports state.changed", async () => {
    const requested = { id: "esc_1", call_id: "call_1", reason: "Delivery at the gate", status: "requested" as const, created_at: "2026-11-17T10:00:01Z", resolved_at: null, important_lines: [] };
    const expired = { ...requested, status: "expired" as const, resolved_at: "2026-11-17T10:00:31Z" };
    let timedOut = false;
    const detail = () =>
      makeCall({ status: "active", state: timedOut ? "SAFE_CONTINUE" : "ESCALATE", ended_at: null, duration_ms: null, summary: null, escalations: [timedOut ? expired : requested] });
    const { result, api } = setup(undefined, detail);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => socket().open());
    act(() => socket().emit(makeEvent("call.snapshot", { call: detail() }, { seq: 3 })));
    expect(result.current.state.escalation?.status).toBe("requested");
    const readsBefore = api.callsTo("GET /api/v1/calls/call_1").length;

    timedOut = true;
    act(() => socket().emit(makeEvent("state.changed", { from: "ESCALATE", to: "SAFE_CONTINUE" }, { seq: 4 })));
    await waitFor(() => expect(result.current.state.escalation?.status).toBe("expired"));
    expect(result.current.state.state).toBe("SAFE_CONTINUE");
    expect(api.callsTo("GET /api/v1/calls/call_1").length).toBe(readsBefore + 1); // one authoritative read, no polling loop
  });

  it("does not ask REST while the call is still waiting for the owner", async () => {
    const requested = { id: "esc_1", call_id: "call_1", reason: "r", status: "requested" as const, created_at: "2026-11-17T10:00:01Z", resolved_at: null, important_lines: [] };
    const detail = () => makeCall({ status: "active", state: "ESCALATE", ended_at: null, duration_ms: null, summary: null, escalations: [requested] });
    const { result, api } = setup(undefined, detail);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => socket().open());
    act(() => socket().emit(makeEvent("call.snapshot", { call: detail() }, { seq: 3 })));
    act(() => socket().emit(makeEvent("transcript.partial", { speaker: "caller", text: "hello" }, { seq: 4 })));
    const readsBefore = api.callsTo("GET /api/v1/calls/call_1").length;
    await new Promise((resolve) => setTimeout(resolve, 150));
    expect(api.callsTo("GET /api/v1/calls/call_1").length).toBe(readsBefore);
    expect(result.current.state.escalation?.status).toBe("requested");
  });

  it("shows the call as ended only after its closing sentence, frame by frame, and a snapshot older than the stream cannot revive it", async () => {
    const { result } = setup();
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => socket().open());
    const sentence = { text: "I can't share that. Goodbye.", locale: "en-IN", voice_id: "v", rate: 1, style: null, ssml: null, transliteration: null, est_duration_ms: 5000 };
    const intro = makeTurn({ seq: 1, speaker: "assistant", source: "assistant", language_profile: null });
    const otp = makeTurn({ seq: 2, text: "Please read out the OTP." });
    const goodbye = makeTurn({ seq: 3, speaker: "assistant", source: "assistant", text: sentence.text, speech: sentence, state_after: "END_SPAM", language_profile: null });
    const active = (extra: Partial<CallDetail>) => makeCall({ status: "active", state: "IDENTIFY_PURPOSE", ended_at: null, duration_ms: null, summary: null, assistant_speaking: false, turns: [intro, otp], ...extra });
    act(() => socket().emit(makeEvent("call.snapshot", { call: active({}) }, { seq: 20 })));

    const modes: string[] = [];
    const observe = () => {
      const mode = modeFor(result.current.state, Date.now());
      if (modes.at(-1) !== mode) modes.push(mode);
    };
    observe();
    // The server's order: the end state, then the closing turn, then the announcement of its speech; one frame at a time.
    const frames = [
      makeEvent("state.changed", { from: "IDENTIFY_PURPOSE", to: "END_SPAM" }, { seq: 21 }),
      makeEvent("risk.updated", { risk: makeRisk() }, { seq: 22 }),
      makeEvent("transcript.final", { turn: goodbye }, { seq: 23 }),
      makeEvent("assistant.speaking", { turn_id: goodbye.id, text: sentence.text, locale: "en-IN", voice_id: "v", est_duration_ms: 5000 }, { seq: 24 }),
    ];
    for (const frame of frames) {
      act(() => socket().emit(frame));
      observe();
    }
    expect(modes).toEqual(["thinking", "assistant_speaking"]);

    for (const frame of [
      makeEvent("assistant.finished", { turn_id: goodbye.id }, { seq: 25 }),
      makeEvent("state.changed", { from: "END_SPAM", to: "COMPLETED" }, { seq: 26 }),
      makeEvent("call.ended", { reason: "refused_and_ended", state: "COMPLETED", duration_ms: 9000 }, { seq: 27 }),
    ]) {
      act(() => socket().emit(frame));
      observe();
    }
    expect(modes).toEqual(["thinking", "assistant_speaking", "ended"]);
    expect(result.current.state.status).toBe("ended");

    // A snapshot that was built while the sentence was playing arrives after the end (slow network).
    act(() => socket().emit(makeEvent("call.snapshot", { call: active({ state: "END_SPAM", turns: [intro, otp, goodbye], assistant_speaking: true, speaking_turn_id: goodbye.id }) }, { seq: 24 })));
    observe();
    expect(modes).toEqual(["thinking", "assistant_speaking", "ended"]);
    expect(result.current.state.status).toBe("ended");
    expect(result.current.state.state).toBe("COMPLETED");
    expect(result.current.state.assistant.speaking).toBeNull();
  });

  it("stops reconnecting once the call has ended", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { result } = setup();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => socket().open());
    act(() => socket().emit(makeEvent("call.snapshot", { call: makeCall({ status: "active" }) }, { seq: 3 })));
    act(() => socket().emit(makeEvent("call.ended", { reason: "refused", state: "END_SPAM", duration_ms: 9000 }, { seq: 4 })));
    expect(result.current.state.status).toBe("ended");
    act(() => socket().drop(1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(result.current.state.connection).toBe("closed");
  });

  it("applies REST turn results idempotently and can refresh from REST", async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.state.hydrated).toBe(true));
    const turn = makeTurn({ seq: 2, text: "from rest" });
    const turnResult = { caller_turn: turn, assistant_turn: null, interrupted_turn_id: null, call: makeCall(), risk: makeRisk(), state: "ASSESSING" as const, ended: false, escalation: null };
    act(() => result.current.applyTurnResult(turnResult));
    act(() => result.current.applyTurnResult(turnResult));
    expect(result.current.state.turns.filter((t) => t.id === "turn_2")).toHaveLength(1);
    await act(async () => result.current.refresh());
    expect(result.current.state.turns).toHaveLength(1); // forced REST snapshot replaced the model
  });
});
