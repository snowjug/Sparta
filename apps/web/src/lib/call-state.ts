import type { Tone } from "@/components/ui/badge";
import type { CallState, CallStatus } from "./api/enums";
import { stateLabel } from "./labels";

export const STEPPER_STEPS = ["Connect", "Intro", "Who", "Why", "Assess", "Outcome"] as const;

const PHASE: Record<CallState, number> = {
  INITIALIZING: 0,
  DISCLOSURE: 1,
  IDENTIFY_CALLER: 2,
  IDENTIFY_PURPOSE: 3,
  CLARIFY: 3,
  ASSESSING: 4,
  SAFE_CONTINUE: 4,
  ESCALATE: 5,
  REFUSE_SENSITIVE_REQUEST: 5,
  END_SPAM: 5,
  END_SILENCE: 5,
  OWNER_TAKEOVER: 5,
  COMPLETED: 5,
  FAILED: 5,
};

const OUTCOME_LABEL: Partial<Record<CallState, string>> = {
  ESCALATE: "Waiting for you",
  REFUSE_SENSITIVE_REQUEST: "Refusing",
  END_SPAM: "Ended: spam",
  END_SILENCE: "Ended: silence",
  OWNER_TAKEOVER: "You took over",
  COMPLETED: "Completed",
  FAILED: "Failed",
};

const TONES: Partial<Record<CallState, Tone>> = {
  ESCALATE: "warning",
  REFUSE_SENSITIVE_REQUEST: "warning",
  OWNER_TAKEOVER: "info",
  FAILED: "danger",
};

export interface StateModel {
  state: CallState | null;
  label: string;
  /** Index into STEPPER_STEPS of the current step. */
  step: number;
  /** Text for the last step (changes with the outcome). */
  outcomeLabel: string;
  /** True once the conversation has reached an end state (spam / silence / completed / failed). */
  finished: boolean;
  /** True when the owner is expected to act. */
  needsOwner: boolean;
  tone: Tone;
}

export function describeCallState(state: CallState | null | undefined, status?: CallStatus): StateModel {
  if (!state) {
    return { state: null, label: "Waiting", step: 0, outcomeLabel: "Outcome", finished: false, needsOwner: false, tone: "neutral" };
  }
  const known = state in PHASE;
  const finished =
    status === "ended" ||
    status === "failed" ||
    state === "COMPLETED" ||
    state === "FAILED" ||
    state === "END_SPAM" ||
    state === "END_SILENCE";
  return {
    state,
    label: stateLabel(state),
    step: known ? PHASE[state] : 0,
    outcomeLabel: OUTCOME_LABEL[state] ?? STEPPER_STEPS[5],
    finished,
    needsOwner: state === "ESCALATE",
    tone: TONES[state] ?? (finished ? "neutral" : "accent"),
  };
}

export function isEndState(state: CallState | null | undefined): boolean {
  return state === "COMPLETED" || state === "FAILED" || state === "END_SPAM" || state === "END_SILENCE";
}
