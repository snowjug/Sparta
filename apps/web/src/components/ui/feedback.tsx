"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { describeError, type ErrorDescription } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { Button } from "./button";
import { Icon, type IconName } from "./icon";

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* fall back to the selection API below */
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

export function CopyButton({
  text,
  label = "Copy",
  copiedLabel = "Copied",
  className,
  ariaLabel,
}: {
  text: string;
  label?: string;
  copiedLabel?: string;
  className?: string;
  ariaLabel?: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), []);

  async function onClick() {
    const ok = await copyText(text);
    setState(ok ? "copied" : "failed");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2200);
  }

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        icon={state === "copied" ? "check" : "copy"}
        onClick={onClick}
        className={className}
        aria-label={ariaLabel}
      >
        {state === "copied" ? copiedLabel : state === "failed" ? "Copy failed" : label}
      </Button>
      <span className="sr-only" role="status">
        {state === "copied" ? "Copied to clipboard" : state === "failed" ? "Could not copy" : ""}
      </span>
    </>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("animate-shimmer rounded-xl bg-raised", className)} />;
}

export function LoadingBlock({ label = "Loading", lines = 3 }: { label?: string; lines?: number }) {
  return (
    <div role="status" aria-busy="true" className="space-y-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} className={cn("h-5", index === 0 ? "w-2/3" : index === lines - 1 ? "w-1/2" : "w-full")} />
      ))}
    </div>
  );
}

export function EmptyState({
  icon = "shield",
  title,
  description,
  action,
  className,
  headingLevel = 3,
}: {
  icon?: IconName;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  /** 1 when it is the whole page (404, error), 2 directly under the page's h1, 3 inside a section: heading levels never skip. */
  headingLevel?: 1 | 2 | 3;
}) {
  const Heading = headingLevel === 1 ? "h1" : headingLevel === 2 ? "h2" : "h3";
  return (
    <div className={cn("flex flex-col items-center gap-3 rounded-3xl border border-dashed border-line-strong px-6 py-10 text-center", className)}>
      <span className="flex size-12 items-center justify-center rounded-full bg-accent-soft text-accent">
        <Icon name={icon} size={24} />
      </span>
      <Heading className="text-lg font-semibold tracking-tight text-fg">{title}</Heading>
      {description ? <p className="max-w-md text-pretty text-base text-muted">{description}</p> : null}
      {action}
    </div>
  );
}

/** Technical details for an API failure. Trace id and codes only: never content or phone numbers. */
export function ErrorDetails({ error }: { error: ErrorDescription }) {
  return (
    <div className="mt-2 space-y-2 rounded-xl bg-sunken p-3 text-sm">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        <dt className="text-muted">Code</dt>
        <dd className="font-mono text-xs text-fg">{error.code}</dd>
        {error.status ? (
          <>
            <dt className="text-muted">Status</dt>
            <dd className="font-mono text-xs text-fg">{error.status}</dd>
          </>
        ) : null}
        {error.traceId ? (
          <>
            <dt className="text-muted">Trace ID</dt>
            <dd className="break-all font-mono text-xs text-fg">{error.traceId}</dd>
          </>
        ) : null}
        {error.requestId && error.requestId !== error.traceId ? (
          <>
            <dt className="text-muted">Request ID</dt>
            <dd className="break-all font-mono text-xs text-fg">{error.requestId}</dd>
          </>
        ) : null}
      </dl>
      {error.details.length > 0 ? (
        <ul className="list-disc space-y-0.5 pl-5 text-fg">
          {error.details.map((detail, index) => (
            <li key={`${detail.field}-${index}`}>
              <span className="font-mono text-xs">{detail.field}</span>: {detail.message}
            </li>
          ))}
        </ul>
      ) : null}
      <CopyButton text={error.diagnostic} label="Copy details" />
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  className?: string;
}) {
  const described = describeError(error);
  return (
    <div role="alert" className={cn("rounded-3xl border border-danger/40 bg-danger-bg p-5", className)}>
      <div className="flex items-start gap-3">
        <Icon name="alert" size={22} className="mt-0.5 shrink-0 text-danger" />
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold text-fg">{title ?? described.title}</h2>
          <p className="mt-1 text-base text-fg">{described.message}</p>
          <details className="mt-2">
            <summary className="inline-flex min-h-11 items-center text-sm font-semibold text-fg underline underline-offset-4">
              Technical details
            </summary>
            <ErrorDetails error={described} />
          </details>
          {onRetry ? (
            <Button variant="secondary" size="sm" icon="refresh" onClick={onRetry} className="mt-2">
              Try again
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
