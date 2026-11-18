import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { VoiceStage, staticFrame } from "./voice-stage";
import { RiskMeter, SignalList } from "./risk-panel";
import { StateStepper } from "./state-stepper";
import { Transcript } from "./transcript";
import { OwnerControls } from "./owner-controls";
import { installFakeCanvas, mockMatchMedia } from "@/test/media";
import { findOpenDialog } from "@/test/dialog";
import { renderWithApp } from "@/test/render";
import { apiError, createFakeApi, json } from "@/test/fake-fetch";
import { makeCaps, makeCall, makeSignal, makeTurn } from "@/test/fixtures";
import { makeAssistantRoutes } from "@/test/routes";
import type { AssistantSpeech } from "@/lib/live/reducer";

const speaking: AssistantSpeech = { turnId: "turn_3", text: "Hello there, who is calling?", locale: "en-IN", voiceId: null, estDurationMs: 3000, startedAt: Date.now() };

describe("VoiceStage", () => {
  it("exposes the real call state as text and data attributes (state is never colour only)", () => {
    render(<VoiceStage mode="assistant_speaking" riskLevel="medium" assistant={speaking} partial={null} interrupted={null} />);
    const stage = screen.getByTestId("voice-stage");
    expect(stage).toHaveAttribute("data-mode", "assistant_speaking");
    expect(stage).toHaveAttribute("data-risk", "medium");
    const label = screen.getByTestId("voice-stage-label");
    expect(label).toHaveTextContent("Sparta is speaking");
    expect(label).toHaveAttribute("aria-live", "polite");
  });

  it("states how far the assistant was cut off when interrupted", () => {
    render(<VoiceStage mode="interrupted" riskLevel="low" assistant={null} partial={null} interrupted={{ turnId: "turn_3", spokenFraction: 0.62, interruptionMs: 120, at: Date.now() }} />);
    expect(screen.getByTestId("voice-stage-label")).toHaveTextContent("Caller interrupted · cut off at 62%");
  });

  it("animates with requestAnimationFrame when motion is allowed and the mode is animated", () => {
    mockMatchMedia({});
    installFakeCanvas();
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
    render(<VoiceStage mode="assistant_speaking" riskLevel="low" assistant={speaking} partial={null} interrupted={null} />);
    expect(screen.getByTestId("voice-stage")).toHaveAttribute("data-reduced-motion", "false");
    expect(raf).toHaveBeenCalled();
    raf.mockRestore();
  });

  it("does not animate at all with prefers-reduced-motion: a still frame and the text label carry the state", () => {
    mockMatchMedia({ "(prefers-reduced-motion: reduce)": true });
    const canvas = installFakeCanvas();
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
    const { container } = render(<VoiceStage mode="listening" riskLevel="low" assistant={null} partial={null} interrupted={null} />);
    expect(screen.getByTestId("voice-stage")).toHaveAttribute("data-reduced-motion", "true");
    expect(raf).not.toHaveBeenCalled();
    expect(canvas.draws()).toBeGreaterThan(0); // one static frame is drawn
    expect(container.querySelector(".animate-breathe")).toBeNull();
    expect(screen.getByTestId("voice-stage-label")).toHaveTextContent("Listening");
    raf.mockRestore();
  });

  it("uses a flat, state-coded static frame under reduced motion", () => {
    const frame = staticFrame("assistant_speaking");
    expect(new Set(frame.bars).size).toBe(1);
    expect(frame.progress).toBeNull();
    expect(staticFrame("ended").energy).toBeLessThan(staticFrame("assistant_speaking").energy);
  });

  it("shows a check for completion and a bell while waiting for the owner", () => {
    mockMatchMedia({});
    const { container, rerender } = render(<VoiceStage mode="ended" riskLevel="low" assistant={null} partial={null} interrupted={null} />);
    expect(container.querySelector("svg path[stroke-dasharray]")).not.toBeNull();
    rerender(<VoiceStage mode="escalated" riskLevel="low" assistant={null} partial={null} interrupted={null} />);
    expect(screen.getByTestId("voice-stage-label")).toHaveTextContent("Waiting for you");
  });
});

