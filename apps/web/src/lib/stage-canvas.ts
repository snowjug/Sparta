import type { ModePresentation, StageFrame } from "./voice-activity";

export interface StagePalette {
  bar: string;
  track: string;
  progress: string;
  warning: string;
}

export function readPalette(element: Element, presentation: ModePresentation): StagePalette {
  const style = getComputedStyle(element);
  const resolve = (value: string, fallback: string) => {
    const match = /^var\((--[\w-]+)\)$/.exec(value);
    const resolved = match ? style.getPropertyValue(match[1]!).trim() : value;
    return resolved || fallback;
  };
  return {
    bar: resolve(presentation.colorVar, "#d6a65c"),
    track: resolve("var(--line)", "#2a2d33"),
    progress: resolve("var(--accent)", "#d6a65c"),
    warning: resolve("var(--warning)", "#f2bb4d"),
  };
}

/** Draws one frame of the radial voice ring. Only reads `frame`, so a static frame is just one call. */
export function drawStage(
  ctx: CanvasRenderingContext2D,
  size: number,
  dpr: number,
  frame: StageFrame,
  presentation: ModePresentation,
  palette: StagePalette,
  options: { showProgress: boolean; interruptFraction: number | null },
): void {
  const center = size / 2;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, size, size);
  ctx.lineCap = "round";

  const innerRadius = center * 0.56;
  const maxLength = center * 0.3;
  const count = frame.bars.length;
  ctx.strokeStyle = palette.bar;
  ctx.lineWidth = Math.max(2, center * 0.024);
  for (let i = 0; i < count; i += 1) {
    const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
    const length = Math.max(1.5, frame.bars[i]! * maxLength);
    const start = presentation.direction === "out" ? innerRadius : innerRadius + maxLength;
    const end = presentation.direction === "out" ? innerRadius + length : innerRadius + maxLength - length;
    ctx.beginPath();
    ctx.moveTo(center + Math.cos(angle) * start, center + Math.sin(angle) * start);
    ctx.lineTo(center + Math.cos(angle) * end, center + Math.sin(angle) * end);
    ctx.stroke();
  }

  // Spoken progress of the assistant's current utterance (from est_duration_ms), or the point where it was cut off.
  const arcRadius = center * 0.94;
  if (options.showProgress && frame.progress !== null) {
    ctx.lineWidth = Math.max(2.5, center * 0.026);
    ctx.strokeStyle = palette.track;
    ctx.beginPath();
    ctx.arc(center, center, arcRadius, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = palette.progress;
    ctx.beginPath();
    ctx.arc(center, center, arcRadius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * frame.progress);
    ctx.stroke();
  }
  if (options.interruptFraction !== null) {
    const angle = -Math.PI / 2 + Math.PI * 2 * options.interruptFraction;
    ctx.strokeStyle = palette.warning;
    ctx.lineWidth = Math.max(3, center * 0.032);
    ctx.beginPath();
    ctx.moveTo(center + Math.cos(angle) * (arcRadius - center * 0.05), center + Math.sin(angle) * (arcRadius - center * 0.05));
    ctx.lineTo(center + Math.cos(angle) * (arcRadius + center * 0.05), center + Math.sin(angle) * (arcRadius + center * 0.05));
    ctx.stroke();
  }
}
