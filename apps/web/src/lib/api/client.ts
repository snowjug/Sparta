import { ApiError } from "./errors";
import type { ApiErrorDetail } from "./types";

export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  query?: Record<string, QueryValue>;
  /** JSON body (serialised with `Content-Type: application/json`). */
  body?: unknown;
  /** Multipart body; the browser sets the boundary. */
  form?: FormData;
  /** Sent as `Idempotency-Key` (<= 64 chars) so a retried create does not run twice. */
  idempotencyKey?: string;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export interface ApiClientOptions {
  baseUrl: string;
  getAuthHeaders?: () => Promise<Record<string, string>> | Record<string, string>;
  fetchImpl?: typeof fetch;
  onUnauthorized?: (error: ApiError) => void;
  createRequestId?: () => string;
}

export interface Download {
  blob: Blob;
  filename: string | null;
}

export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `idem-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function defaultRequestId(): string {
  const bytes = new Uint8Array(8);
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    crypto.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  return `web-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

export function parseRetryAfter(value: string | null, now: number = Date.now()): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds)) return Math.max(0, Math.ceil(seconds));
  const at = Date.parse(value);
  if (Number.isNaN(at)) return null;
  return Math.max(0, Math.ceil((at - now) / 1000));
}

export function filenameFromDisposition(value: string | null): string | null {
  if (!value) return null;
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(value);
  if (star?.[1]) {
    try {
      return sanitizeFilename(decodeURIComponent(star[1].trim().replace(/^"|"$/g, "")));
    } catch {
      /* fall through to the plain filename */
    }
  }
  const plain = /filename\s*=\s*("([^"]+)"|[^;]+)/i.exec(value);
  const name = plain?.[2] ?? plain?.[1];
  return name ? sanitizeFilename(name.trim()) : null;
}

export function sanitizeFilename(name: string): string {
  const cleaned = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").replace(/^\.+/, "").slice(0, 120);
  return cleaned || "download";
}

interface FastApiValidationItem {
  loc?: unknown[];
  msg?: string;
}

function detailsFromFastApi(detail: unknown): { message: string | null; details: ApiErrorDetail[] | null } {
  if (typeof detail === "string") return { message: detail, details: null };
  if (Array.isArray(detail)) {
    const details = (detail as FastApiValidationItem[]).map((item) => ({
      field: Array.isArray(item.loc) ? item.loc.join(".") : "body",
      message: item.msg ?? "Invalid value",
    }));
    return { message: "The request was not valid.", details };
  }
  return { message: null, details: null };
}

export class ApiClient {
  private readonly options: ApiClientOptions;

  constructor(options: ApiClientOptions) {
    this.options = { ...options, baseUrl: options.baseUrl.replace(/\/+$/, "") };
  }

  get baseUrl(): string {
    return this.options.baseUrl;
  }

  url(path: string, query?: Record<string, QueryValue>): string {
    const url = new URL(`${this.options.baseUrl}/api/v1${path}`);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value === undefined || value === null || value === "") continue;
        url.searchParams.set(key, String(value));
      }
    }
    return url.toString();
  }

  /** Absolute URL for a non-versioned path such as `/healthz`. */
  rootUrl(path: string): string {
    return `${this.options.baseUrl}${path}`;
  }

  async request<T = void>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<T> {
    const response = await this.send(method, path, options);
    if (response.status === 204) return undefined as T;
    const text = await response.text();
    if (!text) return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch (cause) {
      throw new ApiError({
        status: response.status,
        code: "invalid_response",
        message: "The server sent a response that was not valid JSON.",
        requestId: response.headers.get("X-Request-ID"),
        method,
        path,
        cause,
      });
    }
  }

  async download(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<Download> {
    const response = await this.send(method, path, options, "*/*");
    const blob = await response.blob();
    return { blob, filename: filenameFromDisposition(response.headers.get("Content-Disposition")) };
  }

  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("GET", path, options);
  }

  post<T = void>(path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
    return this.request<T>("POST", path, { ...options, body: body ?? options.body });
  }

  put<T = void>(path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
    return this.request<T>("PUT", path, { ...options, body: body ?? options.body });
  }

  delete<T = void>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>("DELETE", path, options);
  }

  private async send(method: HttpMethod, path: string, options: RequestOptions, accept = "application/json"): Promise<Response> {
    const requestId = (this.options.createRequestId ?? defaultRequestId)();
    const headers: Record<string, string> = {
      Accept: accept,
      "X-Request-ID": requestId,
      ...(await this.authHeaders()),
      ...options.headers,
    };
    let body: BodyInit | undefined;
    if (options.form) {
      body = options.form;
    } else if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

    const doFetch = this.options.fetchImpl ?? ((input: RequestInfo | URL, init?: RequestInit) => fetch(input, init));
    let response: Response;
    try {
      response = await doFetch(this.url(path, options.query), {
        method,
        headers,
        body,
        signal: options.signal,
        credentials: "omit",
        cache: "no-store",
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") {
        throw new ApiError({ status: 0, code: "aborted", message: "The request was cancelled.", requestId, method, path, cause });
      }
      throw new ApiError({
        status: 0,
        code: "network_error",
        message: `Cannot reach the Sparta API at ${this.options.baseUrl}. Check that it is running and that this site's origin is allowed (CORS).`,
        requestId,
        method,
        path,
        cause,
      });
    }
    if (response.ok) return response;
    const error = await this.toApiError(response, method, path, requestId);
    if (error.status === 401) this.options.onUnauthorized?.(error);
    throw error;
  }

  private async authHeaders(): Promise<Record<string, string>> {
    const provider = this.options.getAuthHeaders;
    return provider ? await provider() : {};
  }

  private async toApiError(response: Response, method: string, path: string, requestId: string): Promise<ApiError> {
    const text = await response.text().catch(() => "");
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = null;
      }
    }
    const record = (parsed && typeof parsed === "object" ? parsed : {}) as Record<string, unknown>;
    const envelope = (record.error && typeof record.error === "object" ? record.error : null) as {
      code?: string;
      message?: string;
      trace_id?: string;
      details?: ApiErrorDetail[] | null;
    } | null;
    const fastApi = envelope ? { message: null, details: null } : detailsFromFastApi(record.detail);
    const echoed = response.headers.get("X-Request-ID");
    return new ApiError({
      status: response.status,
      code: envelope?.code ?? `http_${response.status}`,
      message: envelope?.message ?? fastApi.message ?? (response.statusText || "The request failed."),
      traceId: envelope?.trace_id ?? echoed,
      requestId: echoed ?? requestId,
      details: envelope?.details ?? fastApi.details,
      retryAfterS: parseRetryAfter(response.headers.get("Retry-After")),
      method,
      path,
    });
  }
}
