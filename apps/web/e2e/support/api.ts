import type { APIRequestContext, APIResponse } from "@playwright/test";
import type { CallDetail, TurnResult } from "../../src/lib/api/types";

/** Texts of the curated simulator scenarios that the tests replay as typed turns (the server only plays them in real time when autoplay is on). */
export const SCENARIO_TURNS = {
  "bank-otp-en": [
    "Good afternoon, this is Rahul calling from State Bank of India. Your account has been flagged for suspicious activity.",
    "To secure it I just need the OTP that was sent to your phone. Please read it out now.",
  ],
  "delivery-legit": ["Hi, I am a delivery executive from Amazon. I have a parcel for you and I am at your gate."],
  "recruiter-callback": [
    "Hello, this is Priya from Northwind Careers. We received your application and would like to schedule an interview this week.",
    "Could you ask the owner to call me back on the number I am calling from?",
  ],
  "language-switch-journey": [
    "Hello, I am calling from the Mysuru Electricity Board about your connection.",
    "Dhyan se suniye, aapka bill pending hai aur connection kat sakta hai.",
    "Nimma bill pending ide sir, immediately pay maadbeku, illandre connection cut aagutte.",
    "Please tell me the OTP that you just received so that I can verify your account.",
  ],
} as const;

export type SeededScenario = keyof typeof SCENARIO_TURNS;

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    url: string,
    body: string,
  ) {
    super(`API ${status} ${url}: ${body.slice(0, 400)}`);
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const newKey = () => `e2e-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;

/**
 * The signed-in dev identity's view of the real API: used to seed data fast and to check what the UI did.
 *
 * A 5xx is never retried: it is a backend defect and fails the test. Only 429 (240 requests a minute per owner) is waited out, as
 * long as the API's `Retry-After` asks. Seeds let the assistant finish speaking before the next caller turn, because a turn that
 * arrives while it speaks is barge-in (correct product behaviour, but not what a seed wants).
 */
export class OwnerApi {
  constructor(readonly request: APIRequestContext) {}

  private async parse<T>(response: APIResponse): Promise<T> {
    if (!response.ok()) throw new ApiRequestError(response.status(), response.url(), await response.text());
    if (response.status() === 204) return undefined as T;
    return (await response.json()) as T;
  }

  private async send<T>(send: () => Promise<APIResponse>): Promise<T> {
    for (let attempt = 1; ; attempt += 1) {
      const response = await send();
      if (response.status() === 429 && attempt < 8) {
        const seconds = Number(response.headers()["retry-after"] ?? "1");
        await sleep(Math.min(15, Math.max(1, Number.isFinite(seconds) ? seconds : 1)) * 1000 + 200);
        continue;
      }
      return this.parse<T>(response);
    }
  }

  get<T>(path: string): Promise<T> {
    return this.send<T>(() => this.request.get(path));
  }

  post<T>(path: string, data: unknown = {}): Promise<T> {
    const headers = { "Idempotency-Key": newKey() };
    return this.send<T>(() => this.request.post(path, { data, headers }));
  }

  put<T>(path: string, data: unknown): Promise<T> {
    return this.send<T>(() => this.request.put(path, { data }));
  }

  /** Speaking rate 1.3 is the fastest the API allows: seeded calls and scripted journeys wait less for the simulated speech. */
  async useFastSpeech(): Promise<void> {
    const profile = await this.get<Record<string, unknown>>("assistant-profile");
    await this.put("assistant-profile", { ...profile, speaking_rate: 1.3 });
  }

  startCall(body: Record<string, unknown> = {}): Promise<CallDetail> {
    return this.post<CallDetail>("simulator/calls", { silence_timers: "off", ...body });
  }

  sendTurn(callId: string, text: string, extra: Record<string, unknown> = {}): Promise<TurnResult> {
    return this.post<TurnResult>(`calls/${callId}/turns`, { text, source: "typed", ...extra });
  }

  getCall(callId: string): Promise<CallDetail> {
    return this.get<CallDetail>(`calls/${callId}`);
  }

  endCall(callId: string): Promise<unknown> {
    return this.post(`calls/${callId}/end`);
  }

  /** Test hygiene: an owner may only have 5 active calls, so tests that share an owner close what they opened. Best effort. */
  async endActiveCalls(): Promise<void> {
    try {
      const active = await this.get<{ items: Array<{ id: string }> }>("calls?status=active&limit=20");
      for (const call of active.items) await this.endCall(call.id).catch(() => undefined);
    } catch {
      /* the owner may have deleted its data in the test */
    }
  }

  async waitForStatus(callId: string, status: CallDetail["status"], timeoutMs = 60_000): Promise<CallDetail> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const call = await this.getCall(callId);
      if (call.status === status) return call;
      if (Date.now() > deadline) throw new Error(`Call ${callId} did not reach status ${status} within ${timeoutMs} ms (now ${call.status}, ${call.state})`);
      await sleep(700);
    }
  }

  /** Waits until the assistant is silent (backend truth), like a caller who lets the assistant finish. */
  async waitForSilence(callId: string, timeoutMs = 30_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const call = await this.getCall(callId);
      if (!call.assistant_speaking || call.status !== "active") return;
      if (Date.now() > deadline) throw new Error(`The assistant was still speaking on ${callId} after ${timeoutMs} ms`);
      await sleep(600);
    }
  }

  /** Plays a curated scenario as typed turns, letting Sparta finish speaking before each one, and waits until the call is ended and summarised. */
  async seedCall(scenario: SeededScenario, { waitForEnd = true }: { waitForEnd?: boolean } = {}): Promise<CallDetail> {
    const call = await this.startCall({ scenario_id: scenario });
    for (const text of SCENARIO_TURNS[scenario]) {
      await this.waitForSilence(call.id);
      await this.sendTurn(call.id, text);
    }
    return waitForEnd ? this.waitForStatus(call.id, "ended") : this.getCall(call.id);
  }

  /** A short call the owner ended right away: cheap filler for pagination and counters. */
  async seedEndedCall(label?: string): Promise<CallDetail> {
    const call = await this.startCall(label ? { caller_label: label } : {});
    await this.endCall(call.id);
    return this.waitForStatus(call.id, "ended");
  }

  /**
   * Many short ended calls. An owner may have 5 active calls at once and an ended call counts as active until the assistant has
   * finished its sentence, so they are created in batches of four.
   */
  async seedEndedCalls(count: number): Promise<string[]> {
    const ids: string[] = [];
    while (ids.length < count) {
      const batch: string[] = [];
      for (let index = 0; index < Math.min(4, count - ids.length); index += 1) batch.push((await this.startCall()).id);
      for (const id of batch) await this.endCall(id);
      for (const id of batch) await this.waitForStatus(id, "ended");
      ids.push(...batch);
    }
    return ids;
  }

  /** `delivery-legit`: one caller turn makes Sparta escalate to the owner. The call stays active until the owner decides. */
  async seedEscalatedCall(): Promise<CallDetail> {
    const call = await this.startCall({ scenario_id: "delivery-legit" });
    await this.waitForSilence(call.id);
    await this.sendTurn(call.id, SCENARIO_TURNS["delivery-legit"][0]);
    await this.waitForSilence(call.id);
    return this.getCall(call.id);
  }
}
