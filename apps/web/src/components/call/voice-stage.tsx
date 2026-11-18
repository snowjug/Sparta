"use client";

import { useEffect, useMemo, useRef } from "react";
import type { RiskLevel } from "@/lib/api/enums";
import { cn } from "@/lib/cn";
import { drawStage, readPalette } from "@/lib/stage-canvas";
import { useReducedMotion, useTheme } from "@/lib/theme";
import type { AssistantSpeech, InterruptInfo, PartialInfo } from "@/lib/live/reducer";
import {
  buildSpeechEnvelope,
  computeStageFrame,
  MODE_PRESENTATION,
  type StageFrame,
  type VoiceMode,
} from "@/lib/voice-activity";
import { LogoMark } from "@/components/brand/logo";
import { Icon, type IconName } from "@/components/ui/icon";

const BARS = 56;

export interface VoiceStageProps {
  mode: VoiceMode;
  riskLevel: RiskLevel;
  assistant: AssistantSpeech | null;
  partial: PartialInfo | null;
  interrupted: InterruptInfo | null;
  /** Live microphone spectrum (Simulator Lab, real Web Audio AnalyserNode). Read every frame; null when the mic is off. */
  readMicLevels?: () => ArrayLike<number> | null;
  className?: string;
}

const STATIC_LEVEL: Partial<Record<VoiceMode, number>> = {
  assistant_speaking: 0.4,
  caller_speaking: 0.4,
  listening: 0.12,
  thinking: 0.16,
  interrupted: 0.22,
  escalated: 0.1,
};

/** Reduced motion: one still frame whose bar height encodes the state; the label carries the rest. */
export function staticFrame(mode: VoiceMode): StageFrame {
  const level = STATIC_LEVEL[mode] ?? 0.05;
  return { bars: new Array<number>(BARS).fill(level), progress: null, energy: level };
}

const CENTER_ICON: Partial<Record<VoiceMode, IconName>> = {
  escalated: "bell",
  taken_over: "user-check",
  failed: "alert",
};

/**
 * The call's voice visualisation. Everything it draws is a function of real call state:
 *  - assistant speaking: radiating bars shaped by the utterance text and `est_duration_ms`, plus a spoken-progress arc;
 *  - caller speaking: inward bars that swell with each `transcript.partial` (or the real microphone spectrum);
 *  - listening / thinking / escalated: low, slow indicators; interrupted: a cut mark where the assistant stopped.
 * With `prefers-reduced-motion` nothing animates: a still frame plus the text label carry the state.
 */
export function VoiceStage({ mode, riskLevel, assistant, partial, interrupted, readMicLevels, className }: VoiceStageProps) {
  const reduced = useReducedMotion();
  const { resolved } = useTheme();
  const presentation = MODE_PRESENTATION[mode];
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const envelope = useMemo(() => (assistant ? buildSpeechEnvelope(assistant.text, assistant.estDurationMs) : null), [assistant]);

  const latest = useRef({ assistant, envelope, partial, interrupted, readMicLevels });
  useEffect(() => {
    latest.current = { assistant, envelope, partial, interrupted, readMicLevels };
  });

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    let frameId = 0;
    let disposed = false;
    let size = 1;
    let dpr = 1;
    const palette = readPalette(canvas, presentation);

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      size = Math.max(1, Math.round(rect.width));
      dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(size * dpr);
      canvas.height = Math.round(size * dpr);
    };
    const render = () => {
      const current = latest.current;
      const frame = reduced
        ? staticFrame(mode)
        : computeStageFrame({
            mode,
            now: Date.now(),
            bars: BARS,
            assistant: current.assistant,
            envelope: current.envelope,
            partial: current.partial,
            interrupted: current.interrupted,
            micLevels: current.readMicLevels?.() ?? null,
          });
      drawStage(ctx, size, dpr, frame, presentation, palette, {
        showProgress: !reduced,
        interruptFraction: mode === "interrupted" ? current.interrupted?.spokenFraction ?? null : null,
      });
    };
    const tick = () => {
      if (disposed) return;
      render();
      frameId = requestAnimationFrame(tick);
    };
    const start = () => {
      cancelAnimationFrame(frameId);
      if (!reduced && presentation.animated && document.visibilityState !== "hidden") frameId = requestAnimationFrame(tick);
    };

    resize();
    render();
    start();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
      resize();
      render();
    });
    observer?.observe(canvas);
    document.addEventListener("visibilitychange", start);
    return () => {
      disposed = true;
      cancelAnimationFrame(frameId);
      observer?.disconnect();
      document.removeEventListener("visibilitychange", start);
    };
  }, [mode, reduced, resolved, presentation]);

  const centerIcon = CENTER_ICON[mode];
  const showCheck = mode === "ended";
  const cut = mode === "interrupted" && interrupted ? ` · cut off at ${Math.round(interrupted.spokenFraction * 100)}%` : "";

  return (
    <div className={cn("w-full", className)} data-testid="voice-stage" data-mode={mode} data-risk={riskLevel} data-reduced-motion={reduced ? "true" : "false"}>
      <div className="sp-stage relative mx-auto aspect-square w-full max-w-[22rem]" data-mode={mode} data-risk={riskLevel}>
        <span aria-hidden="true" className="sp-stage-risk-ring absolute inset-0 rounded-full border-2" />
        <span
          aria-hidden="true"
          className={cn(
            "sp-stage-halo absolute inset-[4%] rounded-full",
            !reduced && mode === "listening" && "animate-breathe",
            !reduced && mode === "escalated" && "animate-attention",
          )}
        />
        {!reduced && mode === "interrupted" && interrupted ? (
          <span key={interrupted.at} aria-hidden="true" className="sp-stage-flash absolute inset-[10%] animate-flash rounded-full border-2" />
        ) : null}
        <canvas ref={canvasRef} aria-hidden="true" className="sp-stage-canvas absolute inset-0 size-full" />
        <div className="absolute inset-[35%] flex items-center justify-center rounded-full border border-line bg-surface text-fg shadow-card">
          {showCheck ? (
            <svg viewBox="0 0 24 24" width="40%" height="40%" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M5 12.5l4.5 4.5L19 7.5" strokeDasharray="48" className={reduced ? undefined : "animate-draw"} />
            </svg>
          ) : centerIcon ? (
            <Icon name={centerIcon} size={36} className={mode === "failed" ? "text-danger" : mode === "escalated" ? "text-warning" : "text-info"} />
          ) : (
            <LogoMark size={44} />
          )}
        </div>
      </div>
      <p role="status" aria-live="polite" aria-atomic="true" className="mt-4 text-center text-lg font-semibold tracking-tight text-fg" data-testid="voice-stage-label">
        {presentation.label}
        {cut}
      </p>
      <p className="mx-auto mt-1 max-w-sm text-center text-sm text-muted">{presentation.detail}</p>
    </div>
  );
}
