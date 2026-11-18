"use client";

import { useCallback, useSyncExternalStore } from "react";
import { readStorage, subscribeStorage, writeStorage } from "./storage";

type Kind = "local" | "session";

/** A boolean preference kept in localStorage (no personal data). Server render and first paint use the default. */
export function useStoredBoolean(key: string, defaultValue = false): [boolean, (next: boolean) => void] {
  const value = useSyncExternalStore(
    subscribeStorage,
    () => {
      const stored = readStorage(key);
      return stored === "1" ? true : stored === "0" ? false : defaultValue;
    },
    () => defaultValue,
  );
  const set = useCallback((next: boolean) => writeStorage(key, next ? "1" : "0"), [key]);
  return [value, set];
}

/** A string preference kept in local or session storage. */
export function useStoredString(key: string, defaultValue: string, kind: Kind = "local"): [string, (next: string) => void] {
  const value = useSyncExternalStore(
    subscribeStorage,
    () => readStorage(key, kind) ?? defaultValue,
    () => defaultValue,
  );
  const set = useCallback((next: string) => writeStorage(key, next, kind), [key, kind]);
  return [value, set];
}
