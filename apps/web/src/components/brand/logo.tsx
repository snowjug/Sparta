import { cn } from "@/lib/cn";

/** Original Sparta mark: a shield containing a five-bar voice wave. Inline SVG, no external assets. */
export function LogoMark({ size = 32, className, title }: { size?: number; className?: string; title?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      {title ? <title>{title}</title> : null}
      <path
        d="M16 3.5 25.5 7v8.2c0 5.9-4 10.4-9.5 12.3-5.5-1.9-9.5-6.4-9.5-12.3V7z"
        fill="color-mix(in srgb, var(--accent) 12%, transparent)"
        stroke="var(--accent)"
        strokeWidth={1.7}
        strokeLinejoin="round"
      />
      <g stroke="var(--text)" strokeWidth={1.7} strokeLinecap="round">
        <path d="M11.2 14.4v3.4" />
        <path d="M13.6 12.4v7.4" />
        <path d="M16 10.4v11.4" />
        <path d="M18.4 12.4v7.4" />
        <path d="M20.8 14.4v3.4" />
      </g>
    </svg>
  );
}

export function Brand({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark size={compact ? 28 : 32} />
      <span className="text-lg font-semibold tracking-tight text-fg">Sparta</span>
    </span>
  );
}
