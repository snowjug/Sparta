import { describe, expect, it } from "vitest";
import { parseFrame, describeEvent } from "./events";

describe("parseFrame", () => {
  it("accepts a well-formed envelope and normalises missing optional fields", () => {
    const frame = parseFrame(JSON.stringify({ type: "transcript.final", call_id: "c1", seq: 7, data: { turn: {} } }));
    expect(frame).toMatchObject({ type: "transcript.final", call_id: "c1", seq: 7, simulated: false });
    expect(typeof (frame as { ts: string }).ts).toBe("string");
  });

  it("recognises ping frames, which have no call_id or seq", () => {
    expect(parseFrame('{"type":"ping"}')).toEqual({ type: "ping" });
  });

  it("rejects garbage, arrays, missing call ids and oversized frames", () => {
    expect(parseFrame("not json")).toBeNull();
    expect(parseFrame("[]")).toBeNull();
    expect(parseFrame('{"type":"x"}')).toBeNull();
    expect(parseFrame('{"call_id":"c1"}')).toBeNull();
    expect(parseFrame('{"type":"","call_id":"c1"}')).toBeNull();
    expect(parseFrame("x".repeat(2_000_001))).toBeNull();
    expect(parseFrame(42)).toBeNull();
  });

  it("clamps invalid seq to 0 and non-object data to {}", () => {
    expect(parseFrame({ type: "x", call_id: "c", seq: -3, data: [1] })).toMatchObject({ seq: 0, data: {} });
    expect(parseFrame({ type: "x", call_id: "c", seq: "9" })).toMatchObject({ seq: 0 });
  });
});

describe("describeEvent", () => {
  it("summarises events for the log viewer without dumping whole payloads", () => {
    const long = "word ".repeat(40);
    const text = describeEvent({ type: "transcript.partial", call_id: "c", seq: 1, ts: "", simulated: false, data: { speaker: "caller", text: long } });
    expect(text.length).toBeLessThan(90);
    expect(describeEvent({ type: "state.changed", call_id: "c", seq: 2, ts: "", simulated: false, data: { from: "A", to: "B" } })).toBe("A → B");
    expect(describeEvent({ type: "assistant.interrupted", call_id: "c", seq: 3, ts: "", simulated: false, data: { turn_id: "turn_3", spoken_fraction: 0.62 } })).toContain("62%");
    expect(describeEvent({ type: "stream.resync", call_id: "c", seq: 4, ts: "", simulated: false, data: {} })).toMatch(/resync/);
    expect(describeEvent({ type: "something.new", call_id: "c", seq: 5, ts: "", simulated: false, data: {} })).toBe("something.new");
  });
});
