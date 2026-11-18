"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from "react";
import { describeError, type ErrorDescription } from "@/lib/api/errors";
import { cn } from "@/lib/cn";
import { Button, IconButton } from "./button";
import { ErrorDetails } from "./feedback";
import { Icon } from "./icon";

export type ToastTone = "success" | "info" | "error";

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface ToastOptions {
  title?: string;
  action?: ToastAction;
  /** Milliseconds before auto-dismiss. 0 keeps the toast until dismissed. */
  duration?: number;
}

interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  message: string;
  error?: ErrorDescription;
  action?: ToastAction;
  duration: number;
}

type Action = { type: "add"; toast: ToastItem } | { type: "dismiss"; id: number };

function reducer(state: ToastItem[], action: Action): ToastItem[] {
  if (action.type === "add") return [...state, action.toast].slice(-4);
  return state.filter((toast) => toast.id !== action.id);
}

export interface ToastApi {
  success(message: string, options?: ToastOptions): void;
  info(message: string, options?: ToastOptions): void;
  /** Accepts an ApiError / Error / string. Shows the API message and a copyable trace id in "Details". */
  error(error: unknown, options?: ToastOptions): void;
  dismiss(id: number): void;
}

const noop: ToastApi = { success() {}, info() {}, error() {}, dismiss() {} };
const ToastContext = createContext<ToastApi>(noop);

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

const DEFAULT_DURATION: Record<ToastTone, number> = { success: 5000, info: 6000, error: 14000 };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, dispatch] = useReducer(reducer, []);
  const counter = useRef(0);

  const push = useCallback((tone: ToastTone, title: string, message: string, options?: ToastOptions, error?: ErrorDescription) => {
    counter.current += 1;
    dispatch({
      type: "add",
      toast: { id: counter.current, tone, title, message, error, action: options?.action, duration: options?.duration ?? DEFAULT_DURATION[tone] },
    });
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (message, options) => push("success", options?.title ?? "Done", message, options),
      info: (message, options) => push("info", options?.title ?? "Heads up", message, options),
      error: (error, options) => {
        const described = describeError(error);
        push("error", options?.title ?? described.title, described.message, options, described);
      },
      dismiss: (id) => dispatch({ type: "dismiss", id }),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <section
        aria-label="Status messages"
        className="pointer-events-none fixed inset-x-0 top-3 z-[70] flex flex-col items-center gap-2 px-3 sm:inset-x-auto sm:right-4 sm:items-end"
      >
        {toasts.map((toast) => (
          <ToastCard key={toast.id} toast={toast} onDismiss={() => dispatch({ type: "dismiss", id: toast.id })} />
        ))}
      </section>
    </ToastContext.Provider>
  );
}

const TONE_STYLES: Record<ToastTone, { icon: "check" | "info" | "alert"; ring: string; iconClass: string }> = {
  success: { icon: "check", ring: "border-success/45", iconClass: "bg-success-bg text-success" },
  info: { icon: "info", ring: "border-info/45", iconClass: "bg-info-bg text-info" },
  error: { icon: "alert", ring: "border-danger/50", iconClass: "bg-danger-bg text-danger" },
};

function ToastCard({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  const style = TONE_STYLES[toast.tone];
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  const arm = useCallback(() => {
    clear();
    if (toast.duration > 0) timer.current = setTimeout(onDismiss, toast.duration);
  }, [clear, onDismiss, toast.duration]);

  useEffect(() => {
    arm();
    return clear;
  }, [arm, clear]);

  return (
    <div
      // Errors interrupt (assertive); everything else waits its turn (polite).
      role={toast.tone === "error" ? "alert" : "status"}
      onMouseEnter={clear}
      onMouseLeave={arm}
      onFocus={clear}
      onBlur={arm}
      className={cn(
        "pointer-events-auto w-full max-w-md animate-toast-in rounded-2xl border bg-surface p-4 shadow-card",
        style.ring,
      )}
    >
      <div className="flex items-start gap-3">
        <span className={cn("mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full", style.iconClass)}>
          <Icon name={style.icon} size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-fg">{toast.title}</p>
          <p className="mt-0.5 break-words text-sm text-muted">{toast.message}</p>
          {toast.error && (toast.error.traceId || toast.error.details.length > 0 || toast.error.code) ? (
            <details className="mt-1">
              <summary className="inline-flex min-h-11 items-center text-sm font-semibold text-fg underline underline-offset-4">Details</summary>
              <ErrorDetails error={toast.error} />
            </details>
          ) : null}
          {toast.action ? (
            <Button
              variant="secondary"
              size="sm"
              className="mt-2"
              onClick={() => {
                toast.action?.onClick();
                onDismiss();
              }}
            >
              {toast.action.label}
            </Button>
          ) : null}
        </div>
        <IconButton icon="x" label="Dismiss notification" onClick={onDismiss} className="-mr-2 -mt-2" />
      </div>
    </div>
  );
}
