import type { CallState, CallStatus, Speaker } from "../api/enums";
import type {
  CallDetail,
  CallSummary,
  CallTurn,
  Escalation,
  LiveEvent,
  OwnerAction,
  RiskAssessment,
  TurnResult,
} from "../api/types";

export type ConnectionStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed" | "failed";

export interface AssistantSpeech {
  turnId: string;
  text: string;
  locale: string;
  voiceId: string | null;
  estDurationMs: number;
  /** Client clock (ms) when `assistant.speaking` arrived: the visualization measures progress from here. */
  startedAt: number;
}

export interface InterruptInfo {
  turnId: string;
  spokenFraction: number;
  interruptionMs: number;
  at: number;
}

export interface PartialInfo {
  speaker: Speaker;
  text: string;
  language: string | null;
  startedAt: number;
  updatedAt: number;
}

export interface ProviderErrorInfo {
  provider: string;
  stage: string;
  message: string;
  degraded: boolean;
  at: number;
}

export interface LanguageEventInfo {
  from: string;
  to: string;
  profile: string | null;
  confidence: number | null;
  at: number;
}

export const MAX_LOGGED_EVENTS = 500;
const MAX_PENDING = 400;

export interface LiveCallState {
  callId: string | null;
  call: CallDetail | null;
  turns: CallTurn[];
  partial: PartialInfo | null;
  state: CallState | null;
  status: CallStatus;
  risk: RiskAssessment | null;
  language: { code: string | null; profile: string | null; confidence: number | null };
  languageEvents: LanguageEventInfo[];
  assistant: { speaking: AssistantSpeech | null; lastFinishedTurnId: string | null; interrupted: InterruptInfo | null };
  listening: boolean;
  escalation: Escalation | null;
  ownerActions: OwnerAction[];
  summary: CallSummary | null;
  providerErrors: ProviderErrorInfo[];
  ended: { reason: string; durationMs: number | null; at: number } | null;
  simulated: boolean;
  /** Highest event seq applied. Events at or below it are duplicates and are ignored. */
  lastSeq: number;
  /** Set when a seq gap was seen or the server sent `stream.resync`: live events are held until the gap is filled. */
  gapAfterSeq: number | null;
  pending: LiveEvent[];
  resyncCount: number;
  hydrated: boolean;
  connection: ConnectionStatus;
  reconnectAttempt: number;
  events: LiveEvent[];
  eventCount: number;
}

export function initialLiveState(callId: string | null = null): LiveCallState {
  return {
    callId,
    call: null,
    turns: [],
    partial: null,
    state: null,
    status: "active",
    risk: null,
    language: { code: null, profile: null, confidence: null },
    languageEvents: [],
    assistant: { speaking: null, lastFinishedTurnId: null, interrupted: null },
    listening: false,
    escalation: null,
    ownerActions: [],
    summary: null,
    providerErrors: [],
    ended: null,
    simulated: false,
    lastSeq: 0,
    gapAfterSeq: null,
    pending: [],
    resyncCount: 0,
    hydrated: false,
    connection: "idle",
    reconnectAttempt: 0,
    events: [],
    eventCount: 0,
  };
}

export type LiveAction =
  | { type: "reset"; callId: string | null }
  | { type: "connection"; status: ConnectionStatus; attempt?: number }
  | { type: "event"; event: LiveEvent; at: number }
  /** Events fetched from GET /calls/{id}/events to fill a gap; applied in seq order, then held live events drain. */
  | { type: "backfill"; events: LiveEvent[]; at: number }
  /** A REST CallDetail (initial load, explicit refresh, or fallback after a failed backfill). Without `force` it is
   * ignored once the model was hydrated, because the WebSocket snapshot + events are newer than a slow REST reply. */
  | { type: "snapshot"; call: CallDetail; at: number; force?: boolean }
  /** The server's own record of the escalations and owner actions (REST), merged without touching anything else in the model. */
  | { type: "escalations"; escalations: Escalation[]; ownerActions: OwnerAction[] }
  | { type: "turn-result"; result: TurnResult; at: number };

