import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/errors";
import { backoffDelay, CLOSE, DEFAULT_BACKOFF, LiveConnection, type StatusInfo, type WebSocketLike } from "./socket";
import type { LiveEvent, LiveTicket } from "../api/types";
import type { ConnectionStatus } from "./reducer";

class FakeSocket implements WebSocketLike {
  static instances: FakeSocket[] = [];
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  closed: { code?: number; reason?: string } | null = null;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  send(data: unknown) {
    this.onmessage?.({ data: typeof data === "string" ? data : JSON.stringify(data) } as MessageEvent);
  }
  serverClose(code: number, reason = "") {
    this.readyState = 3;
    this.onclose?.({ code, reason } as CloseEvent);
  }
  close(code?: number, reason?: string) {
    this.closed = { code, reason };
    this.readyState = 3;
  }
}

const flush = async () => {
  await vi.advanceTimersByTimeAsync(0);
};

function setup(options: Partial<ConstructorParameters<typeof LiveConnection>[0]> = {}) {
  const statuses: Array<[ConnectionStatus, StatusInfo]> = [];
  const events: LiveEvent[] = [];
  let ticketCount = 0;
  const getTicket = vi.fn(async (): Promise<LiveTicket> => ({ ticket: `ticket-${++ticketCount}`, expires_in: 60, ws_url: "ignored" }));
  const connection = new LiveConnection({
    callId: "call_1",
    getTicket,
    wsBase: "ws://api.test",
    onEvent: (event) => events.push(event),
    onStatus: (status, info) => statuses.push([status, info]),
    createSocket: (url) => new FakeSocket(url),
    random: () => 0.5,
    ...options,
  });
  return { connection, statuses, events, getTicket };
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.instances = [];
});
afterEach(() => vi.useRealTimers());

describe("backoffDelay", () => {
  it("grows exponentially, stays capped, and spreads with jitter", () => {
    const delays = [0, 1, 2, 3, 4, 5, 6, 7].map((attempt) => backoffDelay(attempt, DEFAULT_BACKOFF, () => 0.5));
    expect(delays).toEqual([500, 1000, 2000, 4000, 8000, 15000, 15000, 15000]);
    expect(backoffDelay(1, DEFAULT_BACKOFF, () => 0)).toBeLessThan(backoffDelay(1, DEFAULT_BACKOFF, () => 1));
    expect(backoffDelay(30, DEFAULT_BACKOFF, () => 1)).toBeLessThanOrEqual(DEFAULT_BACKOFF.maxMs);
  });
});

