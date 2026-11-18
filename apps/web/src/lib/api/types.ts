// API types. Source of truth: packages/contracts/openapi.json -> src/lib/api/generated.ts (`npm run types:api`).
// This file is the thin layer on top:
//  * response DTOs are generated types made fully required (the API always serialises every field, including defaults),
//  * request bodies stay as generated (fields with server defaults are optional),
//  * a compile-time check keeps the hand-written enum vocabularies in enums.ts in lock-step with the contract.
import type {
  CallCategory,
  CallState,
  CallStatus,
  EscalationStatus,
  FeedbackKind,
  LiveEventType,
  OwnerActionType,
  ProviderKind,
  RecommendedAction,
  ResponseStyle,
  RiskLevel,
  ScreeningStrictness,
  SignalCode,
  SignalKind,
  SignalSeverity,
  Speaker,
  TurnSource,
  VoiceStatus,
} from "./enums";
import type { components } from "./generated";

type S = components["schemas"];

/** Makes every property required, recursively, while keeping `| null`. */
export type DeepRequired<T> = T extends readonly (infer U)[]
  ? DeepRequired<U>[]
  : T extends object
    ? { [K in keyof T]-?: DeepRequired<Exclude<T[K], undefined>> }
    : T;

export type IsoDateTime = string;
/** 0..1 */
export type Score = number;

// ------------------------------------------------------------------------------------------------ call content

export type LatencyBreakdown = DeepRequired<S["LatencyBreakdown"]>;
export type LanguageSegment = DeepRequired<S["LanguageSegment"]>;
export type ScriptCode = LanguageSegment["script"];
export type LanguageVariant = NonNullable<LanguageSegment["variant"]>;
export type SpeechPlan = DeepRequired<S["SpeechPlan"]>;
export type CallerClaim = DeepRequired<S["CallerClaim"]>;
export type RiskSignal = DeepRequired<S["RiskSignal"]>;
export type RiskAssessment = DeepRequired<S["RiskAssessment"]>;
export type CallTurn = DeepRequired<S["CallTurn"]>;
export type Escalation = DeepRequired<S["Escalation"]>;
export type OwnerAction = DeepRequired<S["OwnerAction"]>;
export type CallSummary = DeepRequired<S["CallSummary"]>;
export type FeedbackRecord = DeepRequired<S["FeedbackRecord"]>;
export type ProviderEventRecord = DeepRequired<S["ProviderEventRecord"]>;
export type TimelineEntry = DeepRequired<S["TimelineEntry"]>;
export type TimelineKind = TimelineEntry["kind"];
export type VersionInfo = DeepRequired<S["VersionInfo"]>;
export type CallListItem = DeepRequired<S["CallListItem"]>;
export type CallCapabilities = DeepRequired<S["CallCapabilities"]>;
export type CallDetail = DeepRequired<S["CallDetail"]>;

// ------------------------------------------------------------------------------------------------ requests / results

export type CreateCallRequest = S["CreateCallRequest"];
export type TurnRequest = S["TurnRequest"];
export type PartialRequest = S["PartialRequest"];
export type InterruptRequest = S["InterruptRequest"];
export type FeedbackRequest = S["FeedbackRequest"];
export type TurnResult = DeepRequired<S["TurnResult"]>;
export type OwnerActionResult = DeepRequired<S["OwnerActionResult"]>;
export type InterruptResult = DeepRequired<S["InterruptResult"]>;

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
}

export interface CallListQuery {
  q?: string;
  risk_level?: RiskLevel;
  category?: CallCategory;
  language?: string;
  status?: CallStatus;
  attention?: boolean;
  provider?: ProviderKind;
  from?: string;
  to?: string;
  limit?: number;
  cursor?: string;
}

// ------------------------------------------------------------------------------------------------ live events

export interface LiveEvent<D = Record<string, unknown>> {
  type: LiveEventType | (string & {});
  call_id: string;
  seq: number;
  ts: IsoDateTime;
  simulated: boolean;
  data: D;
}

export type LiveTicket = DeepRequired<S["TicketResponse"]>;

// ------------------------------------------------------------------------------------------------ system / home

