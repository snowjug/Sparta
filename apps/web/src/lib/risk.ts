import type { IconName } from "@/components/ui/icon";
import type { Tone } from "@/components/ui/badge";
import type { RiskLevel, SignalSeverity } from "./api/enums";

export interface RiskVisual {
  level: RiskLevel;
  /** Short label used in chips. */
  label: string;
  /** Sentence used by screen readers and meters. */
  description: string;
  tone: Tone;
  icon: IconName;
  /** CSS colour variable for the meter / stage ring. Green is used for low risk only, red for high only. */
  colorVar: string;
  /** 0..1 position of the level on the meter (used when no score is available). */
  rank: number;
}

const VISUALS: Record<RiskLevel, RiskVisual> = {
  unknown: {
    level: "unknown",
    label: "Not enough evidence",
    description: "Sparta does not have enough evidence yet to rate this call.",
    tone: "neutral",
    icon: "shield",
    colorVar: "var(--muted)",
    rank: 0,
  },
  low: {
    level: "low",
    label: "Low risk",
    description: "No scam signals so far. This is not a guarantee.",
    tone: "success",
    icon: "shield-check",
    colorVar: "var(--success)",
    rank: 0.2,
  },
  medium: {
    level: "medium",
    label: "Caution",
    description: "Some warning signs. Sparta is being careful.",
    tone: "warning",
    icon: "alert",
    colorVar: "var(--warning)",
    rank: 0.55,
  },
  high: {
    level: "high",
    label: "High risk",
    description: "Strong scam signals. Sparta refuses to share anything.",
    tone: "danger",
    icon: "ban",
    colorVar: "var(--danger)",
    rank: 0.9,
  },
};

export function riskVisual(level: RiskLevel | string | null | undefined): RiskVisual {
  return VISUALS[(level as RiskLevel) in VISUALS ? (level as RiskLevel) : "unknown"];
}

/** Meter fill 0..1. `unknown` never fills the meter: Sparta does not show certainty it does not have. */
export function riskMeterFill(level: RiskLevel | string | null | undefined, score: number | null | undefined): number {
  const visual = riskVisual(level);
  if (visual.level === "unknown") return 0;
  if (typeof score === "number" && Number.isFinite(score)) return Math.min(1, Math.max(0.04, score));
  return visual.rank;
}

const SEVERITY_TONES: Record<SignalSeverity, Tone> = {
  info: "neutral",
  low: "info",
  medium: "warning",
  high: "danger",
  critical: "danger",
};

export function severityTone(severity: SignalSeverity | string, kind: "risk" | "legitimate" = "risk"): Tone {
  if (kind === "legitimate") return "success";
  return SEVERITY_TONES[severity as SignalSeverity] ?? "neutral";
}