describe("RiskMeter and SignalList", () => {
  it("never claims certainty when there is not enough evidence", () => {
    render(<RiskMeter level="unknown" score={0.7} confidence={0.2} />);
    const meter = screen.getByRole("meter", { name: "Risk score" });
    expect(meter).toHaveAttribute("aria-valuenow", "0");
    expect(meter).toHaveAttribute("aria-valuetext", "Not enough evidence yet");
    expect(screen.getByText("No score yet")).toBeInTheDocument();
  });

  it("spells out the level and numbers for assistive tech", () => {
    render(<RiskMeter level="high" score={0.93} confidence={0.9} />);
    const meter = screen.getByRole("meter", { name: "Risk score" });
    expect(meter).toHaveAttribute("aria-valuenow", "93");
    expect(meter).toHaveAttribute("aria-valuetext", expect.stringMatching(/High risk\. Risk score 93%\. Confidence 90%/));
    expect(screen.getByTestId("risk-meter")).toHaveAttribute("data-risk", "high");
  });

  it("lists evidence with excerpts as plain text and links back to the turns", () => {
    render(<SignalList signals={[makeSignal({ evidence_excerpt: "<b>share the otp</b>" }), makeSignal({ code: "LEGIT_DELIVERY_COORDINATION", kind: "legitimate", severity: "info", evidence_turn_ids: ["turn_4", "turn_6"], evidence_excerpt: null, description: "Courier at the gate" })]} />);
    const items = screen.getAllByTestId("signal-item");
    expect(items).toHaveLength(2);
    expect(within(items[0]!).getByText("<b>share the otp</b>", { exact: false })).toBeInTheDocument();
    expect(items[0]!.querySelector("b")).toBeNull();
    expect(within(items[1]!).getByText("Sign of a genuine call")).toBeInTheDocument();
    expect(within(items[1]!).getByRole("link", { name: "turn 6" })).toHaveAttribute("href", "#turn-turn_6");
  });
});

describe("StateStepper", () => {
  it("marks earlier steps done, the current step, and names the outcome", () => {
    render(<StateStepper state="IDENTIFY_PURPOSE" status="active" />);
    const items = within(screen.getByRole("list", { name: "Call progress" })).getAllByRole("listitem");
    expect(items).toHaveLength(6);
    expect(items[3]).toHaveAttribute("aria-current", "step");
    expect(items[0]).toHaveTextContent("done");
    expect(items[5]).toHaveTextContent("not reached yet");
  });

  it("shows how the call ended", () => {
    render(<StateStepper state="END_SPAM" status="ended" />);
    expect(screen.getByText("Ended: spam")).toBeInTheDocument();
    expect(screen.getByTestId("state-stepper")).toHaveAttribute("data-state", "END_SPAM");
  });
});

