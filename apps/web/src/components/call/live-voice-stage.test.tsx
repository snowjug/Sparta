import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveVoiceStage } from "./live-voice-stage";
import { initialLiveState, type LiveCallState } from "@/lib/live/reducer";
import { SPEAKING_GRACE_MS } from "@/lib/voice-activity";
import { installFakeCanvas, mockMatchMedia } from "@/test/media";

function endedModel(overrides: Partial<LiveCallState> = {}): LiveCallState {
  return {
    ...initialLiveState("call_1"),
    hydrated: true,
    connection: "open",
    status: "ended",
    state: "END_SPAM",
    ...overrides,
  };
}

const closingSentence = (startedAt: number, estDurationMs: number) => ({ turnId: "turn_5", text: "I can't help with that. Goodbye.", locale: "en-IN", voiceId: null, estDurationMs, startedAt });

describe("LiveVoiceStage clock", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockMatchMedia({});
    installFakeCanvas();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  const label = () => screen.getByTestId("voice-stage-label");

  it("lets the closing sentence's window elapse by time alone after the call was marked ended early (a REST turn result, `assistant.finished` lost)", () => {
    const live = endedModel({ assistant: { speaking: closingSentence(Date.now(), 2000), lastFinishedTurnId: null, interrupted: null } });
    render(<LiveVoiceStage live={live} />);
    expect(label()).toHaveTextContent("Sparta is speaking");
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(label()).toHaveTextContent("Sparta is speaking");
    act(() => {
      vi.advanceTimersByTime(1000 + SPEAKING_GRACE_MS + 300);
    });
    expect(label()).toHaveTextContent("Call ended");
    expect(screen.getByTestId("voice-stage")).toHaveAttribute("data-mode", "ended");
  });

  it("does not tick for a call that has ended and is not speaking (finished screens stay idle)", () => {
    const interval = vi.spyOn(globalThis, "setInterval");
    render(<LiveVoiceStage live={endedModel()} />);
    expect(screen.getByTestId("voice-stage")).toHaveAttribute("data-mode", "ended");
    expect(interval).not.toHaveBeenCalled();
  });
});
