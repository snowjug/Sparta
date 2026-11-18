"use client";

import { useLayoutEffect, type RefObject } from "react";

/**
 * Sets a CSS custom property through the CSSOM. Unlike a `style` attribute in markup this is not blocked by a strict
 * Content-Security-Policy, and it lets the stylesheet animate `transform` / `opacity` from the variable.
 */
export function useCssVar(ref: RefObject<HTMLElement | null>, name: string, value: string | number): void {
  useLayoutEffect(() => {
    ref.current?.style.setProperty(name, String(value));
  }, [ref, name, value]);
}
