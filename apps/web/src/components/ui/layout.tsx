import { useId, type ElementType, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Icon } from "./icon";

export function Card({
  as: Tag = "section",
  className,
  children,
  ...rest
}: {
  as?: ElementType;
  className?: string;
  children: ReactNode;
} & Record<string, unknown>) {
  return (
    <Tag className={cn("rounded-3xl border border-line bg-surface p-5 shadow-card sm:p-6", className)} {...rest}>
      {children}
    </Tag>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  eyebrow?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-x-6 gap-y-4">
      <div className="min-w-0 max-w-2xl">
        {eyebrow ? <p className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-accent">{eyebrow}</p> : null}
        <h1 className="text-balance text-2xl font-semibold tracking-tight text-fg sm:text-3xl">{title}</h1>
        {description ? <p className="mt-1.5 text-pretty text-base text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function Section({
  title,
  description,
  actions,
  children,
  className,
  headingLevel = 2,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  headingLevel?: 2 | 3;
}) {
  const id = useId();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  return (
    <section aria-labelledby={id} className={cn("space-y-4", className)}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <Heading id={id} className="text-lg font-semibold tracking-tight text-fg">
            {title}
          </Heading>
          {description ? <p className="mt-0.5 text-sm text-muted">{description}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Native <details>: keyboard and screen-reader support for free, styled to match. */
export function Disclosure({
  summary,
  children,
  defaultOpen,
  className,
  summaryClassName,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
  summaryClassName?: string;
}) {
  return (
    <details open={defaultOpen} className={cn("group rounded-2xl border border-line bg-surface", className)}>
      <summary
        className={cn(
          "flex min-h-11 list-none items-center justify-between gap-3 rounded-2xl px-4 py-2 text-sm font-semibold text-fg",
          "[&::-webkit-details-marker]:hidden",
          summaryClassName,
        )}
      >
        <span className="min-w-0">{summary}</span>
        <Icon name="chevron-down" size={18} className="shrink-0 text-muted transition-transform duration-200 group-open:rotate-180" />
      </summary>
      <div className="border-t border-line px-4 py-4">{children}</div>
    </details>
  );
}

export function Divider({ className }: { className?: string }) {
  return <hr className={cn("border-0 border-t border-line", className)} />;
}

/** Key/value row used in diagnostics and detail panels (tabular numerals for metrics). */
export function DefinitionRow({ label, children, mono }: { label: ReactNode; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className={cn("min-w-0 text-right text-fg tabular-nums", mono && "font-mono text-xs")}>{children}</dd>
    </div>
  );
}
