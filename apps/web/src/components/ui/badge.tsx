import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Icon, type IconName } from "./icon";

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-raised text-fg border-line",
  accent: "bg-accent-soft text-accent border-accent/35",
  success: "bg-success-bg text-success border-success/35",
  warning: "bg-warning-bg text-warning border-warning/35",
  danger: "bg-danger-bg text-danger border-danger/35",
  info: "bg-info-bg text-info border-info/35",
};

export function toneClasses(tone: Tone): string {
  return TONES[tone];
}

export interface BadgeProps {
  tone?: Tone;
  icon?: IconName;
  children: ReactNode;
  className?: string;
  title?: string;
  /** Rendered as uppercase eyebrow (used for REAL / SIMULATED provider badges). */
  strong?: boolean;
  "data-testid"?: string;
}

/** Status pill. Colour is never the only signal: pair it with text and, where meaningful, an icon. */
export function Badge({ tone = "neutral", icon, children, className, title, strong, "data-testid": testId }: BadgeProps) {
  return (
    <span
      title={title}
      data-testid={testId}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold leading-5",
        strong && "uppercase tracking-wide",
        TONES[tone],
        className,
      )}
    >
      {icon ? <Icon name={icon} size={14} /> : null}
      {children}
    </span>
  );
}
