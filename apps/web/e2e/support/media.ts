/** A short, valid mono 16-bit PCM WAV file (silence): enough to pass the server's magic-byte and length checks. */
export function silentWav(durationMs = 200, sampleRate = 8000): Buffer {
  const samples = Math.floor((sampleRate * durationMs) / 1000);
  const data = Buffer.alloc(samples * 2);
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(1, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(sampleRate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(data.length, 40);
  return Buffer.concat([header, data]);
}

/**
 * Replaces the browser's Web Speech recognizer with a scriptable one. Headless browsers have no speech service, so the real
 * engine cannot be exercised here; this verifies how the app drives the standard SpeechRecognition interface (start, interim
 * and final results, errors) and what it sends to the API, not the quality of recognition.
 */
export const FAKE_SPEECH_RECOGNITION = `
  class FakeSpeechRecognition {
    constructor() {
      this.lang = ""; this.continuous = false; this.interimResults = false; this.maxAlternatives = 1;
      this.onstart = null; this.onend = null; this.onerror = null; this.onresult = null;
      window.__recognition = this;
      window.__recognitionLangs = (window.__recognitionLangs || []).concat([""]);
    }
    start() { window.__recognitionLangs[window.__recognitionLangs.length - 1] = this.lang; setTimeout(() => this.onstart && this.onstart(), 0); }
    stop() { setTimeout(() => this.onend && this.onend(), 0); }
    abort() { setTimeout(() => this.onend && this.onend(), 0); }
    emit(transcript, isFinal, confidence) {
      const result = [{ transcript, confidence: confidence === undefined ? 0.92 : confidence }];
      result.isFinal = isFinal;
      this.onresult && this.onresult({ resultIndex: 0, results: [result] });
    }
  }
  window.SpeechRecognition = FakeSpeechRecognition;
  window.webkitSpeechRecognition = FakeSpeechRecognition;
`;

/** Records what the page asks the browser's speech synthesis to say, instead of making sound. */
export const SPY_SPEECH_SYNTHESIS = `
  window.__spoken = [];
  if (window.speechSynthesis) {
    window.speechSynthesis.speak = (utterance) => { window.__spoken.push({ text: utterance.text, lang: utterance.lang }); };
    window.speechSynthesis.cancel = () => { window.__cancelled = (window.__cancelled || 0) + 1; };
  }
`;
