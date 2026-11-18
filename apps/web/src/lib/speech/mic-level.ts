/**
 * Real microphone level through Web Audio: MediaStream -> AnalyserNode -> frequency bins.
 * The voice stage uses these values directly when the Simulator Lab microphone is on: nothing here is simulated.
 */

export interface MicMeter {
  /** `bars` values 0..1 (spectrum folded to the requested resolution). */
  readLevels(bars: number): number[];
  /** Overall level 0..1. */
  readLevel(): number;
  stop(): void;
}

export function isMicMeterSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof window !== "undefined" &&
    (typeof AudioContext !== "undefined" || "webkitAudioContext" in window)
  );
}

export class MicPermissionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MicPermissionError";
  }
}

export async function startMicMeter(): Promise<MicMeter> {
  if (!isMicMeterSupported()) throw new MicPermissionError("This browser cannot capture the microphone.");
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (cause) {
    const name = cause instanceof DOMException ? cause.name : "";
    throw new MicPermissionError(
      name === "NotAllowedError" || name === "SecurityError"
        ? "Microphone permission was denied. Allow it for this site in your browser settings."
        : name === "NotFoundError"
          ? "No microphone was found."
          : "The microphone could not be opened.",
    );
  }

  const Ctor = (window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext) as typeof AudioContext;
  const context = new Ctor();
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.72;
  source.connect(analyser);
  const bins = new Uint8Array(analyser.frequencyBinCount);

  const normalised = () => {
    analyser.getByteFrequencyData(bins);
    return bins;
  };

  return {
    readLevels(bars: number) {
      const data = normalised();
      // Speech energy sits in the lower half of the spectrum: spread those bins over the requested bar count.
      const usable = Math.floor(data.length * 0.6);
      const out: number[] = [];
      for (let i = 0; i < bars; i += 1) {
        const index = Math.min(usable - 1, Math.floor((i / bars) * usable));
        out.push(Math.pow((data[index] ?? 0) / 255, 0.85));
      }
      return out;
    },
    readLevel() {
      const data = normalised();
      let sum = 0;
      for (const value of data) sum += value;
      return sum / data.length / 255;
    },
    stop() {
      for (const track of stream.getTracks()) track.stop();
      source.disconnect();
      void context.close();
    },
  };
}
