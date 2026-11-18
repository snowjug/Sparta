import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CallerInput } from "./caller-input";
import { renderWithApp } from "@/test/render";
import { apiError, createFakeApi } from "@/test/fake-fetch";
import { makeCall, makeRisk, makeTurn } from "@/test/fixtures";
import { makeAssistantRoutes } from "@/test/routes";

const turnResult = (text = "Hello") => ({
  caller_turn: makeTurn({ seq: 2, text }),
  assistant_turn: makeTurn({ seq: 3, speaker: "assistant", source: "assistant", text: "Who is calling?" }),
  call: makeCall(),
  risk: makeRisk(),
  state: "IDENTIFY_PURPOSE",
  ended: false,
  escalation: null,
});

function setup(overrides: Partial<Parameters<typeof CallerInput>[0]> = {}, routes: Record<string, () => unknown> = {}) {
  const api = createFakeApi({
    ...makeAssistantRoutes(),
    "POST /api/v1/calls/call_1/turns": () => turnResult(),
    "POST /api/v1/calls/call_1/partial": () => undefined,
    "POST /api/v1/calls/call_1/interrupt": () => ({ interrupted: true, turn_id: "turn_1", interruption_ms: 120, spoken_fraction: 0.5 }),
    "POST /api/v1/calls/call_1/silence": () => turnResult("(silence)"),
    ...routes,
  });
  const onTurnResult = vi.fn();
  const view = renderWithApp(<CallerInput callId="call_1" language="auto" active speaking={null} maxAudioBytes={8_000_000} onTurnResult={onTurnResult} onLevelsReader={() => {}} {...overrides} />, { api });
  return { onTurnResult, ...view };
}

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).SpeechRecognition;
  delete (window as unknown as Record<string, unknown>).webkitSpeechRecognition;
});

describe("CallerInput: typed turns", () => {
  it("sends a typed caller turn with an idempotency key and hands the result to the call model", async () => {
    const { api, onTurnResult } = setup({ language: "hi-IN" });
    await userEvent.type(screen.getByTestId("caller-text"), "Main bank se bol raha hoon");
    await userEvent.click(screen.getByTestId("send-turn"));
    await waitFor(() => expect(onTurnResult).toHaveBeenCalled());
    const [request] = api.callsTo("POST /api/v1/calls/call_1/turns");
    expect(request?.body).toMatchObject({ text: "Main bank se bol raha hoon", source: "typed", language_hint: "hi-IN" });
    expect(request?.headers.get("Idempotency-Key")).toBeTruthy();
    expect(screen.getByTestId("caller-text")).toHaveValue("");
  });

  it("omits the language hint in auto mode and disables inputs once the call is over", async () => {
    const { api } = setup();
    await userEvent.type(screen.getByTestId("caller-text"), "Hello");
    await userEvent.click(screen.getByTestId("send-turn"));
    await waitFor(() => expect(api.callsTo("POST /api/v1/calls/call_1/turns")).toHaveLength(1));
    expect(api.callsTo("POST /api/v1/calls/call_1/turns")[0]?.body).not.toHaveProperty("language_hint");
  });

  it("tells the owner when the call is already ending instead of failing silently", async () => {
    setup({}, { "POST /api/v1/calls/call_1/turns": () => apiError(409, "conflict", "This call is ending and cannot accept more input.") });
    await userEvent.type(screen.getByTestId("caller-text"), "one more thing");
    await userEvent.click(screen.getByTestId("send-turn"));
    expect(await screen.findByTestId("call-ending-note")).toHaveTextContent("This call is ending and cannot accept more input.");
  });

  it("is disabled when the call is not active", () => {
    setup({ active: false });
    expect(screen.getByTestId("caller-text")).toBeDisabled();
    expect(screen.getByTestId("send-turn")).toBeDisabled();
    expect(screen.getByTestId("caller-silent")).toBeDisabled();
  });
});

describe("CallerInput: barge-in and silence", () => {
  it("offers barge-in only while the assistant is speaking, passing the real spoken fraction", async () => {
    const { unmount } = setup();
    expect(screen.getByTestId("barge-in")).toBeDisabled();
    expect(screen.getByText("Available while the assistant is speaking.")).toBeInTheDocument();
    unmount();

    const speaking = { turnId: "turn_1", text: "Hello", locale: "en-IN", voiceId: null, estDurationMs: 4000, startedAt: Date.now() - 1000 };
    const second = setup({ speaking });
    expect(screen.getByTestId("barge-in")).toBeEnabled();
    await userEvent.click(screen.getByTestId("barge-in"));
    await waitFor(() => expect(second.api.callsTo("POST /api/v1/calls/call_1/interrupt")).toHaveLength(1));
    const body = second.api.callsTo("POST /api/v1/calls/call_1/interrupt")[0]!.body as { turn_id: string; spoken_fraction: number };
    expect(body.turn_id).toBe("turn_1");
    expect(body.spoken_fraction).toBeGreaterThan(0.2);
    expect(body.spoken_fraction).toBeLessThan(0.6);
    expect(await screen.findByText(/The assistant stopped after \d+% of its sentence/)).toBeInTheDocument();
  });

  it("fires a silence timeout", async () => {
    const { api, onTurnResult } = setup();
    await userEvent.click(screen.getByTestId("caller-silent"));
    await waitFor(() => expect(onTurnResult).toHaveBeenCalled());
    expect(api.callsTo("POST /api/v1/calls/call_1/silence")).toHaveLength(1);
  });
});

