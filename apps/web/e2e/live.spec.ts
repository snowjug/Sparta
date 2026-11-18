import type { WebSocketRoute } from "@playwright/test";
import { expect, test } from "./support/test";

const unavailable = {
  status: 503,
  contentType: "application/json",
  headers: { "access-control-allow-origin": "http://localhost:3100" },
  body: JSON.stringify({ error: { code: "unavailable", message: "The live service is restarting.", trace_id: "trace-ticket-503", details: null } }),
};

test.describe("live index", () => {
  test("shows an honest empty state, then lists the call in progress", async ({ page, api }) => {
    await page.goto("/live");
    await expect(page.getByRole("heading", { name: "No call is active right now" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Start a simulated call" })).toBeVisible();

    const call = await api.startCall();
    await page.goto("/live");
    const row = page.getByTestId("active-calls").getByTestId("call-row");
    await expect(row).toHaveCount(1);
    await expect(row).toContainText("Simulated");
    await row.click();
    await expect(page).toHaveURL(new RegExp(`/live/${call.id}$`));
  });
});

test.describe("websocket resilience", () => {
  // The browser logs the failures the test injects on purpose.
  test.use({ allowedErrors: /status of 503|WebSocket/i });

  test("after a dropped connection the live view reconnects with a fresh ticket, with backoff, and fills the gap from the server", async ({ page, api }) => {
    const call = await api.startCall();
    await api.waitForSilence(call.id);

    const sockets: Array<{ ws: WebSocketRoute; server: WebSocketRoute }> = [];
    await page.routeWebSocket(/\/api\/v1\/live\//, (ws) => {
      sockets.push({ ws, server: ws.connectToServer() });
    });
    let blockTickets = false;
    await page.route("**/api/v1/live/ticket", (route) => (blockTickets ? route.fulfill(unavailable) : route.continue()));
    const ticketRequests: number[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith("/live/ticket")) ticketRequests.push(Date.now());
    });

    await page.goto(`/live/${call.id}`);
    const pill = page.getByTestId("connection-pill");
    await expect(pill).toHaveAttribute("data-connection", "open");
    expect(sockets).toHaveLength(1);
    expect(ticketRequests).toHaveLength(1);
    const turns = page.getByTestId("turn");
    await expect(turns).toHaveCount(1); // Sparta's introduction

    // The network drops, and the live service stays unreachable for a moment.
    blockTickets = true;
    await sockets[0]!.server.close();
    await sockets[0]!.ws.close({ code: 1011, reason: "network lost" });
    await expect(pill).toHaveAttribute("data-connection", "reconnecting");

    // Meanwhile the caller talks: these events are missed by the browser.
    await api.sendTurn(call.id, "Hello, I am calling from the bank about your account.");
    await expect.poll(() => ticketRequests.length, { timeout: 20_000 }).toBeGreaterThanOrEqual(4); // initial + three retries
    // The waits between the retries double (about 1 s, then 2 s, each +/- 20 % jitter), so the two ranges never overlap. The gap before the
    // first retry is not measured: it also contains the time the first connection stayed open.
    const retryGaps = [ticketRequests[2]! - ticketRequests[1]!, ticketRequests[3]! - ticketRequests[2]!];
    expect(retryGaps[0]!).toBeGreaterThan(700);
    expect(retryGaps[1]!).toBeGreaterThan(retryGaps[0]! * 1.2);

    // The live service is back: a new ticket, a new socket and a snapshot that contains the missed turns.
    blockTickets = false;
    await expect(pill).toHaveAttribute("data-connection", "open", { timeout: 30_000 });
    expect(sockets.length).toBeGreaterThanOrEqual(2);
    await expect(turns).toHaveCount(3);
    await expect(turns.nth(1)).toContainText("calling from the bank");
    await expect(turns.nth(1)).toHaveAttribute("data-speaker", "caller");

    // And live events flow again, without duplicates.
    await api.waitForSilence(call.id);
    await api.sendTurn(call.id, "Please confirm your date of birth.");
    await expect(turns).toHaveCount(5);
    await expect(turns.nth(3)).toContainText("date of birth");
  });

  test("a stream.resync from the server makes the client fetch the missed events; keep-alive pings are ignored", async ({ page, api }) => {
    const call = await api.startCall();
    await api.waitForSilence(call.id);
    const sockets: Array<{ ws: WebSocketRoute; server: WebSocketRoute }> = [];
    await page.routeWebSocket(/\/api\/v1\/live\//, (ws) => {
      sockets.push({ ws, server: ws.connectToServer() });
    });
    await page.goto(`/live/${call.id}`);
    await expect(page.getByTestId("connection-pill")).toHaveAttribute("data-connection", "open");
    const turns = page.getByTestId("turn");
    await expect(turns).toHaveCount(1);

    sockets[0]!.ws.send(JSON.stringify({ type: "ping" }));
    sockets[0]!.ws.send(JSON.stringify({ type: "ping" }));

    const eventsRequest = page.waitForRequest((request) => request.url().includes(`/calls/${call.id}/events`) && request.url().includes("after_seq="));
    sockets[0]!.ws.send(JSON.stringify({ type: "stream.resync", call_id: call.id, seq: 0, data: {} }));
    const request = await eventsRequest;
    expect(new URL(request.url()).searchParams.get("after_seq")).toMatch(/^\d+$/);

    // The model is unchanged (no duplicate turns) and the connection stays up.
    await expect(turns).toHaveCount(1);
    await expect(page.getByTestId("connection-pill")).toHaveAttribute("data-connection", "open");
    await page.locator("summary", { hasText: "Diagnostics" }).click();
    await expect(page.getByTestId("diagnostics")).toContainText("Resync requests");
  });
});

test.describe("escalation window", () => {
  test("when the owner does not answer within the window, Sparta takes a message and the live view says so", async ({ page, api }) => {
    test.setTimeout(120_000);
    const call = await api.seedEscalatedCall();
    await page.goto(`/live/${call.id}`);
    const banner = page.getByTestId("escalation-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/Sparta takes a message in about \d+s/);
    await expect(page.getByTestId("action-takeover")).toBeEnabled();
    await expect(page.getByTestId("escalation-resolved")).toContainText("You did not answer in time, so Sparta took a message.", { timeout: 60_000 });
    await expect(page.getByTestId("escalation-banner")).toHaveCount(0);
  });
});
