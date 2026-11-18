import { isApiError } from "../api/errors";
import type { LiveEvent, LiveTicket } from "../api/types";
import { isPing, parseFrame } from "./events";
import type { ConnectionStatus } from "./reducer";

export interface WebSocketLike {
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  close(code?: number, reason?: string): void;
}

export interface BackoffPolicy {
  baseMs: number;
  maxMs: number;
  factor: number;
  /** +/- fraction of random spread so many tabs do not reconnect in lock-step. */
  jitter: number;
}

export const DEFAULT_BACKOFF: BackoffPolicy = { baseMs: 500, maxMs: 15_000, factor: 2, jitter: 0.2 };

export function backoffDelay(attempt: number, policy: BackoffPolicy = DEFAULT_BACKOFF, random: () => number = Math.random): number {
  const exponential = Math.min(policy.maxMs, policy.baseMs * policy.factor ** Math.max(0, attempt));
  const spread = 1 - policy.jitter + 2 * policy.jitter * random();
  return Math.round(Math.min(policy.maxMs, exponential * spread));
}

/** WebSocket close codes the Sparta API uses (docs/API_CONTRACT.md). */
export const CLOSE = {
  BAD_TICKET: 4401,
  ORIGIN_NOT_ALLOWED: 4403,
  CALL_NOT_FOUND: 4404,
  TOO_MANY: 4429,
} as const;

export interface StatusInfo {
  attempt: number;
  code?: number;
  reason?: string;
  nextDelayMs?: number;
  error?: unknown;
}

export interface LiveConnectionOptions {
  callId: string | null;
  /** POST /live/ticket. A fresh single-use ticket is requested for every (re)connect. */
  getTicket: (callId: string | null) => Promise<LiveTicket>;
  /** ws:// or wss:// origin of the API. Never taken from the ticket response: one trusted origin only. */
  wsBase: string;
  onEvent: (event: LiveEvent) => void;
  onStatus: (status: ConnectionStatus, info: StatusInfo) => void;
  createSocket?: (url: string) => WebSocketLike;
  backoff?: BackoffPolicy;
  random?: () => number;
  /** Return false to stop reconnecting (for example once the call has ended). */
  shouldReconnect?: () => boolean;
}

const OPEN = 1;

/**
 * One live-event connection: single-use ticket -> WebSocket -> LiveEvent frames, with automatic reconnect and
 * exponential backoff. Gap filling (seq resume) lives above, in the reducer + hook, which own the event sequence.
 */
export class LiveConnection {
  private readonly options: LiveConnectionOptions;
  private socket: WebSocketLike | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private stopped = true;
  private generation = 0;
  private badTicketStreak = 0;

  constructor(options: LiveConnectionOptions) {
    this.options = options;
  }

  get isOpen(): boolean {
    return this.socket?.readyState === OPEN;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    this.attempt = 0;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.generation += 1;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.detach();
    this.options.onStatus("closed", { attempt: this.attempt });
  }

  /** Skip the backoff wait (for example when the browser comes back online or the owner taps Reconnect). */
  reconnectNow(): void {
    if (this.stopped) return;
    if (this.isOpen) return;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    void this.connect();
  }

  private detach(): void {
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
    try {
      socket.close(1000, "client closing");
    } catch {
      /* already closed */
    }
  }

  private url(ticket: string): string {
    const base = this.options.wsBase.replace(/\/+$/, "");
    const path = this.options.callId ? `/api/v1/live/${encodeURIComponent(this.options.callId)}` : "/api/v1/live";
    return `${base}${path}?ticket=${encodeURIComponent(ticket)}`;
  }

  private async connect(): Promise<void> {
    const generation = ++this.generation;
    this.options.onStatus(this.attempt === 0 ? "connecting" : "reconnecting", { attempt: this.attempt });
    let ticket: LiveTicket;
    try {
      ticket = await this.options.getTicket(this.options.callId);
    } catch (error) {
      if (generation !== this.generation || this.stopped) return;
      this.handleTicketFailure(error);
      return;
    }
    if (generation !== this.generation || this.stopped) return;

    let socket: WebSocketLike;
    try {
      socket = (this.options.createSocket ?? ((url) => new WebSocket(url) as unknown as WebSocketLike))(this.url(ticket.ticket));
    } catch (error) {
      this.scheduleRetry({ attempt: this.attempt, error });
      return;
    }
    this.socket = socket;

    socket.onopen = () => {
      if (generation !== this.generation) return;
      this.attempt = 0;
      this.badTicketStreak = 0;
      this.options.onStatus("open", { attempt: 0 });
    };
    socket.onmessage = (message) => {
      if (generation !== this.generation) return;
      const frame = parseFrame(message.data);
      if (!frame || isPing(frame)) return;
      this.options.onEvent(frame);
    };
    socket.onerror = () => {
      /* the close event that always follows carries the code; nothing to do here */
    };
    socket.onclose = (event) => {
      if (generation !== this.generation) return;
      this.socket = null;
      this.handleClose(event.code, event.reason);
    };
  }

  private handleTicketFailure(error: unknown): void {
    if (isApiError(error)) {
      if (error.status === 401 || error.status === 403 || error.status === 404) {
        this.fail({ attempt: this.attempt, error, reason: error.message });
        return;
      }
      if (error.kind === "rate_limited" && error.retryAfterS) {
        this.scheduleRetry({ attempt: this.attempt, error }, error.retryAfterS * 1000);
        return;
      }
    }
    this.scheduleRetry({ attempt: this.attempt, error });
  }

  private handleClose(code: number, reason: string): void {
    if (this.stopped) return;
    if (code === CLOSE.ORIGIN_NOT_ALLOWED || code === CLOSE.CALL_NOT_FOUND) {
      this.fail({ attempt: this.attempt, code, reason });
      return;
    }
    if (this.options.shouldReconnect && !this.options.shouldReconnect()) {
      this.stopped = true;
      this.options.onStatus("closed", { attempt: this.attempt, code, reason });
      return;
    }
    if (code === CLOSE.BAD_TICKET && this.badTicketStreak < 2) {
      // Expired or already used: a fresh ticket right away, without backoff (but only twice in a row).
      this.badTicketStreak += 1;
      this.attempt += 1;
      void this.connect();
      return;
    }
    this.scheduleRetry({ attempt: this.attempt, code, reason }, code === CLOSE.TOO_MANY ? this.options.backoff?.maxMs ?? DEFAULT_BACKOFF.maxMs : undefined);
  }

  private fail(info: StatusInfo): void {
    this.stopped = true;
    this.options.onStatus("failed", info);
  }

  private scheduleRetry(info: StatusInfo, forcedDelayMs?: number): void {
    if (this.stopped) return;
    const delay = forcedDelayMs ?? backoffDelay(this.attempt, this.options.backoff, this.options.random);
    this.attempt += 1;
    this.options.onStatus("reconnecting", { ...info, attempt: this.attempt, nextDelayMs: delay });
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.connect();
    }, delay);
  }
}