describe("LiveConnection", () => {
  it("fetches a single-use ticket, builds the call URL from the trusted base and delivers events (filtering pings)", async () => {
    const { connection, statuses, events, getTicket } = setup();
    connection.start();
    await flush();
    expect(getTicket).toHaveBeenCalledWith("call_1");
    const socket = FakeSocket.instances[0]!;
    expect(socket.url).toBe("ws://api.test/api/v1/live/call_1?ticket=ticket-1");
    socket.open();
    socket.send('{"type":"ping"}');
    socket.send("garbage");
    socket.send({ type: "call.snapshot", call_id: "call_1", seq: 3, data: { call: {} } });
    expect(events).toHaveLength(1);
    expect(events[0]?.type).toBe("call.snapshot");
    expect(statuses.map(([status]) => status)).toEqual(["connecting", "open"]);
  });

  it("uses the all-calls endpoint without a call id", async () => {
    const { connection } = setup({ callId: null });
    connection.start();
    await flush();
    expect(FakeSocket.instances[0]!.url).toBe("ws://api.test/api/v1/live?ticket=ticket-1");
  });

  it("reconnects with exponential backoff and a fresh ticket each time, and resets after a successful open", async () => {
    const { connection, statuses, getTicket } = setup();
    connection.start();
    await flush();
    FakeSocket.instances[0]!.open();
    FakeSocket.instances[0]!.serverClose(1006);
    expect(statuses.at(-1)?.[0]).toBe("reconnecting");
    expect(statuses.at(-1)?.[1].nextDelayMs).toBe(500);

    await vi.advanceTimersByTimeAsync(499);
    expect(FakeSocket.instances).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(2);
    expect(FakeSocket.instances).toHaveLength(2);
    expect(FakeSocket.instances[1]!.url).toContain("ticket=ticket-2"); // tickets are single use

    // second drop before opening: the delay doubles
    FakeSocket.instances[1]!.serverClose(1006);
    expect(statuses.at(-1)?.[1].nextDelayMs).toBe(1000);
    await vi.advanceTimersByTimeAsync(1001);
    FakeSocket.instances[2]!.open();
    expect(statuses.at(-1)).toEqual(["open", { attempt: 0 }]);
    FakeSocket.instances[2]!.serverClose(1006);
    expect(statuses.at(-1)?.[1].nextDelayMs).toBe(500); // reset after a successful connection
    expect(getTicket).toHaveBeenCalledTimes(3);
  });

  it("asks for a new ticket immediately on 4401, but gives up on 4403 (origin) and 4404 (no such call)", async () => {
    const { connection, statuses } = setup();
    connection.start();
    await flush();
    FakeSocket.instances[0]!.serverClose(CLOSE.BAD_TICKET);
    await flush();
    expect(FakeSocket.instances).toHaveLength(2);
    FakeSocket.instances[1]!.serverClose(CLOSE.ORIGIN_NOT_ALLOWED, "origin");
    expect(statuses.at(-1)?.[0]).toBe("failed");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.instances).toHaveLength(2);

    const other = setup();
    other.connection.start();
    await flush();
    FakeSocket.instances.at(-1)!.serverClose(CLOSE.CALL_NOT_FOUND);
    expect(other.statuses.at(-1)?.[0]).toBe("failed");
  });

  it("waits the full backoff cap on 4429 (too many connections)", async () => {
    const { connection, statuses } = setup();
    connection.start();
    await flush();
    FakeSocket.instances[0]!.serverClose(CLOSE.TOO_MANY);
    expect(statuses.at(-1)?.[1].nextDelayMs).toBe(DEFAULT_BACKOFF.maxMs);
  });

  it("does not reconnect when told the call is over, and stop() closes the socket and cancels timers", async () => {
    let over = false;
    const ended = setup({ shouldReconnect: () => !over });
    ended.connection.start();
    await flush();
    over = true;
    FakeSocket.instances[0]!.serverClose(1000);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(ended.statuses.at(-1)?.[0]).toBe("closed");

    FakeSocket.instances = [];
    const stopped = setup();
    stopped.connection.start();
    await flush();
    const socket = FakeSocket.instances[0]!;
    socket.open();
    socket.serverClose(1006);
    stopped.connection.stop();
    await vi.advanceTimersByTimeAsync(30_000);
    expect(FakeSocket.instances).toHaveLength(1);
    expect(stopped.statuses.at(-1)?.[0]).toBe("closed");
  });

  it("retries when the ticket request fails on the network, but stops on 401", async () => {
    let calls = 0;
    const flaky = setup({
      getTicket: async () => {
        calls += 1;
        if (calls === 1) throw new ApiError({ status: 0, code: "network_error", message: "offline" });
        return { ticket: "t", expires_in: 60, ws_url: "" };
      },
    });
    flaky.connection.start();
    await flush();
    expect(flaky.statuses.at(-1)?.[0]).toBe("reconnecting");
    await vi.advanceTimersByTimeAsync(600);
    expect(FakeSocket.instances).toHaveLength(1);

    FakeSocket.instances = [];
    const denied = setup({
      getTicket: async () => {
        throw new ApiError({ status: 401, code: "unauthorized", message: "sign in" });
      },
    });
    denied.connection.start();
    await flush();
    expect(denied.statuses.at(-1)?.[0]).toBe("failed");
    expect(FakeSocket.instances).toHaveLength(0);
  });

  it("reconnectNow() skips the backoff wait", async () => {
    const { connection } = setup();
    connection.start();
    await flush();
    FakeSocket.instances[0]!.serverClose(1006);
    connection.reconnectNow();
    await flush();
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it("ignores frames from a socket that was replaced", async () => {
    const { connection, events } = setup();
    connection.start();
    await flush();
    const first = FakeSocket.instances[0]!;
    first.serverClose(1006);
    connection.reconnectNow();
    await flush();
    first.onmessage?.({ data: JSON.stringify({ type: "x", call_id: "c", seq: 1 }) } as MessageEvent);
    expect(events).toHaveLength(0);
  });
});
