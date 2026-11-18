import type { ApiErrorDetail } from "./types";

export type ErrorKind =
  | "network"
  | "validation"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "unsupported_by_provider"
  | "payload_too_large"
  | "unsupported_media"
  | "rate_limited"
  | "stt_unavailable"
  | "provider_unavailable"
  | "server"
  | "aborted"
  | "unknown";

export interface ApiErrorInit {
  status: number;
  code: string;
  message: string;
  traceId?: string | null;
  requestId?: string | null;
  details?: ApiErrorDetail[] | null;
  retryAfterS?: number | null;
  method?: string;
  path?: string;
  cause?: unknown;
}

/** An error returned by the Sparta API (`{error: {code, message, trace_id, details}}`) or a failure to reach it. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly traceId: string | null;
  readonly requestId: string | null;
  readonly details: ApiErrorDetail[] | null;
  readonly retryAfterS: number | null;
  readonly method: string | null;
  readonly path: string | null;

  constructor(init: ApiErrorInit) {
    super(init.message, init.cause === undefined ? undefined : { cause: init.cause });
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code;
    this.traceId = init.traceId ?? null;
    this.requestId = init.requestId ?? null;
    this.details = init.details ?? null;
    this.retryAfterS = init.retryAfterS ?? null;
    this.method = init.method ?? null;
    this.path = init.path ?? null;
  }

  get kind(): ErrorKind {
    return kindFor(this.code, this.status);
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

export function kindFor(code: string, status: number): ErrorKind {
  switch (code) {
    case "network_error":
      return "network";
    case "aborted":
      return "aborted";
    case "validation_error":
      return "validation";
    case "unauthorized":
      return "unauthorized";
    case "forbidden":
      return "forbidden";
    case "not_found":
      return "not_found";
    case "conflict":
      return "conflict";
    case "unsupported_by_provider":
      return "unsupported_by_provider";
    case "payload_too_large":
      return "payload_too_large";
    case "unsupported_media_type":
      return "unsupported_media";
    case "rate_limited":
      return "rate_limited";
    case "stt_unavailable":
      return "stt_unavailable";
    case "provider_unavailable":
      return "provider_unavailable";
    default:
      break;
  }
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 409) return "conflict";
  if (status === 413) return "payload_too_large";
  if (status === 415) return "unsupported_media";
  if (status === 422) return "validation";
  if (status === 429) return "rate_limited";
  if (status === 503) return "provider_unavailable";
  if (status >= 500) return "server";
  return "unknown";
}

export interface ErrorDescription {
  kind: ErrorKind;
  title: string;
  message: string;
  code: string;
  status: number | null;
  traceId: string | null;
  requestId: string | null;
  retryAfterS: number | null;
  details: ApiErrorDetail[];
  /** Safe-to-share diagnostic text (no content, no numbers). */
  diagnostic: string;
  retryable: boolean;
}

const TITLES: Record<ErrorKind, string> = {
  network: "Can't reach Sparta",
  validation: "Check the highlighted details",
  unauthorized: "You're not signed in",
  forbidden: "Not allowed",
  not_found: "Not found",
  conflict: "That conflicts with the current state",
  unsupported_by_provider: "Not supported by this telephony provider",
  payload_too_large: "That file or message is too large",
  unsupported_media: "Unsupported file type",
  rate_limited: "Too many requests",
  stt_unavailable: "Speech recognition isn't available here",
  provider_unavailable: "A provider is unavailable",
  server: "Something went wrong on our side",
  aborted: "Request cancelled",
  unknown: "Something went wrong",
};

const STT_EXPLANATION =
  "This server's speech recognizer is the built-in simulator, which cannot transcribe audio. " +
  "Type the words the caller said (a transcript hint) or ask the operator to configure Azure Speech.";

/** Turn any thrown value into something a toast or inline message can render accessibly. */
export function describeError(error: unknown, fallbackMessage = "Please try again."): ErrorDescription {
  if (isApiError(error)) {
    const kind = error.kind;
    let message = error.message || fallbackMessage;
    if (kind === "rate_limited") {
      message =
        error.retryAfterS && error.retryAfterS > 0
          ? `You're going too fast. Try again in ${error.retryAfterS} second${error.retryAfterS === 1 ? "" : "s"}.`
          : "You're going too fast. Wait a moment and try again.";
    } else if (kind === "stt_unavailable") {
      message = `${STT_EXPLANATION} (${error.message})`;
    } else if (kind === "network") {
      message = error.message;
    }
    const diagnostic = [
      `code: ${error.code}`,
      `status: ${error.status || "n/a"}`,
      error.traceId ? `trace_id: ${error.traceId}` : null,
      error.requestId ? `request_id: ${error.requestId}` : null,
      error.method && error.path ? `request: ${error.method} ${error.path}` : null,
      `time: ${new Date().toISOString()}`,
    ]
      .filter(Boolean)
      .join("\n");
    return {
      kind,
      title: TITLES[kind],
      message,
      code: error.code,
      status: error.status || null,
      traceId: error.traceId,
      requestId: error.requestId,
      retryAfterS: error.retryAfterS,
      details: error.details ?? [],
      diagnostic,
      retryable: kind === "network" || kind === "server" || kind === "provider_unavailable" || kind === "rate_limited",
    };
  }
  const message = error instanceof Error && error.message ? error.message : fallbackMessage;
  return {
    kind: "unknown",
    title: TITLES.unknown,
    message,
    code: "unknown",
    status: null,
    traceId: null,
    requestId: null,
    retryAfterS: null,
    details: [],
    diagnostic: `code: unknown\ntime: ${new Date().toISOString()}`,
    retryable: false,
  };
}

/**
 * Field-level messages keyed by the last path segment of `details[].field` (e.g. `body.takeover_number` -> `takeover_number`).
 * Some validation errors carry only a message (for example "Enter a valid phone number"): with a `fallbackField` that message is
 * shown next to the one field the form is about, instead of only in a toast.
 */
export function fieldErrors(error: unknown, fallbackField?: string): Record<string, string> {
  if (!isApiError(error)) return {};
  const out: Record<string, string> = {};
  for (const detail of error.details ?? []) {
    const key = detail.field.split(".").pop() ?? detail.field;
    out[key] ??= detail.message;
  }
  if (fallbackField && Object.keys(out).length === 0 && error.kind === "validation" && error.message) out[fallbackField] = error.message;
  return out;
}
