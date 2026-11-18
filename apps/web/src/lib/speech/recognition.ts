/**
 * Browser speech recognition (Web Speech API). Feature-detected: Firefox and some embedded browsers have none, and
 * headless test browsers cannot capture a microphone, so every caller must handle `null` / unsupported.
 *
 * Privacy note shown in the UI: Chromium-based browsers send the microphone audio to the browser vendor's speech
 * service to produce text. Sparta's own server only ever receives the recognised text.
 */

interface RecognitionAlternativeLike {
  transcript: string;
  confidence: number;
}
interface RecognitionResultLike {
  isFinal: boolean;
  length: number;
  [index: number]: RecognitionAlternativeLike;
}
interface RecognitionEventLike {
  resultIndex: number;
  results: { length: number; [index: number]: RecognitionResultLike };
}
interface RecognitionErrorLike {
  error: string;
  message?: string;
}
interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: RecognitionErrorLike) => void) | null;
  onresult: ((event: RecognitionEventLike) => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => RecognitionLike;

export function getRecognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function isRecognitionSupported(): boolean {
  return getRecognitionCtor() !== null;
}

export interface RecognizerHandlers {
  onStart?: () => void;
  onInterim: (text: string) => void;
  /** One finished utterance. `confidence` is the engine's 0..1 estimate, or null when it reports none. */
  onFinal: (text: string, confidence: number | null) => void;
  onError: (code: string, message: string) => void;
  onEnd?: () => void;
}

export interface Recognizer {
  start(): void;
  stop(): void;
  abort(): void;
}

const ERROR_MESSAGES: Record<string, string> = {
  "not-allowed": "Microphone permission was denied. Allow the microphone for this site, or type the caller's words instead.",
  "service-not-allowed": "This browser blocked its speech service. Type the caller's words instead.",
  "no-speech": "No speech was detected. Try again, or type the caller's words.",
  "audio-capture": "No microphone was found. Connect one, or type the caller's words.",
  network: "The browser's speech service could not be reached. Check your connection, or type the caller's words.",
  "language-not-supported": "This browser cannot recognise that language. Pick another language, or type the caller's words.",
  aborted: "Listening was stopped.",
};

export function recognitionErrorMessage(code: string): string {
  return ERROR_MESSAGES[code] ?? `Speech recognition stopped (${code}).`;
}

export function createRecognizer(lang: string, handlers: RecognizerHandlers): Recognizer | null {
  const Ctor = getRecognitionCtor();
  if (!Ctor) return null;
  const recognition = new Ctor();
  recognition.lang = lang;
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  recognition.onstart = () => handlers.onStart?.();
  recognition.onend = () => handlers.onEnd?.();
  recognition.onerror = (event) => handlers.onError(event.error, recognitionErrorMessage(event.error));
  recognition.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      if (!result || result.length === 0) continue;
      const best = result[0];
      if (!best) continue;
      if (result.isFinal) {
        const text = best.transcript.trim();
        if (text) handlers.onFinal(text, Number.isFinite(best.confidence) && best.confidence > 0 ? best.confidence : null);
      } else {
        interim += best.transcript;
      }
    }
    if (interim.trim()) handlers.onInterim(interim.trim());
  };
  return {
    start: () => recognition.start(),
    stop: () => recognition.stop(),
    abort: () => recognition.abort(),
  };
}
