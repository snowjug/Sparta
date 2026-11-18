"use client";

import { useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import { useMotionPreference, useTheme, type ThemePreference } from "@/lib/theme";
import { Icon, type IconName } from "@/components/ui/icon";
import { Switch } from "@/components/ui/form";

const OPTIONS: Array<{ value: ThemePreference; label: string; icon: IconName }> = [
  { value: "system", label: "System", icon: "monitor" },
  { value: "light", label: "Light", icon: "sun" },
  { value: "dark", label: "Dark", icon: "moon" },
];

/** Display menu: theme (system / light / dark) and a manual reduced-motion override. */
export function DisplayMenu({ className }: { className?: string }) {
  const { preference, resolved, setPreference } = useTheme();
  const { preference: motion, setPreference: setMotion } = useMotionPreference();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const root = useRef<HTMLDivElement>(null);

  // Clicking outside closes the menu. (Focus leaving is not enough: pressing the mouse on a label or on empty panel space moves focus
  // to nothing, and that must not close the menu before the click lands.)
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node | null)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <div
      ref={root}
      className={cn("relative", className)}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          setOpen(false);
          root.current?.querySelector<HTMLButtonElement>("button[aria-controls]")?.focus();
        }
      }}
      onBlur={(event) => {
        // Tabbing away to another control closes the menu; a blur to "nothing" (a mouse press inside the panel) does not.
        const next = event.relatedTarget as Node | null;
        if (open && next && !root.current?.contains(next)) setOpen(false);
      }}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Display settings. Theme: ${preference === "system" ? `system (${resolved})` : preference}`}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex size-11 items-center justify-center rounded-full border border-line-strong bg-surface text-fg transition-colors hover:bg-raised"
      >
        <Icon name={resolved === "dark" ? "moon" : "sun"} size={20} />
      </button>
      {open ? (
        <div
          id={panelId}
          role="group"
          aria-label="Display settings"
          className="absolute right-0 top-12 z-50 w-72 max-w-[calc(100vw-2rem)] animate-fade-up rounded-2xl border border-line bg-surface p-4 shadow-card"
        >
          <fieldset>
            <legend className="mb-2 text-sm font-semibold text-fg">Theme</legend>
            <div className="grid grid-cols-3 gap-2">
              {OPTIONS.map((option) => (
                <label key={option.value} className="relative block cursor-pointer">
                  <input
                    type="radio"
                    name="theme"
                    value={option.value}
                    checked={preference === option.value}
                    onChange={() => setPreference(option.value)}
                    className="peer sr-only"
                  />
                  <span
                    className={cn(
                      "flex min-h-11 flex-col items-center justify-center gap-0.5 rounded-xl border border-line-strong px-1 text-xs font-semibold text-fg",
                      "peer-checked:border-accent peer-checked:bg-accent-soft hover:bg-raised",
                      "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-focus",
                    )}
                  >
                    <Icon name={option.icon} size={18} />
                    {option.label}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="mt-3 border-t border-line pt-1">
            <Switch
              checked={motion === "reduce"}
              onChange={(checked) => setMotion(checked ? "reduce" : "system")}
              label="Reduce motion"
              description="Replaces animation with static indicators and text. Also follows your system setting."
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