function upsertTurn(turns: CallTurn[], turn: CallTurn): CallTurn[] {
  const index = turns.findIndex((existing) => existing.id === turn.id);
  const next = index === -1 ? [...turns, turn] : turns.map((existing, i) => (i === index ? turn : existing));
  return next.sort((a, b) => a.seq - b.seq);
}

/** The server marks the interrupted assistant turn on its side; the live model mirrors that so the transcript shows it at once. */
function markInterrupted(turns: CallTurn[], turnId: string, spokenFraction: number | null): CallTurn[] {
  if (!turnId || !turns.some((turn) => turn.id === turnId && turn.speaker === "assistant")) return turns;
  return turns.map((turn) =>
    turn.id === turnId && turn.speaker === "assistant" ? { ...turn, interrupted: true, spoken_fraction: spokenFraction ?? turn.spoken_fraction } : turn,
  );
}

function lastCallerLanguage(turns: CallTurn[]): { code: string | null; profile: string | null; confidence: number | null } | null {
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const turn = turns[i]!;
    if (turn.speaker === "caller" && turn.language) {
      return { code: turn.language, profile: turn.language_profile, confidence: turn.language_confidence };
    }
  }
  return null;
}

/**
 * Fallback for servers that do not report `assistant_speaking` in the snapshot: when the newest turn is an assistant turn
 * that is younger than its own estimated duration, treat it as still speaking, so the visualisation also works for someone
 * who opens the call a moment after it started. A later `assistant.finished` event always corrects a wrong guess.
 */
export function inferSpeaking(turns: ReadonlyArray<CallTurn>, now: number): AssistantSpeech | null {
  const last = turns[turns.length - 1];
  if (!last || last.speaker !== "assistant" || last.interrupted || !last.speech) return null;
  const estimate = last.speech.est_duration_ms;
  const created = Date.parse(last.created_at);
  if (!(estimate > 0) || Number.isNaN(created)) return null;
  const age = now - created;
  if (age < -2000 || age > estimate + 500) return null;
  return { turnId: last.id, text: last.speech.text, locale: last.speech.locale, voiceId: last.speech.voice_id, estDurationMs: estimate, startedAt: created };
}

/**
 * Newer servers report whether the assistant is mid-utterance (`assistant_speaking`, `speaking_turn_id`): the truth from the
 * live runtime. Returns `undefined` when an older server omits the fields, so callers fall back to {@link inferSpeaking}.
 * `serverNow` (the snapshot event's own timestamp) keeps the elapsed time free of client/server clock skew.
 */
export function speechFromCall(call: CallDetail, turns: ReadonlyArray<CallTurn>, at: number, serverNow?: number): AssistantSpeech | null | undefined {
  const flag: unknown = (call as { assistant_speaking?: unknown }).assistant_speaking;
  if (typeof flag !== "boolean") return undefined;
  if (!flag) return null;
  const turn = (call.speaking_turn_id ? turns.find((candidate) => candidate.id === call.speaking_turn_id) : undefined) ?? [...turns].reverse().find((candidate) => candidate.speaker === "assistant");
  if (!turn?.speech) return null;
  const estimate = Math.max(0, turn.speech.est_duration_ms);
  const created = Date.parse(turn.created_at);
  const elapsed = Number.isNaN(created) ? 0 : Math.min(Math.max(0, (serverNow ?? at) - created), estimate);
  return { turnId: turn.id, text: turn.speech.text, locale: turn.speech.locale, voiceId: turn.speech.voice_id, estDurationMs: estimate, startedAt: at - elapsed };
}

function currentEscalation(escalations: ReadonlyArray<Escalation>): Escalation | null {
  const open = [...escalations].reverse().find((e) => e.status === "requested");
  return open ?? escalations[escalations.length - 1] ?? null;
}

/**
 * The server does not announce how an escalation ended: when the owner does not answer in time it only reports
 * `state.changed` (ESCALATE -> SAFE_CONTINUE) and the message-taking turn. The model therefore calls an escalation stale once the
 * call has left ESCALATE while it still says "requested"; the REST detail carries the real status. Returns that escalation's id.
 */
export function staleEscalationId(state: LiveCallState): string | null {
  const escalation = state.escalation;
  if (!escalation || escalation.status !== "requested" || state.status !== "active") return null;
  return state.state !== null && state.state !== "ESCALATE" ? escalation.id : null;
}

