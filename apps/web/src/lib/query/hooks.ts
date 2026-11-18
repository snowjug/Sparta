"use client";

import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useApi } from "../api/provider";
import type { CallListQuery } from "../api/types";
import { qk } from "./keys";

export function useSystemStatus() {
  const api = useApi();
  return useQuery({ queryKey: qk.status, queryFn: ({ signal }) => api.system.status({ signal }), staleTime: 30_000 });
}

export function useMe() {
  const api = useApi();
  return useQuery({ queryKey: qk.me, queryFn: ({ signal }) => api.system.me({ signal }), staleTime: 60_000 });
}

export function useHome() {
  const api = useApi();
  return useQuery({
    queryKey: qk.home,
    queryFn: ({ signal }) => api.system.home({ signal }),
    staleTime: 3_000,
    refetchInterval: 8_000,
  });
}

/** Calls that are in progress right now (polled: the all-calls live stream is not needed for a short list). */
export function useActiveCalls() {
  const api = useApi();
  return useQuery({
    queryKey: qk.calls({ status: "active", limit: 10 }),
    queryFn: ({ signal }) => api.calls.list({ status: "active", limit: 10 }, { signal }),
    refetchInterval: 4_000,
    staleTime: 1_000,
  });
}

export function usePreferences() {
  const api = useApi();
  return useQuery({ queryKey: qk.preferences, queryFn: ({ signal }) => api.preferences.get({ signal }), staleTime: 30_000 });
}

export function useAssistantProfile() {
  const api = useApi();
  return useQuery({ queryKey: qk.assistant, queryFn: ({ signal }) => api.assistant.get({ signal }), staleTime: 30_000 });
}

export function useVoices() {
  const api = useApi();
  return useQuery({ queryKey: qk.voices, queryFn: ({ signal }) => api.assistant.voices({ signal }), staleTime: 5 * 60_000 });
}

export function useVoiceStatus() {
  const api = useApi();
  return useQuery({ queryKey: qk.voiceStatus, queryFn: ({ signal }) => api.voice.status({ signal }) });
}

export function useVoiceConsent(enabled = true) {
  const api = useApi();
  return useQuery({ queryKey: qk.voiceConsent, queryFn: ({ signal }) => api.voice.consent({ signal }), enabled, staleTime: 5 * 60_000 });
}

export function useCall(id: string | null | undefined) {
  const api = useApi();
  return useQuery({
    queryKey: qk.call(id ?? ""),
    queryFn: ({ signal }) => api.calls.get(id as string, { signal }),
    enabled: Boolean(id),
    staleTime: 3_000,
  });
}

export function useCallsInfinite(filters: CallListQuery, pageSize = 20) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: qk.calls(filters),
    queryFn: ({ pageParam, signal }) => api.calls.list({ ...filters, limit: pageSize, cursor: pageParam }, { signal }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    placeholderData: keepPreviousData,
    staleTime: 5_000,
  });
}

export function useSafetyPolicies() {
  const api = useApi();
  return useQuery({ queryKey: qk.policies, queryFn: ({ signal }) => api.safety.policies({ signal }), staleTime: 5 * 60_000 });
}

export function useSafetyEvents(limit = 20) {
  const api = useApi();
  return useQuery({ queryKey: qk.safetyEvents(limit), queryFn: ({ signal }) => api.safety.events(limit, { signal }) });
}

export function useAudit(limit = 50) {
  const api = useApi();
  return useQuery({ queryKey: qk.audit(limit), queryFn: ({ signal }) => api.safety.audit(limit, { signal }) });
}

export function useBlockedCallers() {
  const api = useApi();
  return useQuery({ queryKey: qk.blocked, queryFn: ({ signal }) => api.safety.blocked({ signal }) });
}

export function useTrustedCallers() {
  const api = useApi();
  return useQuery({ queryKey: qk.trusted, queryFn: ({ signal }) => api.safety.trusted({ signal }) });
}

export function useScenarios() {
  const api = useApi();
  return useQuery({ queryKey: qk.scenarios, queryFn: ({ signal }) => api.simulator.scenarios({ signal }), staleTime: 60_000 });
}

export function useProviders() {
  const api = useApi();
  return useQuery({ queryKey: qk.providers, queryFn: ({ signal }) => api.simulator.providers({ signal }), staleTime: 30_000 });
}
