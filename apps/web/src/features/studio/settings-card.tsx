import { useId, type ReactNode } from "react";
import { Card } from "@/components/ui/layout";

/** A titled settings block. The heading id labels the region for screen readers and anchors the in-page links. */
export function SettingsCard({
  id,
  title,
  description,
  children,
  badge,
}: {
  id: string;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  badge?: ReactNode;
}) {
  const headingId = useId();
  return (
    <Card id={id} aria-labelledby={headingId} className="scroll-mt-24 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={headingId} className="text-lg font-semibold tracking-tight text-fg">
            {title}
          </h2>
          {description ? <p className="mt-1 max-w-2xl text-pretty text-sm text-muted">{description}</p> : null}
        </div>
        {badge}
      </div>
      {children}
    </Card>
  );
}
