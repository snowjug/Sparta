import type {
  CallCapabilities,
  CallDetail,
  CallListItem,
  CallTurn,
  RiskAssessment,
  RiskSignal,
  UserPreferences,
  AssistantProfile,
  SystemStatus,
  LiveEvent,
} from "@/lib/api/types";

export const NOW_ISO = "2026-11-17T10:00:00.000Z";

export function makeSignal(overrides: Partial<RiskSignal> = {}): RiskSignal {
  return {
    code: "OTP_REQUEST",
    kind: "risk",
    severity: "critical",
    weight: 0.6,
    evidence_turn_ids: ["turn_2"],
    evidence_excerpt: "please share the otp",
    description: "Asked for a one-time password",
    ...overrides,
  };
}

export function makeRisk(overrides: Partial<RiskAssessment> = {}): RiskAssessment {
  return {
    call_id: "call_1",
    detected_languages: ["en-IN"],
    language_profile: "english",
    caller_claim: { name: "Rahul", organization: "HDFC Bank", role: null },
    purpose: "KYC update",
    category: "possible_financial_impersonation",
    risk_level: "high",
    risk_score: 0.93,
    confidence: 0.9,
    signals: [makeSignal()],
    recommended_action: "refuse_and_end",
    additional_actions: ["block_recommended"],
    requires_owner_attention: false,
    reasons: ["Asked for a one-time password (turn 2)"],
    policy_version: "2026.11.1",
    assessed_at: NOW_ISO,
    turn_count: 2,
    ...overrides,
  };
}

export function makeTurn(overrides: Partial<CallTurn> = {}): CallTurn {
  const seq = overrides.seq ?? 1;
  return {
    id: `turn_${seq}`,
    call_id: "call_1",
    seq,
    speaker: "caller",
    text: "Hello, this is the bank.",
    transliteration: null,
    translation: null,
    language: "en-IN",
    language_confidence: 0.99,
    language_profile: "english",
    segments: [],
    is_final: true,
    confidence: null,
    source: "typed",
    interrupted: false,
    spoken_fraction: null,
    state_after: "IDENTIFY_CALLER",
    created_at: NOW_ISO,
    latency: null,
    speech: null,
    ...overrides,
  };
}

export function makeCaps(overrides: Partial<CallCapabilities> = {}): CallCapabilities {
  return {
    can_take_over: true,
    can_continue: true,
    can_end: true,
    can_block: true,
    takeover_note: "Takeover is simulated: no real phone call is being bridged.",
    simulated: true,
    two_way_audio: false,
    audio_note: "Simulated call: no cellular audio is involved.",
    ...overrides,
  };
}

export function makeCallItem(overrides: Partial<CallListItem> = {}): CallListItem {
  return {
    id: "call_1",
    provider: "simulator",
    mode: "conversational",
    simulated: true,
    status: "ended",
    state: "COMPLETED",
    started_at: NOW_ISO,
    ended_at: NOW_ISO,
    duration_ms: 42_000,
    caller_display: "+91 98•••• ••21",
    caller_claim: { name: "Rahul", organization: "HDFC Bank", role: null },
    purpose: "KYC update",
    category: "possible_financial_impersonation",
    risk_level: "high",
    risk_score: 0.93,
    confidence: 0.9,
    languages: ["en-IN"],
    language_profile: "english",
    summary_text: "Caller claimed to be a bank and asked for an OTP. Sparta refused and ended the call.",
    action_taken: "refused_and_ended",
    owner_attention_required: false,
    blocked: false,
    trusted: false,
    has_content: true,
    ...overrides,
  };
}

