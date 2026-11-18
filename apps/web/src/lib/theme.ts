"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import { readStorage, STORAGE_KEYS, subscribeStorage, writeStorage } from "./storage";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";
export type MotionPreference = "system" | "reduce";

function subscribeMedia(query: string) {
  return (callback: () => void) => {
    if (typeof window === "undefined" || !window.matchMedia) return () => {};
    const list = window.matchMedia(query);
    list.addEventListener("change", callback);
    return () => list.removeEventListener("change", callback);
  };
}

function matches(query: string): boolean {
  return typeof window !== "undefined" && !!window.matchMedia && window.matchMedia(query).matches;
}

const subscribeLight = subscribeMedia("(prefers-color-scheme: light)");
const subscribeReduce = subscribeMedia("(prefers-reduced-motion: reduce)");

function readThemePreference(): ThemePreference {
  const stored = readStorage(STORAGE_KEYS.theme);
  return stored === "light" || stored === "dark" ? stored : "system";
}

export function resolveTheme(preference: ThemePreference, systemPrefersLight: boolean): ResolvedTheme {
  if (preference === "light" || preference === "dark") return preference;
  return systemPrefersLight ? "light" : "dark";
}

export function useTheme() {
  const preference = useSyncExternalStore(subscribeStorage, readThemePreference, () => "system" as ThemePreference);
  const systemPrefersLight = useSyncExternalStore(subscribeLight, () => matches("(prefers-color-scheme: light)"), () => false);
  const resolved = resolveTheme(preference, systemPrefersLight);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", resolved);
    root.setAttribute("data-theme-pref", preference);
  }, [resolved, preference]);

  const setPreference = useCallback((next: ThemePreference) => {
    writeStorage(STORAGE_KEYS.theme, next === "system" ? null : next);
  }, []);

  return { preference, resolved, setPreference };
}

function readMotionPreference(): MotionPreference {
  return readStorage(STORAGE_KEYS.motion) === "reduce" ? "reduce" : "system";
}

/** True when the OS asks for reduced motion or the owner chose "Reduce motion" in the display menu. */
export function useReducedMotion(): boolean {
  const system = useSyncExternalStore(subscribeReduce, () => matches("(prefers-reduced-motion: reduce)"), () => false);
  const manual = useSyncExternalStore(subscribeStorage, () => readMotionPreference() === "reduce", () => false);
  return system || manual;
}

export function useMotionPreference() {
  const preference = useSyncExternalStore(subscribeStorage, readMotionPreference, () => "system" as MotionPreference);
  const setPreference = useCallback((next: MotionPreference) => {
    writeStorage(STORAGE_KEYS.motion, next === "reduce" ? "reduce" : null);
    const root = document.documentElement;
    if (next === "reduce") root.setAttribute("data-motion", "reduce");
    else root.removeAttribute("data-motion");
  }, []);
  return { preference, setPreference };
}
