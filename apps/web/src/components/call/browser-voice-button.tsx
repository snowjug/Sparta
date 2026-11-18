"use client";

import { useEffect, useRef, useState } from "react";
import { cancelBrowserSpeech, isSpeechSynthesisSupported, speakWithBrowser } from "@/lib/speech/tts";
import { Button } from "@/components/ui/button";

/**
 * "Hear it" button using the BROWSER's voice. Honest label: this is not the production voice, which is chosen above and
 * only produces audio when a real speech provider is connected.
 */
export function BrowserVoiceButton({ text, lang, rate = 1, label = "Hear it in your browser's voice" }: { text: string; lang: string; rate?: number; label?: string }) {
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancel = useRef<(() => void) | null>(null);
  const supported = typeof window !== "undefined" && isSpeechSynthesisSupported();

  useEffect(() => () => cancelBrowserSpeech(), []);

  if (!supported) {
    return <p className="text-sm text-muted">This browser cannot speak text aloud, so there is no browser voice preview.</p>;
  }

  return (
    <div className="space-y-1">
      <Button
        variant="secondary"
        size="sm"
        icon={speaking ? "stop" : "play"}
        onClick={() => {
          if (speaking) {
            cancel.current?.();
            setSpeaking(false);
            return;
          }
          setError(null);
          cancel.current = speakWithBrowser(text, lang, rate, {
            onStart: () => setSpeaking(true),
            onEnd: () => setSpeaking(false),
            onError: (message) => {
              setSpeaking(false);
              setError(message);
            },
          });
          setSpeaking(true);
        }}
      >
        {speaking ? "Stop" : label}
      </Button>
      <p className="text-xs text-muted">This is your browser&apos;s built-in voice, not the production voice Sparta uses on calls.</p>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          The browser could not speak this ({error}).
        </p>
      ) : null}
    </div>
  );
}
