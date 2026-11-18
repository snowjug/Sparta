"use client";

import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";
import { Icon } from "./icon";

export interface FieldControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: true;
  "aria-required"?: true;
}

/** Label + hint + error wiring. The control is supplied as a render prop so ids and ARIA stay correct. */
export function Field({
  label,
  hint,
  error,
  required,
  children,
  className,
  labelHidden,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  children: (props: FieldControlProps) => ReactNode;
  className?: string;
  labelHidden?: boolean;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("space-y-1.5", className)}>
      <label htmlFor={id} className={cn("block text-sm font-medium text-fg", labelHidden && "sr-only")}>
        {label}
        {required ? <span className="ml-0.5 text-accent" aria-hidden="true">*</span> : null}
      </label>
      {children({
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
        "aria-required": required ? true : undefined,
      })}
      {hint ? (
        <p id={hintId} className="text-sm text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="flex items-start gap-1.5 text-sm font-medium text-danger">
          <Icon name="alert" size={16} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}

const CONTROL =
  "min-h-11 w-full rounded-xl border border-line-strong bg-sunken px-3.5 text-base text-fg placeholder:text-muted " +
  "transition-colors hover:border-fg/40 disabled:cursor-not-allowed disabled:opacity-60 aria-[invalid=true]:border-danger";

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(CONTROL, className)} {...rest} />;
}

export function TextArea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(CONTROL, "min-h-24 py-2.5 leading-relaxed", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select className={cn(CONTROL, "appearance-none pr-10", className)} {...rest}>
        {children}
      </select>
      <Icon name="chevron-down" size={18} className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-muted" />
    </div>
  );
}

/** Native checkbox exposed as role="switch": on/off is conveyed by position and by the announced state. */
export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
  className,
  ...rest
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
  className?: string;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "checked" | "type" | "role">) {
  const descId = useId();
  return (
    <label className={cn("flex min-h-11 cursor-pointer items-start justify-between gap-4 py-2 has-[:disabled]:cursor-not-allowed", className)}>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-fg">{label}</span>
        {description ? (
          <span id={descId} className="mt-0.5 block text-sm text-muted">
            {description}
          </span>
        ) : null}
      </span>
      <span className="relative mt-0.5 inline-flex shrink-0">
        <input
          type="checkbox"
          role="switch"
          className="peer sr-only"
          checked={checked}
          disabled={disabled}
          aria-describedby={description ? descId : undefined}
          onChange={(event) => onChange(event.target.checked)}
          {...rest}
        />
        <span
          aria-hidden="true"
          className={cn(
            "h-7 w-12 rounded-full border border-line-strong bg-sunken transition-colors duration-200",
            "peer-checked:border-accent peer-checked:bg-accent peer-disabled:opacity-50",
            "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus",
          )}
        />
        <span
          aria-hidden="true"
          className="absolute left-1 top-1 size-5 rounded-full bg-muted transition-transform duration-200 peer-checked:translate-x-5 peer-checked:bg-accent-ink peer-disabled:opacity-50"
        />
      </span>
    </label>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  description?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2 has-[:disabled]:cursor-not-allowed has-[:disabled]:opacity-60">
      <input
        type="checkbox"
        className="mt-0.5 size-5 shrink-0 accent-accent"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="min-w-0">
        <span className="block text-sm font-medium text-fg">{label}</span>
        {description ? <span className="mt-0.5 block text-sm text-muted">{description}</span> : null}
      </span>
    </label>
  );
}

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  description?: string;
  disabled?: boolean;
}

/** Radio group styled as a segmented control. Native radios give arrow-key navigation and correct semantics. */
export function SegmentedControl<T extends string>({
  legend,
  value,
  onChange,
  options,
  name,
  legendHidden,
  stacked,
}: {
  legend: ReactNode;
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  name?: string;
  legendHidden?: boolean;
  stacked?: boolean;
}) {
  const generated = useId();
  const group = name ?? generated;
  return (
    <fieldset className="min-w-0">
      <legend className={cn("mb-1.5 text-sm font-medium text-fg", legendHidden && "sr-only")}>{legend}</legend>
      <div className={cn("grid gap-2", stacked ? "grid-cols-1" : "grid-flow-col auto-cols-fr")}>
        {options.map((option) => (
          <label key={option.value} className="relative block min-w-0 cursor-pointer has-[:disabled]:cursor-not-allowed">
            <input
              type="radio"
              name={group}
              value={option.value}
              checked={value === option.value}
              disabled={option.disabled}
              onChange={() => onChange(option.value)}
              className="peer sr-only"
            />
            <span
              className={cn(
                "flex min-h-11 flex-col justify-center rounded-2xl border border-line-strong bg-surface px-3.5 py-2 text-sm font-medium text-fg",
                "transition-colors hover:bg-raised peer-checked:border-accent peer-checked:bg-accent-soft",
                "peer-checked:[&_.sp-seg-check]:opacity-100 peer-disabled:opacity-50",
                "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus",
              )}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="min-w-0">{option.label}</span>
                <Icon name="check" size={16} className="sp-seg-check shrink-0 text-accent opacity-0" />
              </span>
              {option.description ? <span className="mt-0.5 text-sm font-normal text-muted">{option.description}</span> : null}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function RangeField({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format,
  hint,
}: {
  label: ReactNode;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  format?: (value: number) => string;
  hint?: ReactNode;
}) {
  const id = useId();
  const text = format ? format(value) : String(value);
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium text-fg">
          {label}
        </label>
        <output htmlFor={id} className="text-sm font-semibold tabular-nums text-fg">
          {text}
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-valuetext={text}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-11 w-full cursor-pointer accent-accent"
      />
      {hint ? <p className="text-sm text-muted">{hint}</p> : null}
    </div>
  );
}
