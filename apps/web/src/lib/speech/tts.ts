/**
 * Browser text-to-speech (Web Speech API `speechSynthesis`). This is the BROWSER's own voice: it is never the
 * production voice Sparta uses on a call, and the UI labels it that way wherever it is offered.
 */

export function isSpeechSynthesisSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";
}

export function pickVoice(voices: ReadonlyArray<SpeechSynthesisVoice>, lang: string): SpeechSynthesisVoice | null {
  const wanted = lang.toLowerCase();
  const base = wanted.split("-")[0];
  return (
    voices.find((voice) => voice.lang.toLowerCase() === wanted) ??
    voices.find((voice) => voice.lang.toLowerCase().split("-")[0] === base) ??
    null
  );
}

export interface SpeakHandlers {
  onStart?: () => void;
  onEnd?: () => void;
  onError?: (message: string) => void;
  /** Real word boundary events from the browser engine (not every voice emits them). */
  onBoundary?: (charIndex: number) => void;
}

/** Speaks `text`. Returns a function that cancels this utterance. */
export function speakWithBrowser(text: string, lang: string, rate: number, handlers: SpeakHandlers = {}): () => void {
  if (!isSpeechSynthesisSupported()) {
    handlers.onError?.("This browser has no speech synthesis.");
    return () => {};
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  utterance.rate = Math.min(2, Math.max(0.5, rate));
  const voice = pickVoice(window.speechSynthesis.getVoices(), lang);
  if (voice) utterance.voice = voice;
  utterance.onstart = () => handlers.onStart?.();
  utterance.onend = () => handlers.onEnd?.();
  utterance.onerror = (event) => {
    // "canceled" / "interrupted" are how a deliberate cancel() is reported, not failures.
    if (event.error !== "canceled" && event.error !== "interrupted") handlers.onError?.(event.error);
    else handlers.onEnd?.();
  };
  utterance.onboundary = (event) => handlers.onBoundary?.(event.charIndex);
  window.speechSynthesis.speak(utterance);
  return () => {
    utterance.onend = null;
    utterance.onerror = null;
    window.speechSynthesis.cancel();
  };
}

export function cancelBrowserSpeech(): void {
  if (isSpeechSynthesisSupported()) window.speechSynthesis.cancel();
}