describe("CallerInput: microphone (Web Speech API)", () => {
  it("says clearly when the browser has no speech recognition, and keeps the other inputs", () => {
    setup();
    const note = screen.getByTestId("mic-unsupported");
    expect(note).toHaveTextContent("This browser has no speech recognition (Web Speech API).");
    expect(note).toHaveTextContent(/Type the caller/);
    expect(screen.queryByTestId("mic-start")).toBeNull();
    expect(screen.getByTestId("caller-text")).toBeEnabled();
  });

  it("starts recognition in the chosen language, previews interim text and sends the final text as browser_stt", async () => {
    class FakeRecognition {
      static last: FakeRecognition | null = null;
      lang = "";
      continuous = false;
      interimResults = false;
      maxAlternatives = 1;
      onstart: (() => void) | null = null;
      onend: (() => void) | null = null;
      onerror: ((e: { error: string }) => void) | null = null;
      onresult: ((e: unknown) => void) | null = null;
      started = false;
      constructor() {
        FakeRecognition.last = this;
      }
      start() {
        this.started = true;
        this.onstart?.();
      }
      stop() {}
      abort() {}
    }
    (window as unknown as Record<string, unknown>).webkitSpeechRecognition = FakeRecognition;
    const { api } = setup({ language: "kn-IN" });
    await userEvent.click(screen.getByTestId("mic-start"));
    await waitFor(() => expect(FakeRecognition.last?.started).toBe(true));
    expect(FakeRecognition.last?.lang).toBe("kn-IN");
    expect(screen.getByTestId("mic-status")).toHaveTextContent("Listening");

    const result = (text: string, isFinal: boolean, confidence = 0.87) => ({ resultIndex: 0, results: { length: 1, 0: { isFinal, length: 1, 0: { transcript: text, confidence } } } });
    FakeRecognition.last!.onresult?.(result("nimma account", false));
    await waitFor(() => expect(api.callsTo("POST /api/v1/calls/call_1/partial")).toHaveLength(1));
    expect(api.callsTo("POST /api/v1/calls/call_1/partial")[0]?.body).toMatchObject({ text: "nimma account", language_hint: "kn-IN" });

    FakeRecognition.last!.onresult?.(result("nimma account block aagutte", true));
    await waitFor(() => expect(api.callsTo("POST /api/v1/calls/call_1/turns")).toHaveLength(1));
    expect(api.callsTo("POST /api/v1/calls/call_1/turns")[0]?.body).toMatchObject({ text: "nimma account block aagutte", source: "browser_stt", stt_confidence: 0.87, language_hint: "kn-IN" });
  });

  it("explains a denied microphone permission", async () => {
    class DeniedRecognition {
      onerror: ((e: { error: string }) => void) | null = null;
      onstart: (() => void) | null = null;
      onend: (() => void) | null = null;
      onresult: (() => void) | null = null;
      start() {
        queueMicrotask(() => this.onerror?.({ error: "not-allowed" }));
      }
      stop() {}
      abort() {}
    }
    (window as unknown as Record<string, unknown>).SpeechRecognition = DeniedRecognition;
    setup();
    await userEvent.click(screen.getByTestId("mic-start"));
    expect(await screen.findByTestId("mic-error")).toHaveTextContent("Microphone permission was denied");
  });
});

describe("CallerInput: audio upload", () => {
  const wav = () => new File([new Uint8Array([0x52, 0x49, 0x46, 0x46, 0, 0, 0, 0, 0x57, 0x41, 0x56, 0x45])], "clip.wav", { type: "audio/wav" });

  it("shows the explanatory 422 stt_unavailable message inline", async () => {
    const { api } = setup({}, { "POST /api/v1/calls/call_1/audio": () => apiError(422, "stt_unavailable", "Speech-to-text is the simulator") });
    await userEvent.upload(screen.getByTestId("audio-file"), wav());
    await userEvent.click(screen.getByTestId("upload-audio"));
    const problem = await screen.findByTestId("audio-problem");
    expect(problem).toHaveTextContent("Speech recognition isn't available here");
    expect(problem).toHaveTextContent(/cannot transcribe audio/i);
    expect(problem).toHaveTextContent(/transcript hint/i);
    expect(api.callsTo("POST /api/v1/calls/call_1/audio")).toHaveLength(1);
  });

  it("sends the transcript hint with the multipart upload and folds the result in", async () => {
    const { api, onTurnResult } = setup({ language: "en-IN" }, { "POST /api/v1/calls/call_1/audio": () => turnResult("please share the otp") });
    await userEvent.upload(screen.getByTestId("audio-file"), wav());
    fireEvent.change(screen.getByTestId("transcript-hint"), { target: { value: "please share the otp" } });
    await userEvent.click(screen.getByTestId("upload-audio"));
    await waitFor(() => expect(onTurnResult).toHaveBeenCalled());
    const [request] = api.callsTo("POST /api/v1/calls/call_1/audio");
    expect(request?.body).toMatchObject({ file: expect.stringContaining("clip.wav"), transcript_hint: "please share the otp", language_hint: "en-IN" });
  });

  it("rejects the wrong type or an oversized file before uploading", async () => {
    const { api } = setup({ maxAudioBytes: 10 });
    fireEvent.change(screen.getByTestId("audio-file"), { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });
    expect(await screen.findByTestId("audio-problem")).toHaveTextContent("Choose a WAV, Ogg or WebM audio file.");
    fireEvent.change(screen.getByTestId("audio-file"), { target: { files: [wav()] } });
    expect(await screen.findByTestId("audio-problem")).toHaveTextContent(/The limit is 10 B/);
    expect(screen.getByTestId("upload-audio")).toBeDisabled();
    expect(api.callsTo("POST /api/v1/calls/call_1/audio")).toHaveLength(0);
  });
});