function hydrateFromCall(state: LiveCallState, call: CallDetail, at: number, serverNow?: number): LiveCallState {
  const turns = [...call.turns].sort((a, b) => a.seq - b.seq);
  const language = lastCallerLanguage(turns) ?? state.language;
  const finished = call.status !== "active";
  const reported = finished ? null : speechFromCall(call, turns, at, serverNow);
  const speaking = reported !== undefined ? reported : (inferSpeaking(turns, at) ?? state.assistant.speaking);
  return {
    ...state,
    callId: call.id,
    call,
    turns,
    state: call.state,
    status: call.status,
    risk: call.risk ?? state.risk,
    language: call.risk?.language_profile && !language.profile ? { ...language, profile: call.risk.language_profile } : language,
    escalation: currentEscalation(call.escalations) ?? state.escalation,
    ownerActions: call.owner_actions,
    summary: call.summary,
    simulated: call.simulated,
    partial: null,
    assistant: { ...state.assistant, speaking },
    hydrated: true,
  };
}

function logEvent(state: LiveCallState, event: LiveEvent): LiveCallState {
  const slim: LiveEvent =
    event.type === "call.snapshot"
      ? {
          ...event,
          data: {
            call: {
              id: (event.data as { call?: { id?: string } }).call?.id,
              state: (event.data as { call?: { state?: string } }).call?.state,
              turns: (event.data as { call?: { turns?: unknown[] } }).call?.turns?.length ?? 0,
            },
          },
        }
      : event;
  const events = state.events.length >= MAX_LOGGED_EVENTS ? [...state.events.slice(1), slim] : [...state.events, slim];
  return { ...state, events, eventCount: state.eventCount + 1 };
}

/**
 * Safety net: current servers always send `assistant.finished` before the caller's next final transcript once the estimated
 * speech time has elapsed, but older ones could skip it. Caller speech arriving after the utterance's own estimated duration
 * therefore also settles the assistant here. Caller speech that arrives earlier is barge-in, which the server reports with
 * `assistant.interrupted`.
 */
function settleSpeaking(assistant: LiveCallState["assistant"], at: number): LiveCallState["assistant"] {
  const speaking = assistant.speaking;
  if (!speaking || at - speaking.startedAt < speaking.estDurationMs) return assistant;
  return { ...assistant, speaking: null, lastFinishedTurnId: speaking.turnId };
}

