import type { CallState, RiskLevel } from "@/lib/api/enums";
import { describeCallState } from "@/lib/call-state";
import { languageName, variantLabel } from "@/lib/language";
import { riskVisual } from "@/lib/risk";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export function RiskBadge({ level, className }: { level: RiskLevel | string; className?: string }) {
  const visual = riskVisual(level);
  return (
    <Badge tone={visual.tone} icon={visual.icon} className={className} title={visual.description}>
      {visual.label}
    </Badge>
  );
}

export function StateBadge({ state, className }: { state: CallState | null; className?: string }) {
  const model = describeCallState(state);
  return (
    <Badge tone={model.tone} className={className}>
      {model.label}
    </Badge>
  );
}

/** Detected language of a turn, with the Hinglish / Kanglish variant label when the turn mixes languages. */
export function LanguageChip({
  code,
  variant,
  confidence,
  className,
}: {
  code: string | null | undefined;
  variant?: string | null;
  confidence?: number | null;
  className?: string;
}) {
  const name = languageName(code);
  const mix = variantLabel(variant ?? null);
  const title = confidence !== null && confidence !== undefined ? `Detected with ${Math.round(confidence * 100)}% confidence` : undefined;
  return (
    <Badge tone="neutral" icon="language" className={className} title={title}>
      <span lang="en">{name}</span>
      {mix ? <span className="font-medium text-muted"> · {mix}</span> : null}
    </Badge>
  );
}

export function LanguageList({ languages, profile, className }: { languages: string[]; profile?: string | null; className?: string }) {
  if (languages.length === 0 && !profile) return null;
  const mix = variantLabel(profile ?? null);
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-1.5", className)}>
      {languages.map((code) => (
        <LanguageChip key={code} code={code} />
      ))}
      {mix ? (
        <Badge tone="accent" title="Mixed-language speech detected">
          {mix}
        </Badge>
      ) : null}
    </span>
  );
}
