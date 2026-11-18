"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { newIdempotencyKey } from "@/lib/api/client";
import { describeError, isApiError } from "@/lib/api/errors";
import { useApi } from "@/lib/api/provider";
import type { InterruptResult, TurnResult } from "@/lib/api/types";
import { formatBytes } from "@/lib/format";
import { recognitionLocale } from "@/lib/language";
import type { AssistantSpeech } from "@/lib/live/reducer";
import { Button } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/form";
import { Icon } from "@/components/ui/icon";
import { useToast } from "@/components/ui/toast";
import { useMicrophone } from "./use-microphone";

const AUDIO_TYPES = ["audio/wav", "audio/x-wav", "audio/ogg", "audio/webm"];

export interface CallerInputProps {
  callId: string;
  /** "auto" or a BCP-47 code, from the language selector. */
  language: string;
  active: boolean;
  speaking: AssistantSpeech | null;
  maxAudioBytes: number;
  onTurnResult: (result: TurnResult) => void;
  /** Real microphone spectrum for the voice stage (null while the mic is off). */
  onLevelsReader: (read: (() => ArrayLike<number> | null) | null) => void;
}

function languageHint(language: string): string | undefined {
  return language === "auto" ? undefined : language;
}

export function CallerInput({ callId, language, active, speaking, maxAudioBytes, onTurnResult, onLevelsReader }: CallerInputProps) {
  const api = useApi();
  const toast = useToast();
  const [text, setText] = useState("");
  const [ended, setEnded] = useState<string | null>(null);

  const sendTurn = useMutation({
    mutationFn: (input: { text: string; source: "typed" | "browser_stt"; confidence?: number | null }) =>
      api.calls.sendTurn(
        callId,
        {
          text: input.text,
          source: input.source,
          language_hint: languageHint(language),
          stt_confidence: input.confidence ?? undefined,
          client_turn_id: newIdempotencyKey().slice(0, 36),
        },
        { idempotencyKey: newIdempotencyKey() },
      ),
    onSuccess: (result) => {
      setEnded(null);
      onTurnResult(result);
    },
    onError: (error) => {
      if (isApiError(error) && error.kind === "conflict") setEnded(error.message);
    },
  });

  // Interim text is a live preview only (POST /partial emits transcript.partial, no pipeline run): at most 4 per second.
  const lastPartial = useRef(0);
  const sendPartial = (interim: string) => {
    const now = Date.now();
    if (now - lastPartial.current < 250) return;
    lastPartial.current = now;
    api.calls.sendPartial(callId, { text: interim.slice(0, 1000), language_hint: languageHint(language) }).catch(() => {
      /* partials are best-effort: a rate limit or a closed call must not interrupt speaking */
    });
  };

  const mic = useMicrophone({
    lang: recognitionLocale(language),
    onInterim: sendPartial,
    onFinal: (finalText, confidence) => sendTurn.mutate({ text: finalText, source: "browser_stt", confidence }),
  });

  useEffect(() => {
    onLevelsReader(mic.status === "listening" ? mic.readLevels : null);
  }, [mic.status, mic.readLevels, onLevelsReader]);

  // Stop listening as soon as the call is over.
  const { stop } = mic;
  useEffect(() => {
    if (!active) stop();
  }, [active, stop]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    sendTurn.mutate({ text: value, source: "typed" }, { onSuccess: () => setText("") });
  }

  const interrupt = useMutation({
    mutationFn: (): Promise<InterruptResult> => {
      const fraction = speaking && speaking.estDurationMs > 0 ? Math.min(1, Math.max(0, (Date.now() - speaking.startedAt) / speaking.estDurationMs)) : undefined;
      return api.calls.interrupt(callId, { turn_id: speaking?.turnId, spoken_fraction: fraction });
    },
    onSuccess: (result) =>
      toast.info(
        result.interrupted ? `The assistant stopped${result.spoken_fraction !== null ? ` after ${Math.round(result.spoken_fraction * 100)}% of its sentence` : ""}.` : "The assistant was not speaking, so there was nothing to interrupt.",
        { title: result.interrupted ? "Barge-in" : "No barge-in" },
      ),
  });

  const silence = useMutation({
    mutationFn: () => api.calls.silence(callId),
    onSuccess: onTurnResult,
  });

  return (
    <div className="space-y-6" data-testid="caller-input">
      {ended ? (
        <p role="alert" className="rounded-2xl border border-warning/40 bg-warning-bg px-4 py-3 text-sm text-fg" data-testid="call-ending-note">
          {ended} Start a new call to keep experimenting.
        </p>
      ) : null}

      <form onSubmit={submit} className="space-y-3" aria-label="Type what the caller says">
        <Field label="Type what the caller says" hint="Sent as a typed caller turn. If the assistant is still speaking, this counts as barge-in.">
          {(props) => (
            <div className="flex gap-2">
              <TextInput {...props} value={text} onChange={(event) => setText(event.target.value)} disabled={!active} maxLength={1000} placeholder="Hello, I'm calling from your bank…" autoComplete="off" data-testid="caller-text" />
              <Button type="submit" variant="primary" icon="send" disabled={!active || text.trim().length === 0} loading={sendTurn.isPending} data-testid="send-turn">
                Send
              </Button>
            </div>
          )}
        </Field>
      </form>

      <section aria-label="Microphone" className="space-y-2 rounded-2xl border border-line bg-raised p-4" data-testid="mic-panel">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-fg">
          <Icon name={mic.status === "listening" ? "mic" : "mic-off"} size={18} />
          Speak as the caller (browser microphone)
        </h3>
        {mic.supported ? (
          <>
            <p className="text-sm text-muted">
              Uses your browser&apos;s speech recognition in the selected language. Words appear live as you speak; each finished sentence is sent as a caller turn.{" "}
              <strong className="font-semibold text-fg">Chrome and Edge send microphone audio to their own speech service</strong> to recognise it: Sparta&apos;s server only ever receives the text.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              {mic.status === "listening" || mic.status === "starting" ? (
                <Button variant="danger" icon="stop" onClick={mic.stop} data-testid="mic-stop">
                  Stop microphone
                </Button>
              ) : (
                <Button variant="secondary" icon="mic" disabled={!active} onClick={() => void mic.start()} data-testid="mic-start">
                  Start microphone
                </Button>
              )}
              <span className="text-sm text-muted" role="status" data-testid="mic-status">
                {mic.status === "listening" ? "Listening…" : mic.status === "starting" ? "Opening the microphone…" : mic.status === "error" ? "Stopped" : "Microphone is off"}
              </span>
            </div>
            {mic.error ? (
              <p role="alert" className="text-sm font-medium text-danger" data-testid="mic-error">
                {mic.error}
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-sm text-fg" data-testid="mic-unsupported">
            <strong className="font-semibold">This browser has no speech recognition (Web Speech API).</strong> Type the caller&apos;s words above, or upload an audio clip with a transcript below. Chrome and Edge support the microphone option.
          </p>
        )}
      </section>

      <AudioUpload callId={callId} language={language} active={active} maxAudioBytes={maxAudioBytes} onTurnResult={onTurnResult} />

      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Button
            variant="secondary"
            icon="bolt"
            fullWidth
            disabled={!active || !speaking}
            loading={interrupt.isPending}
            onClick={() => interrupt.mutate()}
            aria-describedby="barge-hint"
            data-testid="barge-in"
          >
            Caller interrupts (barge-in)
          </Button>
          <p id="barge-hint" className="text-sm text-muted">
            {speaking ? "The assistant is speaking: interrupt it now." : "Available while the assistant is speaking."}
          </p>
        </div>
        <div className="space-y-1.5">
          <Button variant="secondary" icon="clock" fullWidth disabled={!active} loading={silence.isPending} onClick={() => silence.mutate()} aria-describedby="silence-hint" data-testid="caller-silent">
            Caller stays silent
          </Button>
          <p id="silence-hint" className="text-sm text-muted">
            Fires one silence timeout, like the timer does on a real call.
          </p>
        </div>
      </div>
    </div>
  );
}

function AudioUpload({ callId, language, active, maxAudioBytes, onTurnResult }: Pick<CallerInputProps, "callId" | "language" | "active" | "maxAudioBytes" | "onTurnResult">) {
  const api = useApi();
  const [file, setFile] = useState<File | null>(null);
  const [hint, setHint] = useState("");
  const [problem, setProblem] = useState<{ title: string; message: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const upload = useMutation({
    mutationFn: () =>
      api.calls.sendAudio(callId, file as File, (file as File).name, {
        language_hint: languageHint(language),
        transcript_hint: hint.trim() || undefined,
      }),
    onSuccess: (result) => {
      setProblem(null);
      setFile(null);
      setHint("");
      if (input.current) input.current.value = "";
      onTurnResult(result);
    },
    onError: (error) => {
      const described = describeError(error);
      setProblem({ title: described.title, message: described.message });
    },
    // The explanation is shown inline right here instead of as a toast.
    meta: { silent: true },
  });

  function choose(next: File | null) {
    setProblem(null);
    if (!next) return setFile(null);
    if (!AUDIO_TYPES.includes(next.type)) {
      setFile(null);
      return setProblem({ title: "Unsupported file type", message: "Choose a WAV, Ogg or WebM audio file." });
    }
    if (next.size > maxAudioBytes) {
      setFile(null);
      return setProblem({ title: "File too large", message: `That file is ${formatBytes(next.size)}. The limit is ${formatBytes(maxAudioBytes)}.` });
    }
    setFile(next);
  }

  return (
    <section aria-label="Upload audio" className="space-y-3 rounded-2xl border border-line bg-raised p-4" data-testid="audio-panel">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-fg">
        <Icon name="upload" size={18} />
        Upload a caller audio clip
      </h3>
      <p className="text-sm text-muted">WAV, Ogg or WebM, up to {formatBytes(maxAudioBytes)}. The simulator cannot transcribe audio by itself: add what the clip says as a transcript hint, or configure Azure Speech on the server.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Audio file">
          {(props) => (
            <input
              {...props}
              ref={input}
              type="file"
              accept="audio/wav,audio/x-wav,audio/ogg,audio/webm,.wav,.ogg,.webm"
              disabled={!active}
              onChange={(event) => choose(event.target.files?.[0] ?? null)}
              className="min-h-11 w-full rounded-xl border border-line-strong bg-sunken px-3 py-2 text-sm text-fg file:mr-3 file:rounded-full file:border-0 file:bg-accent file:px-4 file:py-1.5 file:text-sm file:font-semibold file:text-accent-ink"
              data-testid="audio-file"
            />
          )}
        </Field>
        <Field label="Transcript hint (optional)" hint="What the clip says. Without it the simulator answers 422.">
          {(props) => <TextInput {...props} value={hint} onChange={(event) => setHint(event.target.value)} maxLength={1000} disabled={!active} data-testid="transcript-hint" />}
        </Field>
      </div>
      <Button variant="secondary" icon="upload" disabled={!active || !file} loading={upload.isPending} onClick={() => upload.mutate()} data-testid="upload-audio">
        Send audio
      </Button>
      {problem ? (
        <div role="alert" className="rounded-2xl border border-warning/40 bg-warning-bg px-4 py-3 text-sm text-fg" data-testid="audio-problem">
          <p className="font-semibold">{problem.title}</p>
          <p className="mt-0.5">{problem.message}</p>
        </div>
      ) : null}
    </section>
  );
}