/** Effect of one event on the call model. Pure: the same event applied twice yields the same model. */
function applyEffect(state: LiveCallState, event: LiveEvent, at: number): LiveCallState {
  const data = event.data as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  switch (event.type) {
    case "call.snapshot": {
      const call = data.call as CallDetail | undefined;
      const serverNow = Date.parse(event.ts);
      return call ? hydrateFromCall(state, call, at, Number.isNaN(serverNow) ? undefined : serverNow) : state;
    }
    case "call.connected":
      return { ...state, state: (data.state as CallState) ?? state.state, status: "active", simulated: event.simulated || state.simulated };
    case "call.listening":
      return { ...state, listening: true };
    case "state.changed":
      return typeof data.to === "string" ? { ...state, state: data.to as CallState } : state;
    case "transcript.partial": {
      if (typeof data.text !== "string") return state;
      const speaker = (data.speaker as Speaker) ?? "caller";
      const continuing = state.partial && state.partial.speaker === speaker;
      return {
        ...state,
        listening: false,
        partial: {
          speaker,
          text: data.text,
          language: typeof data.language === "string" ? data.language : null,
          startedAt: continuing ? state.partial!.startedAt : at,
          updatedAt: at,
        },
        assistant: speaker === "caller" ? settleSpeaking(state.assistant, at) : state.assistant,
      };
    }
    case "transcript.final": {
      const turn = data.turn as CallTurn | undefined;
      if (!turn || typeof turn.id !== "string") return state;
      const turns = upsertTurn(state.turns, turn);
      const callerLanguage = turn.speaker === "caller" && turn.language ? { code: turn.language, profile: turn.language_profile, confidence: turn.language_confidence } : null;
      return {
        ...state,
        turns,
        partial: state.partial && state.partial.speaker === turn.speaker ? null : state.partial,
        language: callerLanguage ?? state.language,
        assistant: turn.speaker === "caller" ? settleSpeaking(state.assistant, at) : state.assistant,
      };
    }
    case "language.changed": {
      if (typeof data.to !== "string") return state;
      const info: LanguageEventInfo = {
        from: String(data.from ?? ""),
        to: data.to,
        profile: typeof data.profile === "string" ? data.profile : null,
        confidence: typeof data.confidence === "number" ? data.confidence : null,
        at,
      };
      return {
        ...state,
        language: { code: info.to, profile: info.profile, confidence: info.confidence },
        languageEvents: [...state.languageEvents, info].slice(-20),
      };
    }
    case "risk.updated":
      return data.risk ? { ...state, risk: data.risk as RiskAssessment } : state;
    case "assistant.speaking": {
      if (typeof data.turn_id !== "string") return state;
      return {
        ...state,
        listening: false,
        partial: null,
        assistant: {
          ...state.assistant,
          interrupted: null,
          speaking: {
            turnId: data.turn_id,
            text: typeof data.text === "string" ? data.text : "",
            locale: typeof data.locale === "string" ? data.locale : "",
            voiceId: typeof data.voice_id === "string" ? data.voice_id : null,
            estDurationMs: typeof data.est_duration_ms === "number" ? Math.max(0, data.est_duration_ms) : 0,
            startedAt: at,
          },
        },
      };
    }
    case "assistant.finished": {
      const matches = !state.assistant.speaking || state.assistant.speaking.turnId === data.turn_id;
      return {
        ...state,
        assistant: {
          ...state.assistant,
          speaking: matches ? null : state.assistant.speaking,
          lastFinishedTurnId: typeof data.turn_id === "string" ? data.turn_id : state.assistant.lastFinishedTurnId,
        },
      };
    }
    case "assistant.interrupted": {
      const turnId = String(data.turn_id ?? "");
      const spokenFraction = typeof data.spoken_fraction === "number" ? data.spoken_fraction : null;
      return {
        ...state,
        turns: markInterrupted(state.turns, turnId, spokenFraction),
        assistant: {
          ...state.assistant,
          speaking: null,
          interrupted: {
            turnId,
            spokenFraction: spokenFraction ?? 0,
            interruptionMs: typeof data.interruption_ms === "number" ? data.interruption_ms : 0,
            at,
          },
        },
      };
    }
    case "escalation.requested":
      return {
        ...state,
        escalation: (data.escalation as Escalation) ?? state.escalation,
        risk: (data.risk as RiskAssessment) ?? state.risk,
      };
    case "owner.takeover":
    case "owner.action": {
      const action = data.action as OwnerAction | undefined;
      if (!action) return state;
      const ownerActions = state.ownerActions.some((existing) => existing.id === action.id) ? state.ownerActions : [...state.ownerActions, action];
      let escalation = state.escalation;
      if (escalation && escalation.status === "requested") {
        const status = action.action === "takeover" ? "taken_over" : action.action === "continue" ? "continued" : action.action === "end" ? "ended" : null;
        if (status) escalation = { ...escalation, status, resolved_at: action.created_at };
      }
      return { ...state, ownerActions, escalation };
    }
    case "call.ended": {
      const endState = (typeof data.state === "string" ? data.state : state.state) as CallState | null;
      return {
        ...state,
        state: endState,
        status: endState === "FAILED" ? "failed" : "ended",
        listening: false,
        partial: null,
        assistant: { ...state.assistant, speaking: null },
        ended: { reason: String(data.reason ?? ""), durationMs: typeof data.duration_ms === "number" ? data.duration_ms : null, at },
      };
    }
    case "summary.created":
      return data.summary ? { ...state, summary: data.summary as CallSummary } : state;
    case "provider.error":
      return {
        ...state,
        providerErrors: [
          ...state.providerErrors,
          {
            provider: String(data.provider ?? "provider"),
            stage: String(data.stage ?? ""),
            message: String(data.message ?? ""),
            degraded: data.degraded === true,
            at,
          },
        ].slice(-20),
      };
    default:
      return state;
  }
}

function applyOrdered(state: LiveCallState, event: LiveEvent, at: number): LiveCallState {
  const withEffect = applyEffect(state, event, at);
  return logEvent({ ...withEffect, lastSeq: Math.max(withEffect.lastSeq, event.seq) }, event);
}