describe("Transcript", () => {
  const turns = [
    makeTurn({ seq: 1, speaker: "assistant", text: "Hi, I'm Atharv's AI assistant.", source: "assistant", language_profile: null }),
    makeTurn({ seq: 2, text: "Please share the OTP", language: "en-IN", language_profile: "english" }),
    makeTurn({ seq: 3, text: "Aapka KYC pending hai", language: "hi-IN", language_profile: "hinglish", translation: "Your KYC is pending" }),
    makeTurn({ seq: 4, text: "Nimma account block aagutte", language: "kn-IN", language_profile: "kanglish", translation: null }),
  ];

  it("shows per-turn language chips with Hinglish/Kanglish labels and language-change markers", () => {
    render(<Transcript turns={turns} showTranslation={false} />);
    expect(screen.getAllByTestId("turn")).toHaveLength(4);
    const hindiTurn = document.getElementById("turn-turn_3")!;
    expect(within(hindiTurn).getAllByText("Hinglish", { exact: false }).length).toBeGreaterThan(0);
    const kannadaTurn = document.getElementById("turn-turn_4")!;
    expect(within(kannadaTurn).getAllByText("Kanglish", { exact: false }).length).toBeGreaterThan(0);
    const markers = screen.getAllByTestId("language-change");
    expect(markers).toHaveLength(2);
    expect(markers[0]).toHaveTextContent("English → Hindi (Hinglish)");
    expect(markers[1]).toHaveTextContent("Hindi → Kannada (Kanglish)");
    expect(screen.getByText("Aapka KYC pending hai")).toHaveAttribute("lang", "hi-IN");
  });

  it("toggles translations, and says plainly when one is missing", () => {
    const { rerender } = render(<Transcript turns={turns} showTranslation={false} />);
    expect(screen.queryByTestId("translation")).toBeNull();
    rerender(<Transcript turns={turns} showTranslation />);
    const lines = screen.getAllByTestId("translation");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toHaveTextContent("Your KYC is pending");
    expect(lines[1]).toHaveTextContent("No translation available for this turn.");
  });

  it("highlights evidence and labels the signal on the turn, rendering text only", () => {
    render(<Transcript turns={turns} signals={[makeSignal({ evidence_turn_ids: ["turn_2"], evidence_excerpt: "share the otp" })]} showTranslation={false} />);
    const turn = document.getElementById("turn-turn_2")!;
    expect(within(turn).getByTestId("evidence-mark")).toHaveTextContent("share the OTP");
    expect(within(turn).getByText("Asked for a one-time code (OTP)")).toBeInTheDocument();
  });

  it("renders the live partial turn separately and never as HTML", () => {
    render(<Transcript live turns={turns.slice(0, 2)} partial={{ speaker: "caller", text: "<script>alert(1)</script> hello", language: "en-IN", startedAt: 1, updatedAt: 2 }} showTranslation={false} />);
    expect(screen.getByTestId("partial-turn")).toHaveTextContent("<script>alert(1)</script> hello");
    expect(document.querySelector("script")).toBeNull();
    const log = screen.getByRole("log");
    expect(log).toHaveAttribute("aria-live", "polite");
  });

  it("caps the rendered turns and reveals earlier ones on request", async () => {
    const many = Array.from({ length: 30 }, (_, i) => makeTurn({ seq: i + 1, text: `turn number ${i + 1}` }));
    render(<Transcript turns={many} showTranslation={false} maxRendered={10} />);
    expect(screen.getAllByTestId("turn")).toHaveLength(10);
    await userEvent.click(screen.getByRole("button", { name: /Show 20 earlier turns/ }));
    expect(screen.getAllByTestId("turn")).toHaveLength(30);
  });

  it("explains an empty transcript", () => {
    render(<Transcript turns={[]} showTranslation={false} empty={<p>Waiting for the first words.</p>} />);
    expect(screen.getByText("Waiting for the first words.")).toBeInTheDocument();
  });
});

