import type {
  CallCategory,
  CallState,
  FeedbackKind,
  OwnerActionType,
  RecommendedAction,
  ScreeningStrictness,
  SignalCode,
  SignalSeverity,
  VoiceStatus,
} from "./api/enums";
import { languageName, variantLabel } from "./language";

/** Plain-language labels for API vocabularies. Unknown values (newer server) fall back to a readable form. */

export function humanize(value: string): string {
  const text = value.replace(/[_.-]+/g, " ").trim().toLowerCase();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : value;
}

export const CATEGORY_LABELS: Record<CallCategory, string> = {
  unknown: "Not classified yet",
  silent: "Silent call",
  possible_financial_impersonation: "Possible bank or financial impersonation",
  possible_government_impersonation: "Possible government impersonation",
  possible_courier_impersonation: "Possible courier impersonation",
  possible_tech_support_scam: "Possible tech-support scam",
  possible_prize_scam: "Possible prize scam",
  possible_employer_impersonation: "Possible employer impersonation",
  prompt_injection_attempt: "Tried to manipulate the assistant",
  telemarketing: "Telemarketing",
  harassment: "Harassment",
  legitimate_delivery: "Delivery",
  legitimate_appointment: "Appointment",
  legitimate_recruiter: "Recruiter",
  legitimate_support_callback: "Support callback",
  legitimate_personal: "Personal call",
  legitimate_urgent: "Urgent and likely genuine",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category as CallCategory] ?? humanize(category);
}

