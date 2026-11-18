import type { ApiClient, Download } from "./client";
import type {
  AssistantProfile,
  AuditEntry,
  BlockedCaller,
  CallDetail,
  CallListItem,
  CallListQuery,
  CreateCallRequest,
  CreateScenarioRequest,
  FeedbackRecord,
  HomeSummary,
  InterruptRequest,
  InterruptResult,
  ListNumberRequest,
  LiveEvent,
  LiveTicket,
  MeView,
  OwnerActionResult,
  Page,
  PartialRequest,
  PreviewRequest,
  PreviewResult,
  ProviderOption,
  ReplayRequest,
  ReplayResult,
  SafetyEvent,
  SafetyPolicy,
  ScenarioSummary,
  SystemStatus,
  TrustedCaller,
  TurnRequest,
  TurnResult,
  UserPreferences,
  VoiceConsent,
  VoiceEnrollRequest,
  VoiceOption,
  VoiceProfileView,
} from "./types";
import type { FeedbackKind } from "./enums";

interface Signalled {
  signal?: AbortSignal;
}

interface Keyed {
  idempotencyKey?: string;
}

/** One typed method per documented endpoint (docs/API_CONTRACT.md). Pure transport: no UI, no caching. */
export function createEndpoints(client: ApiClient) {
  const callPath = (id: string) => `/calls/${encodeURIComponent(id)}`;
  return {
    system: {
      status: (o: Signalled = {}) => client.get<SystemStatus>("/system/status", o),
      me: (o: Signalled = {}) => client.get<MeView>("/me", o),
      home: (o: Signalled = {}) => client.get<HomeSummary>("/home", o),
    },
    calls: {
      list: (query: CallListQuery = {}, o: Signalled = {}) =>
        client.get<Page<CallListItem>>("/calls", { ...o, query: { ...query } }),
      get: (id: string, o: Signalled = {}) => client.get<CallDetail>(callPath(id), o),
      events: (id: string, afterSeq: number, o: Signalled = {}) =>
        client.get<LiveEvent[]>(`${callPath(id)}/events`, { ...o, query: { after_seq: afterSeq } }),
      sendTurn: (id: string, body: TurnRequest, o: Keyed & Signalled = {}) =>
        client.post<TurnResult>(`${callPath(id)}/turns`, body, o),
      sendPartial: (id: string, body: PartialRequest, o: Signalled = {}) =>
        client.post<void>(`${callPath(id)}/partial`, body, o),
      sendAudio: (id: string, file: Blob, fileName: string, hints: { language_hint?: string; transcript_hint?: string }, o: Keyed & Signalled = {}) => {
        const form = new FormData();
        form.append("file", file, fileName);
        if (hints.language_hint) form.append("language_hint", hints.language_hint);
        if (hints.transcript_hint) form.append("transcript_hint", hints.transcript_hint);
        return client.request<TurnResult>("POST", `${callPath(id)}/audio`, { ...o, form });
      },
      interrupt: (id: string, body: InterruptRequest = {}, o: Signalled = {}) =>
        client.post<InterruptResult>(`${callPath(id)}/interrupt`, body, o),
      silence: (id: string, o: Signalled = {}) => client.post<TurnResult>(`${callPath(id)}/silence`, {}, o),
      takeover: (id: string, o: Keyed & Signalled = {}) => client.post<OwnerActionResult>(`${callPath(id)}/takeover`, {}, o),
      continueCall: (id: string, o: Keyed & Signalled = {}) => client.post<OwnerActionResult>(`${callPath(id)}/continue`, {}, o),
      end: (id: string, o: Keyed & Signalled = {}) => client.post<OwnerActionResult>(`${callPath(id)}/end`, {}, o),
      block: (id: string, reason: string | undefined, o: Keyed & Signalled = {}) =>
        client.post<BlockedCaller>(`${callPath(id)}/block`, reason ? { reason } : {}, o),
      trust: (id: string, label: string | undefined, o: Keyed & Signalled = {}) =>
        client.post<TrustedCaller>(`${callPath(id)}/trust`, label ? { label } : {}, o),
      feedback: (id: string, kind: FeedbackKind, note: string | undefined, o: Keyed & Signalled = {}) =>
        client.post<FeedbackRecord>(`${callPath(id)}/feedback`, note ? { kind, note } : { kind }, o),
      report: (id: string): Promise<Download> => client.download("GET", `${callPath(id)}/report`),
      exportJson: (id: string): Promise<Download> => client.download("GET", `${callPath(id)}/export`),
      deleteContent: (id: string) => client.delete<void>(`${callPath(id)}/content`),
      remove: (id: string) => client.delete<void>(callPath(id)),
      removeAll: () => client.delete<void>("/calls"),
    },
    live: {
      ticket: (callId?: string) => client.post<LiveTicket>("/live/ticket", callId ? { call_id: callId } : {}),
    },
    preferences: {
      get: (o: Signalled = {}) => client.get<UserPreferences>("/preferences", o),
      put: (body: UserPreferences) => client.put<UserPreferences>("/preferences", body),
    },
    assistant: {
      get: (o: Signalled = {}) => client.get<AssistantProfile>("/assistant-profile", o),
      put: (body: AssistantProfile) => client.put<AssistantProfile>("/assistant-profile", body),
      preview: (body: PreviewRequest, o: Signalled = {}) => client.post<PreviewResult>("/assistant-profile/preview", body, o),
      voices: (o: Signalled = {}) => client.get<VoiceOption[]>("/voices", o),
    },
    voice: {
      status: (o: Signalled = {}) => client.get<VoiceProfileView>("/voice/status", o),
      consent: (o: Signalled = {}) => client.get<VoiceConsent>("/voice/consent", o),
      enroll: (body: VoiceEnrollRequest, o: Keyed = {}) => client.post<VoiceProfileView>("/voice/enroll", body, o),
      remove: () => client.delete<void>("/voice"),
    },
    safety: {
      policies: (o: Signalled = {}) => client.get<SafetyPolicy>("/safety/policies", o),
      events: (limit = 20, o: Signalled = {}) => client.get<SafetyEvent[]>("/safety/events", { ...o, query: { limit } }),
      audit: (limit = 50, o: Signalled = {}) => client.get<AuditEntry[]>("/audit", { ...o, query: { limit } }),
      blocked: (o: Signalled = {}) => client.get<BlockedCaller[]>("/blocked-callers", o),
      addBlocked: (body: ListNumberRequest, o: Keyed = {}) => client.post<BlockedCaller>("/blocked-callers", body, o),
      removeBlocked: (id: string) => client.delete<void>(`/blocked-callers/${encodeURIComponent(id)}`),
      trusted: (o: Signalled = {}) => client.get<TrustedCaller[]>("/trusted-callers", o),
      addTrusted: (body: ListNumberRequest, o: Keyed = {}) => client.post<TrustedCaller>("/trusted-callers", body, o),
      removeTrusted: (id: string) => client.delete<void>(`/trusted-callers/${encodeURIComponent(id)}`),
    },
    simulator: {
      providers: (o: Signalled = {}) => client.get<ProviderOption[]>("/simulator/providers", o),
      scenarios: (o: Signalled = {}) => client.get<ScenarioSummary[]>("/simulator/scenarios", o),
      createScenario: (body: CreateScenarioRequest, o: Keyed = {}) => client.post<ScenarioSummary>("/simulator/scenarios", body, o),
      startCall: (body: CreateCallRequest, o: Keyed = {}) => client.post<CallDetail>("/simulator/calls", body, o),
      replay: (body: ReplayRequest) => client.post<ReplayResult>("/simulator/replay", body),
    },
  };
}

export type Endpoints = ReturnType<typeof createEndpoints>;