export type TelephonyView = DeepRequired<S["TelephonyView"]>;
export type LanguageView = DeepRequired<S["LanguageView"]>;
export type SystemStatus = DeepRequired<S["SystemStatus"]>;
export type MeView = DeepRequired<S["MeView"]>;
export type HomeSummary = DeepRequired<S["HomeSummary"]>;
export type ProtectionStatus = HomeSummary["protection"]["status"];

// ------------------------------------------------------------------------------------------------ preferences

export type RetentionPolicy = DeepRequired<S["RetentionPolicy"]>;
export type EscalationRules = DeepRequired<S["EscalationRules"]>;
export type NotificationPreferences = DeepRequired<S["NotificationPreferences"]>;
export type UserPreferences = DeepRequired<S["UserPreferences"]>;
export type AssistantProfile = DeepRequired<S["AssistantProfile"]>;
export type TrustedContactBehavior = UserPreferences["trusted_contact_behavior"];
export type UnknownCallerBehavior = UserPreferences["unknown_caller_behavior"];
export type VoiceOption = DeepRequired<S["VoiceOption"]>;
export type VoiceProfileView = DeepRequired<S["VoiceProfileView"]>;
export type VoiceConsent = DeepRequired<S["VoiceConsentView"]>;
export type VoiceEnrollRequest = S["VoiceEnrollRequest"];
export type PreviewRequest = S["PreviewRequest"];
export type PreviewResult = DeepRequired<S["PreviewResult"]>;

// ------------------------------------------------------------------------------------------------ safety center

export type ProtectedInfo = DeepRequired<S["ProtectedInfoView"]>;
export type SignalView = DeepRequired<S["SignalView"]>;
export type SafetyPolicy = DeepRequired<S["SafetyPolicyView"]>;
export type SafetyEvent = DeepRequired<S["SafetyEventView"]>;
export type AuditEntry = DeepRequired<S["AuditEntry"]>;
export type BlockedCaller = DeepRequired<S["BlockedCaller"]>;
export type TrustedCaller = DeepRequired<S["TrustedCaller"]>;
export type ListNumberRequest = S["ListNumberRequest"];

// ------------------------------------------------------------------------------------------------ simulator

export type ProviderOption = DeepRequired<S["ProviderOption"]>;
export type ScenarioTurnInput = S["ScenarioTurn"];
export type CreateScenarioRequest = S["CreateScenarioRequest"];
export type ScenarioSummary = DeepRequired<S["ScenarioSummary"]>;
export type ReplayRequest = S["ReplayRequest"];
export interface ReplayResult {
  call: CallDetail;
  events: LiveEvent[];
  checksum: string;
  checksum_covers: string;
}

// ------------------------------------------------------------------------------------------------ errors

export type ApiErrorDetail = DeepRequired<S["ErrorDetail"]>;
export type ApiErrorEnvelope = S["ErrorEnvelope"];

// ------------------------------------------------------------------------------------------------ contract drift guard
// If the API adds, renames or removes an enum value, `npm run typecheck` fails here until enums.ts is updated.

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Expect<T extends true> = T;

export type EnumDriftChecks = [
  Expect<Equal<CallState, S["CallState"]>>,
  Expect<Equal<CallStatus, S["CallStatus"]>>,
  Expect<Equal<RiskLevel, S["RiskLevel"]>>,
  Expect<Equal<RecommendedAction, S["RecommendedAction"]>>,
  Expect<Equal<SignalSeverity, S["SignalSeverity"]>>,
  Expect<Equal<SignalKind, S["SignalKind"]>>,
  Expect<Equal<SignalCode, S["SignalCode"]>>,
  Expect<Equal<CallCategory, S["CallCategory"]>>,
  Expect<Equal<Speaker, S["Speaker"]>>,
  Expect<Equal<TurnSource, S["TurnSource"]>>,
  Expect<Equal<ProviderKind, S["ProviderKind"]>>,
  Expect<Equal<OwnerActionType, S["OwnerActionType"]>>,
  Expect<Equal<EscalationStatus, S["EscalationStatus"]>>,
  Expect<Equal<FeedbackKind, S["FeedbackKind"]>>,
  Expect<Equal<ScreeningStrictness, S["ScreeningStrictness"]>>,
  Expect<Equal<ResponseStyle, S["ResponseStyle"]>>,
  Expect<Equal<VoiceStatus, S["VoiceStatus"]>>,
];
