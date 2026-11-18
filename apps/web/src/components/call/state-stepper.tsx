"use client";

import { useRef } from "react";
import type { CallState, CallStatus } from "@/lib/api/enums";
import { describeCallState, STEPPER_STEPS } from "@/lib/call-state";
import { cn } from "@/lib/cn";
import { useCssVar } from "@/lib/use-css-var";
import { Icon } from "@/components/ui/icon";

/** Where the conversation is: connect, introduce, who, why, assess, outcome. State is shown by shape and text, not only colour. */
export function StateStepper({ state, status }: { state: CallState | null; status?: CallStatus }) {
  const model = describeCallState(state, status);
  const labels = [...STEPPER_STEPS.slice(0, 5), model.outcomeLabel];
  const outcomeTone = model.tone === "warning" ? "border-warning bg-warning" : model.tone === "danger" ? "border-danger bg-danger" : model.tone === "info" ? "border-info bg-info" : "border-accent bg-accent";
  const line = useRef<HTMLDivElement>(null);
  const reached = model.finished ? 5 : model.step;
  useCssVar(line, "--fill", reached / 5);

  return (
    <div className="relative" data-testid="state-stepper" data-state={state ?? ""}>
      <div aria-hidden="true" className="absolute inset-x-[8.33%] top-[9px] h-0.5 rounded-full bg-line">
        <div ref={line} className="sp-bar-fill h-full w-full rounded-full" />
      </div>
      <ol aria-label="Call progress" className="relative grid grid-cols-6 gap-1">
        {labels.map((label, index) => {
          const done = index < model.step || (model.finished && index <= model.step);
          const current = index === model.step && !model.finished;
          const last = index === 5;
          return (
            <li key={`${index}-${label}`} aria-current={current ? "step" : undefined} className="flex min-w-0 flex-col items-center gap-1.5 text-center">
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-5 items-center justify-center rounded-full border-2 transition-colors duration-300",
                  done ? (last ? `${outcomeTone} text-accent-ink` : "border-accent bg-accent text-accent-ink") : current ? "border-accent bg-surface" : "border-line-strong bg-surface",
                )}
              >
                {done ? <Icon name="check" size={12} /> : current ? <span className="size-2 rounded-full bg-accent" /> : null}
              </span>
              <span className={cn("text-xs leading-tight", current ? "font-semibold text-fg" : done ? "text-fg" : "text-muted")}>{label}</span>
              <span className="sr-only">{done ? "done" : current ? "current step" : "not reached yet"}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
