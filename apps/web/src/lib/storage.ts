/** localStorage/sessionStorage wrappers that never throw (private mode, quota, SSR). Never store call content or numbers. */

type Kind = "local" | "session";

function area(kind: Kind): Storage | null {
  try {
    if (typeof window === "undefined") return null;
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readStorage(key: string, kind: Kind = "local"): string | null {
  try {
    return area(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string | null, kind: Kind = "local"): void {
  try {
    const store = area(kind);
    if (!store) return;
    if (value === null) store.removeItem(key);
    else store.setItem(key, value);
    if (typeof window !== "undefined") window.dispatchEvent(new Event(STORAGE_EVENT));
  } catch {
    /* storage unavailable: preferences simply do not persist */
  }
}

const STORAGE_EVENT = "sparta:storage";

/** Subscribe to same-tab (custom event) and cross-tab (`storage` event) changes of stored preferences. */
export function subscribeStorage(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(STORAGE_EVENT, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(STORAGE_EVENT, callback);
    window.removeEventListener("storage", callback);
  };
}

export const STORAGE_KEYS = {
  theme: "sparta.theme",
  motion: "sparta.motion",
  devUser: "sparta.dev_user",
  showTranslation: "sparta.show_translation",
  onboardingStep: "sparta.onboarding.step",
  onboardingSkipped: "sparta.onboarding.skipped",
  labLanguage: "sparta.lab.language",
  labHear: "sparta.lab.hear",
} as const;