function handleLive(state: LiveCallState, event: LiveEvent, at: number): LiveCallState {
  if (event.type === "stream.resync") {
    return logEvent({ ...state, gapAfterSeq: state.gapAfterSeq ?? state.lastSeq, resyncCount: state.resyncCount + 1 }, event);
  }
  if (event.type === "call.snapshot") {
    // A (re)connect starts with a full snapshot, so it is authoritative for the model. Held events newer than the
    // snapshot stay queued and the hook still backfills the log from `lastSeq`.
    const applied = applyOrdered(state, event, at);
    return applied;
  }
  if (event.seq > 0 && event.seq <= state.lastSeq && state.gapAfterSeq === null) return state;
  if (state.gapAfterSeq !== null) {
    if (state.pending.some((held) => held.seq === event.seq && held.type === event.type)) return state;
    return { ...state, pending: [...state.pending, event].slice(-MAX_PENDING) };
  }
  if (event.seq > 0 && state.lastSeq > 0 && event.seq > state.lastSeq + 1) {
    return { ...state, gapAfterSeq: state.lastSeq, pending: [event] };
  }
  return applyOrdered(state, event, at);
}

export function liveReducer(state: LiveCallState, action: LiveAction): LiveCallState {
  switch (action.type) {
    case "reset":
      return initialLiveState(action.callId);
    case "connection":
      return { ...state, connection: action.status, reconnectAttempt: action.attempt ?? (action.status === "open" ? 0 : state.reconnectAttempt) };
    case "event":
      return handleLive(state, action.event, action.at);
    case "backfill": {
      const known = new Set(state.events.map((event) => `${event.seq}:${event.type}`));
      const ordered = [...action.events].sort((a, b) => a.seq - b.seq);
      let next = state;
      for (const event of ordered) {
        if (event.seq <= next.lastSeq) {
          // Seen already (the model has it) but a gap-fill may still contribute to the event log.
          if (!known.has(`${event.seq}:${event.type}`)) next = logEvent(next, event);
          continue;
        }
        next = applyOrdered(next, event, action.at);
      }
      const held = [...next.pending].sort((a, b) => a.seq - b.seq);
      next = { ...next, pending: [], gapAfterSeq: null };
      for (const event of held) {
        if (event.seq <= next.lastSeq) continue;
        next = applyOrdered(next, event, action.at);
      }
      return next;
    }
    case "snapshot": {
      if (state.hydrated && !action.force) return state;
      const hydrated = hydrateFromCall(state, action.call, action.at);
      // The REST snapshot replaces the model; held live events are re-applied idempotently on top of it.
      const held = [...state.pending].sort((a, b) => a.seq - b.seq);
      let next: LiveCallState = { ...hydrated, pending: [], gapAfterSeq: null };
      for (const event of held) next = applyOrdered(next, event, action.at);
      return next;
    }
    case "escalations": {
      const latest = currentEscalation(action.escalations);
      const known = new Set(state.ownerActions.map((existing) => existing.id));
      const ownerActions = [...state.ownerActions, ...action.ownerActions.filter((existing) => !known.has(existing.id))];
      // An escalation never goes back to "requested": a late reply cannot undo what an event already resolved.
      const regress = latest && state.escalation && latest.id === state.escalation.id && state.escalation.status !== "requested" && latest.status === "requested";
      return { ...state, ownerActions, escalation: latest && !regress ? latest : state.escalation };
    }
    case "turn-result": {
      const { result } = action;
      let turns = state.turns;
      if (result.caller_turn) turns = upsertTurn(turns, result.caller_turn);
      if (result.assistant_turn) turns = upsertTurn(turns, result.assistant_turn);
      // A caller turn that arrived while the assistant was speaking interrupted that sentence.
      if (result.interrupted_turn_id) turns = markInterrupted(turns, result.interrupted_turn_id, null);
      return {
        ...state,
        turns,
        risk: result.risk ?? state.risk,
        state: result.state,
        status: result.ended ? (result.state === "FAILED" ? "failed" : "ended") : state.status,
        escalation: result.escalation ?? state.escalation,
        partial: null,
      };
    }
    default:
      return state;
  }
}
