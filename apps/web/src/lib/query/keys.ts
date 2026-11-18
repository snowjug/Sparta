import type { CallListQuery } from "../api/types";

export const qk = {
  status: ["system", "status"] as const,
  me: ["me"] as const,
  home: ["home"] as const,
  callsRoot: ["calls"] as const,
  calls: (filters: CallListQuery) => ["calls", "list", filters] as const,
  call: (id: string) => ["calls", "detail", id] as const,
  preferences: ["preferences"] as const,
  assistant: ["assistant-profile"] as const,
  voices: ["voices"] as const,
  voiceStatus: ["voice", "status"] as const,
  voiceConsent: ["voice", "consent"] as const,
  policies: ["safety", "policies"] as const,
  safetyEvents: (limit: number) => ["safety", "events", limit] as const,
  audit: (limit: number) => ["safety", "audit", limit] as const,
  blocked: ["safety", "blocked"] as const,
  trusted: ["safety", "trusted"] as const,
  scenarios: ["simulator", "scenarios"] as const,
  providers: ["simulator", "providers"] as const,
};