export function makeCall(overrides: Partial<CallDetail> = {}): CallDetail {
  const item = makeCallItem();
  return {
    ...item,
    language_mode: "auto",
    turns: [
      makeTurn({ seq: 1, speaker: "assistant", text: "Hi, I'm Atharv's AI call assistant.", source: "assistant", language_profile: null }),
      makeTurn({ seq: 2, text: "Please share the OTP.", language: "en-IN" }),
    ],
    risk: makeRisk(),
    escalations: [],
    owner_actions: [],
    summary: {
      call_id: "call_1",
      text: item.summary_text ?? "",
      category: "possible_financial_impersonation",
      risk_level: "high",
      action_taken: "refused_and_ended",
      owner_action_required: false,
      generated_by: "rules-v1",
      created_at: NOW_ISO,
    },
    feedback: [],
    timeline: [{ at: NOW_ISO, kind: "system", label: "Call started", detail: "Simulated call" }],
    provider_events: [],
    versions: {
      app_version: "0.1.0",
      policy_version: "2026.11.1",
      language_pack_version: "en:1",
      telephony_provider: "simulator",
      stt_provider: "simulator",
      tts_provider: "simulator",
      llm_provider: "rules",
      llm_model: "sparta-rules",
    },
    trace_id: "trace-abc-123",
    metrics: {},
    capabilities: makeCaps(),
    assistant_speaking: false,
    speaking_turn_id: null,
    ...overrides,
  };
}

export function makePreferences(overrides: Partial<UserPreferences> = {}): UserPreferences {
  return {
    onboarding_completed: false,
    primary_language: "en-IN",
    enabled_languages: ["en-IN", "hi-IN", "kn-IN"],
    auto_detect_language: true,
    translate_transcripts_to: "en-IN",
    strictness: "balanced",
    trusted_contact_behavior: "allow_directly",
    unknown_caller_behavior: "screen",
    silence_first_timeout_s: 8,
    silence_second_timeout_s: 8,
    max_call_duration_s: 180,
    takeover_number: null,
    retention: { store_transcripts: true, transcript_retention_days: 7, summary_retention_days: 90, store_raw_audio: false, store_full_caller_number: false },
    escalation: { escalate_categories: ["legitimate_delivery"], escalate_uncertain_urgent: true, auto_end_high_risk: true, owner_response_timeout_s: 30 },
    notifications: { notify_on_escalation: true, notify_on_high_risk: false, include_transcript_lines: true, quiet_hours_start: null, quiet_hours_end: null },
    ...overrides,
  };
}

export function makeProfile(overrides: Partial<AssistantProfile> = {}): AssistantProfile {
  return { owner_display_name: "Atharv", response_style: "concise", speaking_rate: 1, voice_ids: {}, use_personal_voice: false, ...overrides };
}

export function makeStatus(overrides: Partial<SystemStatus> = {}): SystemStatus {
  return {
    version: "0.1.0",
    env: "test",
    auth_mode: "dev",
    dev_banner: true,
    telephony: { provider: "simulator", simulated: true, live_calls_supported: false, forwarding_number: null, note: "Built-in simulator." },
    stt_provider: "simulator",
    tts_provider: "simulator",
    llm_provider: "rules",
    llm_model: "sparta-rules",
    features: { simulator: true, personal_voice: false, llm_summaries: false, translation: false, raw_audio_storage: false },
    policy_version: "2026.11.1",
    language_pack_version: "en:1",
    languages: [
      { code: "en-IN", name: "English (India)", native_name: "English", status: "supported" },
      { code: "hi-IN", name: "Hindi", native_name: "हिन्दी", status: "supported" },
      { code: "kn-IN", name: "Kannada", native_name: "ಕನ್ನಡ", status: "supported" },
      { code: "ta-IN", name: "Tamil", native_name: "தமிழ்", status: "planned" },
    ],
    limits: { max_call_duration_s: 600, max_audio_bytes: 8_000_000, max_audio_seconds: 120, daily_call_cap: 200 },
    ...overrides,
  };
}

let seqCounter = 0;
export function makeEvent(type: string, data: Record<string, unknown> = {}, overrides: Partial<LiveEvent> = {}): LiveEvent {
  seqCounter += 1;
  return { type, call_id: "call_1", seq: seqCounter, ts: NOW_ISO, simulated: true, data, ...overrides };
}

export function resetEventSeq(to = 0): void {
  seqCounter = to;
}
