"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createRecognizer, isRecognitionSupported, type Recognizer } from "@/lib/speech/recognition";
import { isMicMeterSupported, MicPermissionError, startMicMeter, type MicMeter } from "@/lib/speech/mic-level";

export type MicStatus = "idle" | "starting" | "listening" | "error";

export interface UseMicrophoneOptions {
  /** BCP-47 locale for recognition (from the language selector). */
  lang: string;
  onInterim: (text: string) => void;
  onFinal: (text: string, confidence: number | null) => void;
}

/**
 * Browser microphone for the Simulator Lab: Web Speech recognition (interim + final text) together with a real
 * Web Audio analyser whose spectrum drives the voice stage. Both are feature-detected; callers show a fallback
 * message when `supported` is false.
 */
export function useMicrophone({ lang, onInterim, onFinal }: UseMicrophoneOptions) {
  const [status, setStatus] = useState<MicStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [supported] = useState(() => isRecognitionSupported());
  const [meterSupported] = useState(() => isMicMeterSupported());
  const meter = useRef<MicMeter | null>(null);
  const recognizer = useRef<Recognizer | null>(null);
  const wanted = useRef(false);
  const handlers = useRef({ onInterim, onFinal, lang });
  useEffect(() => {
    handlers.current = { onInterim, onFinal, lang };
  });

  const stop = useCallback(() => {
    wanted.current = false;
    recognizer.current?.abort();
    recognizer.current = null;
    meter.current?.stop();
    meter.current = null;
    setStatus("idle");
  }, []);

  const start = useCallback(async () => {
    if (wanted.current) return;
    setError(null);
    setStatus("starting");
    wanted.current = true;
    try {
      if (meterSupported) meter.current = await startMicMeter();
    } catch (cause) {
      wanted.current = false;
      setError(cause instanceof MicPermissionError ? cause.message : "The microphone could not be opened.");
      setStatus("error");
      return;
    }
    if (!wanted.current) {
      meter.current?.stop();
      meter.current = null;
      return;
    }
    const launch = () => {
      const instance = createRecognizer(handlers.current.lang, {
        onStart: () => setStatus("listening"),
        onInterim: (text) => handlers.current.onInterim(text),
        onFinal: (text, confidence) => handlers.current.onFinal(text, confidence),
        onError: (code, message) => {
          if (code === "no-speech" || code === "aborted") return;
          wanted.current = false;
          setError(message);
          setStatus("error");
          meter.current?.stop();
          meter.current = null;
        },
        onEnd: () => {
          // Continuous recognition ends on its own after a while: restart while the owner still wants it on.
          if (wanted.current) setTimeout(() => wanted.current && recognizer.current?.start(), 250);
        },
      });
      recognizer.current = instance;
      instance?.start();
    };
    launch();
    setStatus("listening");
  }, [meterSupported]);

  useEffect(() => () => stop(), [stop]);

  const readLevels = useCallback((): ArrayLike<number> | null => (meter.current ? meter.current.readLevels(32) : null), []);

  return { status, error, supported, meterSupported, start, stop, readLevels };
}
