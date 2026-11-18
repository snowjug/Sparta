import type { CallTurn } from "./api/types";

export interface LanguageInfo {
  name: string;
  native: string;
  short: string;
}

/** Fallback names. The live list comes from GET /system/status (languages[]), which also lists planned languages. */
export const KNOWN_LANGUAGES: Record<string, LanguageInfo> = {
  "en-IN": { name: "English", native: "English", short: "EN" },
  "hi-IN": { name: "Hindi", native: "हिन्दी", short: "HI" },
  "kn-IN": { name: "Kannada", native: "ಕನ್ನಡ", short: "KN" },
  "ta-IN": { name: "Tamil", native: "தமிழ்", short: "TA" },
  "te-IN": { name: "Telugu", native: "తెలుగు", short: "TE" },
  "mr-IN": { name: "Marathi", native: "मराठी", short: "MR" },
  "ml-IN": { name: "Malayalam", native: "മലയാളം", short: "ML" },
  "bn-IN": { name: "Bengali", native: "বাংলা", short: "BN" },
};

function lookup(code: string | null | undefined): LanguageInfo | null {
  if (!code) return null;
  if (KNOWN_LANGUAGES[code]) return KNOWN_LANGUAGES[code];
  const base = code.split("-")[0]?.toLowerCase();
  const match = Object.entries(KNOWN_LANGUAGES).find(([key]) => key.split("-")[0]?.toLowerCase() === base);
  return match ? match[1] : null;
}

export function languageName(code: string | null | undefined): string {
  if (!code || code === "und") return "Unknown language";
  if (code === "auto") return "Auto-detect";
  return lookup(code)?.name ?? code;
}

export function languageShort(code: string | null | undefined): string {
  if (!code || code === "und") return "?";
  return lookup(code)?.short ?? code.split("-")[0]!.toUpperCase();
}

export type Variant = "hinglish" | "kanglish";

export function variantOf(turn: Pick<CallTurn, "language_profile" | "segments">): Variant | null {
  const profile = turn.language_profile?.toLowerCase();
  if (profile === "hinglish" || profile === "kanglish") return profile;
  const fromSegment = turn.segments?.find((segment) => segment.variant)?.variant;
  return fromSegment ?? null;
}

export function variantLabel(variant: Variant | string | null | undefined): string | null {
  if (variant === "hinglish") return "Hinglish";
  if (variant === "kanglish") return "Kanglish";
  return null;
}

export function profileLabel(profile: string | null | undefined): string | null {
  if (!profile) return null;
  const variant = variantLabel(profile.toLowerCase());
  if (variant) return variant;
  const known = lookup(
    ({ english: "en-IN", hindi: "hi-IN", kannada: "kn-IN" } as Record<string, string>)[profile.toLowerCase()] ?? null,
  );
  return known ? known.name : profile.charAt(0).toUpperCase() + profile.slice(1);
}

export interface TurnLanguage {
  code: string | null;
  name: string;
  short: string;
  variant: string | null;
  confidence: number | null;
}

export function turnLanguage(turn: Pick<CallTurn, "language" | "language_profile" | "segments" | "language_confidence">): TurnLanguage {
  return {
    code: turn.language,
    name: languageName(turn.language),
    short: languageShort(turn.language),
    variant: variantLabel(variantOf(turn)),
    confidence: turn.language_confidence,
  };
}

export interface LanguageChange {
  /** Turn id of the caller turn that is spoken in the new language. */
  beforeTurnId: string;
  from: string;
  to: string;
  variant: string | null;
}

/** Caller turns only: the assistant simply follows the caller's language. */
export function languageChanges(turns: ReadonlyArray<CallTurn>): LanguageChange[] {
  const changes: LanguageChange[] = [];
  let previous: string | null = null;
  for (const turn of turns) {
    if (turn.speaker !== "caller" || !turn.language || turn.language === "und") continue;
    if (previous && previous !== turn.language) {
      changes.push({ beforeTurnId: turn.id, from: previous, to: turn.language, variant: variantLabel(variantOf(turn)) });
    }
    previous = turn.language;
  }
  return changes;
}

/** BCP-47 tag safe for the HTML `lang` attribute (screen readers pick the right voice, fonts pick the right script). */
export function htmlLang(code: string | null | undefined): string | undefined {
  if (!code || code === "und" || code === "auto") return undefined;
  return code;
}

/** Locale handed to the browser's SpeechRecognition. "auto" uses the browser language, defaulting to Indian English. */
export function recognitionLocale(selection: string, browserLanguage?: string): string {
  if (selection && selection !== "auto") return selection;
  const language = browserLanguage ?? (typeof navigator !== "undefined" ? navigator.language : "");
  return language && language.length >= 2 ? language : "en-IN";
}