export const STATE_LABELS: Record<CallState, string> = {
  INITIALIZING: "Connecting",
  DISCLOSURE: "Introducing itself as AI",
  IDENTIFY_CALLER: "Asking who is calling",
  IDENTIFY_PURPOSE: "Asking why they called",
  CLARIFY: "Asking for clarification",
  ASSESSING: "Assessing the call",
  SAFE_CONTINUE: "Continuing safely",
  ESCALATE: "Waiting for you",
  REFUSE_SENSITIVE_REQUEST: "Refusing a protected request",
  END_SPAM: "Ending the call (spam)",
  END_SILENCE: "Ending the call (silence)",
  OWNER_TAKEOVER: "You took over",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

export function stateLabel(state: string | null | undefined): string {
  if (!state) return "Waiting";
  return STATE_LABELS[state as CallState] ?? humanize(state);
}

export const ACTION_LABELS: Record<RecommendedAction, string> = {
  continue_screening: "Keep screening",
  ask_clarifying_question: "Ask a clarifying question",
  escalate_to_owner: "Escalate to you",
  refuse_and_end: "Refuse and end the call",
  end_spam: "End as spam",
  block_recommended: "Blocking recommended",
  report_recommended: "Reporting recommended",
  human_review: "Needs your review",
};

export function actionLabel(action: string | null | undefined): string {
  if (!action) return "No action";
  return ACTION_LABELS[action as RecommendedAction] ?? humanize(action);
}

export const SIGNAL_LABELS: Record<SignalCode, string> = {
  OTP_REQUEST: "Asked for a one-time code (OTP)",
  PASSWORD_REQUEST: "Asked for a password",
  PIN_REQUEST: "Asked for a PIN",
  CVV_REQUEST: "Asked for a card security code",
  CARD_OR_ACCOUNT_CREDENTIAL_REQUEST: "Asked for card or account details",
  AUTH_OR_RECOVERY_CODE_REQUEST: "Asked for a login or recovery code",
  IDENTITY_DOCUMENT_REQUEST: "Asked for an ID document",
  ADDRESS_OR_LOCATION_REQUEST: "Asked for your address or location",
  OWNER_AVAILABILITY_PROBE: "Probed whether you are home or reachable",
  REMOTE_ACCESS_REQUEST: "Asked to install remote-access software",
  SCREEN_SHARING_REQUEST: "Asked you to share your screen",
  PAYMENT_OR_TRANSFER_REQUEST: "Asked for a payment or transfer",
  GIFT_CARD_OR_CRYPTO_REQUEST: "Asked for gift cards or crypto",
  MALICIOUS_LINK_OR_CALLBACK: "Pushed a suspicious link or callback number",
  ARREST_OR_LEGAL_THREAT: "Threatened arrest or legal action",
  ACCOUNT_CLOSURE_THREAT: "Threatened to close an account",
  FAKE_KYC_URGENCY: "Urgent verification (KYC) pressure",
  URGENCY_PRESSURE: "Pressured you to act immediately",
  SUSPICIOUS_PRIZE: "Offered a suspicious prize",
  IMPERSONATION_BANK: "Claimed to be a bank",
  IMPERSONATION_GOVERNMENT: "Claimed to be a government office",
  IMPERSONATION_POLICE: "Claimed to be the police",
  IMPERSONATION_COURIER: "Claimed to be a courier",
  IMPERSONATION_EMPLOYER: "Claimed to be an employer",
  RULE_OVERRIDE_ATTEMPT: "Tried to change the assistant's rules",
  FALSE_OWNER_AUTHORIZATION: "Claimed you had authorised them",
  HARASSMENT_OR_ABUSE: "Abusive or harassing language",
  TELEMARKETING: "Sales or marketing call",
  LEGIT_DELIVERY_COORDINATION: "Looks like delivery coordination",
  LEGIT_APPOINTMENT_CONFIRMATION: "Looks like an appointment confirmation",
  LEGIT_RECRUITER_INTRO: "Looks like a recruiter introduction",
  LEGIT_KNOWN_SERVICE_CALLBACK: "Callback from a service you use",
  LEGIT_FAMILY_OR_FRIEND: "Looks like family or a friend",
  LEGIT_SCHOOL_OR_HOSPITAL: "Looks like a school or hospital",
  LEGIT_EMERGENCY_CONTEXT: "Possible emergency",
  LEGIT_SUPPORT_CALLBACK: "Looks like a support callback",
};

export function signalLabel(code: string): string {
  return SIGNAL_LABELS[code as SignalCode] ?? humanize(code);
}

export const SEVERITY_LABELS: Record<SignalSeverity, string> = {
  info: "Info",
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const FEEDBACK_LABELS: Record<FeedbackKind, string> = {
  correct_classification: "Classification is correct",
  was_spam: "This was spam",
  was_legitimate: "This was legitimate",
  wrong_language: "Wrong language",
  poor_transcription: "Poor transcription",
  wrong_summary: "Wrong summary",
  trust_caller: "Trust this caller",
  block_caller: "Block this caller",
};

export const OWNER_ACTION_LABELS: Record<OwnerActionType, string> = {
  takeover: "Took over the call",
  continue: "Let Sparta continue",
  end: "Ended the call",
  block: "Blocked the caller",
  trust: "Marked the caller as trusted",
  unblock: "Unblocked the caller",
  untrust: "Removed trust",
};

export const STRICTNESS_LABELS: Record<ScreeningStrictness, { label: string; description: string }> = {
  relaxed: { label: "Relaxed", description: "Fewer interruptions. Sparta escalates only when it is fairly sure a call is genuine." },
  balanced: { label: "Balanced", description: "Recommended. Sparta screens carefully and asks you when it is unsure." },
  strict: { label: "Strict", description: "Maximum caution. Sparta refuses more and ends doubtful calls sooner." },
};

export const VOICE_STATUS_LABELS: Record<VoiceStatus, string> = {
  not_enrolled: "Not enrolled",
  consent_recorded: "Consent recorded",
  pending_provider_approval: "Waiting for provider approval",
  ready: "Ready",
  failed: "Failed",
  deleted: "Deleted",
};

/** Timeline entries arrive as short machine-flavoured labels ("State: IDENTIFY_CALLER"): render them in plain words. */
export function timelineLabel(entry: { label: string }): string {
  const state = /^State: ([A-Z_]+)$/.exec(entry.label);
  if (state) return `Step: ${stateLabel(state[1])}`;
  const language = /^Language: ([\w-]+)(?: \((\w+)\))?$/.exec(entry.label);
  if (language) {
    const variant = variantLabel(language[2]?.toLowerCase());
    return `Language: ${languageName(language[1])}${variant ? ` (${variant})` : ""}`;
  }
  return entry.label;
}

export function timelineDetail(detail: string | null | undefined): string {
  if (!detail) return "";
  return ACTION_LABELS[detail as RecommendedAction] ?? humanize(detail);
}
