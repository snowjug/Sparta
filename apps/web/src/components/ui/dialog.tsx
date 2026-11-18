"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Button, IconButton } from "./button";
import { Field, TextInput } from "./form";
import { Spinner } from "./spinner";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';

function isVisible(element: HTMLElement): boolean {
  const style = getComputedStyle(element);
  return style.display !== "none" && style.visibility !== "hidden";
}

/** Tab and Shift+Tab wrap inside the dialog: the browser's own modal handling lets focus escape to the browser UI. */
function trapTab(event: KeyboardEvent<HTMLDialogElement>, dialog: HTMLDialogElement | null) {
  if (event.key !== "Tab" || !dialog) return;
  const focusable = [...dialog.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(isVisible);
  if (focusable.length === 0) {
    event.preventDefault();
    return;
  }
  const first = focusable[0]!;
  const last = focusable[focusable.length - 1]!;
  const active = document.activeElement;
  if (event.shiftKey && (active === first || !dialog.contains(active))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || !dialog.contains(active))) {
    event.preventDefault();
    first.focus();
  }
}

/**
 * Modal built on the native <dialog> element: the browser makes the page inert, handles Escape and restores focus to the
 * control that opened it; Tab is wrapped here so focus stays inside. Content only exists while open.
 */
export function Dialog({ open, onClose, title, description, children, footer, className }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      dialog.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="sp-dialog"
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onKeyDown={(event) => trapTab(event, ref.current)}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {open ? (
        <div className={cn("flex max-h-[calc(100dvh-2rem)] flex-col", className)}>
          <div className="flex items-start justify-between gap-4 px-6 pt-6">
            <h2 id={titleId} className="text-lg font-semibold tracking-tight text-fg">
              {title}
            </h2>
            <IconButton icon="x" label="Close dialog" onClick={onClose} className="-mr-2 -mt-2" />
          </div>
          <div className="sp-scroll min-h-0 flex-1 overflow-y-auto px-6 py-3">
            {description ? (
              <p id={descriptionId} className="mb-3 text-base text-muted">
                {description}
              </p>
            ) : null}
            {children}
          </div>
          {footer ? <div className="flex flex-wrap justify-end gap-2 px-6 pb-6 pt-3">{footer}</div> : null}
        </div>
      ) : null}
    </dialog>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => Promise<unknown> | unknown;
  title: ReactNode;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  /** Destructive actions can require typing a word before the confirm button enables. */
  requireText?: string;
  children?: ReactNode;
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  requireText,
  children,
}: ConfirmDialogProps) {
  const [pending, setPending] = useState(false);
  const [typed, setTyped] = useState("");
  const matches = !requireText || typed.trim().toLowerCase() === requireText.toLowerCase();

  async function handleConfirm() {
    setPending(true);
    try {
      await onConfirm();
      setTyped("");
      onClose();
    } catch {
      /* the caller surfaces the failure (toast); keep the dialog open so the owner can retry or cancel */
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => {
        if (pending) return;
        setTyped("");
        onClose();
      }}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending} data-autofocus>
            {cancelLabel}
          </Button>
          <Button variant={tone === "danger" ? "danger" : "primary"} onClick={handleConfirm} disabled={!matches} loading={pending}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
      {requireText ? (
        <Field label={`Type “${requireText}” to confirm`}>
          {(props) => (
            <TextInput
              {...props}
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
            />
          )}
        </Field>
      ) : null}
      {pending ? <Spinner label="Working" className="mt-2" /> : null}
    </Dialog>
  );
}