describe("OwnerControls", () => {
  function setup(overrides: Parameters<typeof makeCaps>[0] = {}, extra: Record<string, () => Response | unknown> = {}) {
    const api = createFakeApi({
      ...makeAssistantRoutes(),
      "POST /api/v1/calls/call_1/takeover": () => ({ action: { id: "a1", call_id: "call_1", action: "takeover", created_at: "2026-11-17T10:00:00Z", simulated: true, result: "ok", detail: null }, call: makeCall(), capabilities: makeCaps() }),
      "POST /api/v1/calls/call_1/end": () => ({ action: { id: "a2", call_id: "call_1", action: "end", created_at: "2026-11-17T10:00:00Z", simulated: true, result: "ok", detail: null }, call: makeCall(), capabilities: makeCaps() }),
      "POST /api/v1/calls/call_1/block": () => json({ id: "b1", number_display: "+91 98••• ••21", reason: null, created_at: "2026-11-17T10:00:00Z", source_call_id: "call_1" }),
      ...extra,
    });
    const onActed = vi.fn();
    const view = renderWithApp(<OwnerControls callId="call_1" status="active" capabilities={makeCaps(overrides)} needsDecision onActed={onActed} />, { api });
    return { onActed, ...view };
  }

  it("enables the controls the provider supports and labels the simulation honestly", () => {
    setup();
    expect(screen.getByTestId("action-takeover")).toBeEnabled();
    expect(screen.getByTestId("action-continue")).toBeEnabled();
    expect(screen.getByTestId("action-end")).toBeEnabled();
    expect(screen.getByTestId("takeover-note")).toHaveTextContent("Takeover is simulated: no real phone call is being bridged.");
    expect(screen.getByTestId("audio-note")).toHaveTextContent("no cellular audio");
  });

  it("disables unsupported controls and shows the provider's reason", () => {
    setup({ can_take_over: false, can_continue: false, can_end: false, simulated: false, two_way_audio: false, takeover_note: "Native phone screening cannot bridge or answer a call.", audio_note: null });
    expect(screen.getByTestId("action-takeover")).toBeDisabled();
    expect(screen.getByTestId("action-continue")).toBeDisabled();
    expect(screen.getByTestId("action-end")).toBeDisabled();
    expect(screen.getByTestId("takeover-unavailable")).toHaveTextContent("Native phone screening cannot bridge or answer a call.");
    expect(screen.getByTestId("action-block")).toBeEnabled();
  });

  it("turns every control off once the call has ended, keeping Block available", () => {
    renderWithApp(<OwnerControls callId="call_1" status="ended" capabilities={makeCaps()} />);
    expect(screen.getByTestId("action-takeover")).toBeDisabled();
    expect(screen.getByTestId("action-end")).toBeDisabled();
    expect(screen.getByTestId("action-block")).toBeEnabled();
    expect(screen.getByText(/These controls are off because the call has ended/)).toBeInTheDocument();
  });

  it("calls the takeover endpoint with an idempotency key and reports the simulation", async () => {
    const { api, onActed } = setup();
    await userEvent.click(screen.getByTestId("action-takeover"));
    await waitFor(() => expect(onActed).toHaveBeenCalled());
    const [request] = api.callsTo("POST /api/v1/calls/call_1/takeover");
    expect(request?.headers.get("Idempotency-Key")).toMatch(/^[\w-]{8,}/);
    expect(await screen.findByText("Takeover simulated: no real phone call was bridged to you.")).toBeInTheDocument();
  });

  it("never pretends success on 409 unsupported_by_provider: it shows the server's message", async () => {
    const { onActed } = setup({}, { "POST /api/v1/calls/call_1/takeover": () => apiError(409, "unsupported_by_provider", "This provider cannot bridge the call to you.") });
    await userEvent.click(screen.getByTestId("action-takeover"));
    const note = await screen.findByTestId("unsupported-note");
    expect(note).toHaveTextContent("Not done.");
    expect(note).toHaveTextContent("This provider cannot bridge the call to you.");
    expect(onActed).not.toHaveBeenCalled();
    expect(screen.queryByText(/Takeover simulated/)).toBeNull();
  });

  it("asks before ending a call", async () => {
    const { api } = setup();
    await userEvent.click(screen.getByTestId("action-end"));
    const dialog = await findOpenDialog();
    expect(within(dialog).getByText("End this call?")).toBeInTheDocument();
    expect(api.callsTo("POST /api/v1/calls/call_1/end")).toHaveLength(0);
    await userEvent.click(within(dialog).getByRole("button", { name: "End call" }));
    await waitFor(() => expect(api.callsTo("POST /api/v1/calls/call_1/end")).toHaveLength(1));
  });

  it("blocks a caller with an optional reason", async () => {
    const { api } = setup();
    await userEvent.click(screen.getByTestId("action-block"));
    const dialog = await findOpenDialog();
    fireEvent.change(within(dialog).getByLabelText("Reason (optional)"), { target: { value: "robocall" } });
    await userEvent.click(within(dialog).getByRole("button", { name: "Block caller" }));
    await waitFor(() => expect(api.callsTo("POST /api/v1/calls/call_1/block")).toHaveLength(1));
    expect(api.callsTo("POST /api/v1/calls/call_1/block")[0]?.body).toEqual({ reason: "robocall" });
  });
});
