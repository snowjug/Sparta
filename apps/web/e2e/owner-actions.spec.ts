import { expect, test } from "./support/test";
import { MASK_CHARS, notifications, openDialog } from "./support/ui";

// Owner controls, honesty about the provider, block/trust and deletion, all against the real backend.

test.describe("escalated call (delivery-legit): take over, continue, end", () => {
  test("take over is an honest simulation, moves the call to owner takeover and the owner can end it", async ({ page, api }) => {
    const call = await api.seedEscalatedCall();
    await page.goto(`/live/${call.id}`);

    await expect(page.getByTestId("connection-pill")).toHaveAttribute("data-connection", "open");
    await expect(page.getByTestId("escalation-banner")).toContainText("Delivery coordination");
    await expect(page.getByTestId("takeover-note")).toContainText("Takeover is simulated: no real phone call is being bridged.");
    await expect(page.getByTestId("audio-note")).toContainText("no cellular audio");
    await expect(page.getByTestId("action-takeover")).toBeEnabled();
    await expect(page.getByTestId("action-continue")).toBeEnabled();

    await page.getByTestId("action-takeover").click();
    await expect(notifications(page)).toContainText("Takeover simulated: no real phone call was bridged to you.");
    await expect(page.getByTestId("live-call")).toHaveAttribute("data-state", "OWNER_TAKEOVER");
    await expect(page.getByTestId("escalation-resolved")).toContainText("You took over this call.");
    expect((await api.getCall(call.id)).state).toBe("OWNER_TAKEOVER");

    await page.getByTestId("action-end").click();
    const dialog = openDialog(page, "End this call?");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "End call" }).click();
    await expect(page.getByTestId("live-call")).toHaveAttribute("data-status", "ended");
    await expect(page.getByTestId("action-takeover")).toBeDisabled();
    await expect(page.getByTestId("action-end")).toBeDisabled();
    await expect(page.getByTestId("live-summary")).toBeVisible({ timeout: 15_000 });
  });

  test("let Sparta continue: Sparta keeps screening and new turns arrive over the websocket without a reload", async ({ page, api }) => {
    const call = await api.seedEscalatedCall();
    await page.goto(`/live/${call.id}`);
    await expect(page.getByTestId("connection-pill")).toHaveAttribute("data-connection", "open");
    const turns = page.getByTestId("turn");

    await page.getByTestId("action-continue").click();
    await expect(page.getByTestId("escalation-resolved")).toContainText("You asked Sparta to continue handling this call.");
    await expect(page.getByTestId("live-call")).not.toHaveAttribute("data-state", "ESCALATE");
    await expect(notifications(page)).toContainText("Sparta will keep handling this call.");
    // Sparta thanks the caller for holding, then waits for them.
    await expect(turns.last()).toContainText("Thanks for holding");
    await api.waitForSilence(call.id);
    const before = await turns.count();

    // The caller keeps talking: the transcript grows by the caller turn and Sparta's reply, pushed by the server.
    await api.sendTurn(call.id, "The apartment is 402, right? Could someone come down to collect it?");
    await expect(turns).toHaveCount(before + 2);
    await expect(turns.nth(before)).toContainText("apartment is 402");
    await expect(turns.nth(before)).toHaveAttribute("data-speaker", "caller");
    await expect(turns.nth(before + 1)).toHaveAttribute("data-speaker", "assistant");
  });
});

test.describe("provider capabilities are honest", () => {
  // The browser logs the 409 it receives; the test provokes it on purpose.
  test.use({ allowedErrors: /status of 409/ });

  test("a provider that cannot do it answers 409 unsupported_by_provider: the message is shown and nothing is reported as done", async ({ page, api }) => {
    const call = await api.seedEscalatedCall();
    await page.route("**/api/v1/calls/*/takeover", (route) =>
      route.fulfill({
        status: 409,
        contentType: "application/json",
        headers: { "access-control-allow-origin": "http://localhost:3100", "x-request-id": "req-unsupported-1" },
        body: JSON.stringify({ error: { code: "unsupported_by_provider", message: "The active telephony provider cannot bridge a call to the owner.", trace_id: "trace-unsupported-1", details: null } }),
      }),
    );
    await page.goto(`/live/${call.id}`);
    await page.getByTestId("action-takeover").click();

    await expect(page.getByTestId("unsupported-note")).toContainText("The active telephony provider cannot bridge a call to the owner.");
    await expect(page.getByTestId("unsupported-note")).toContainText("Not done.");
    await expect(notifications(page).getByText(/Takeover simulated|You took over/)).toHaveCount(0);
    await expect(page.getByTestId("live-call")).toHaveAttribute("data-state", "ESCALATE");
    expect((await api.getCall(call.id)).state).toBe("ESCALATE");
  });
});

test.describe("block and trust", () => {
  test("blocking a caller from the call page shows only the masked number in the Safety Center, and unblocking works", async ({ page, api }) => {
    const call = await api.seedCall("bank-otp-en");
    await page.goto(`/calls/${call.id}`);
    await page.getByTestId("block-caller").click();
    await expect(notifications(page)).toContainText("Caller blocked");

    await page.goto("/safety");
    const item = page.getByTestId("blocked-item");
    await expect(item).toHaveCount(1);
    await expect(item).toContainText(MASK_CHARS);
    await expect(page.getByTestId("blocked-card")).not.toContainText("9800000101");
    await item.getByRole("button", { name: /^Remove/ }).click();
    await expect(page.getByText("You have not blocked anyone.")).toBeVisible();
    expect(await api.get<unknown[]>("blocked-callers")).toHaveLength(0);
  });

  test("trusting a caller from the call page, then removing the trust in the Safety Center", async ({ page, api }) => {
    const call = await api.seedCall("recruiter-callback", { waitForEnd: false });
    await api.endCall(call.id);
    await api.waitForStatus(call.id, "ended");
    await page.goto(`/calls/${call.id}`);
    await page.getByTestId("trust-caller").click();
    await expect(notifications(page)).toContainText("Caller trusted");

    await page.goto("/safety");
    const item = page.getByTestId("trusted-item");
    await expect(item).toHaveCount(1);
    await expect(item).toContainText(MASK_CHARS);
    await item.getByRole("button", { name: /^Remove/ }).click();
    await expect(page.getByText("You have not trusted anyone yet.")).toBeVisible();
  });

  test("the only place a raw number is typed is the block form, and it is only ever shown masked afterwards", async ({ page, api }) => {
    await page.goto("/safety");
    const card = page.getByTestId("blocked-card");
    await card.getByLabel("Phone number").fill("+91 98765 43210");
    await card.getByLabel("Reason (optional)").fill("Spam about loans");
    await card.getByRole("button", { name: "Block number" }).click();
    await expect(notifications(page)).toContainText("Caller blocked");
    const item = card.getByTestId("blocked-item");
    await expect(item).toHaveCount(1);
    await expect(item).toContainText("Spam about loans");
    await expect(card).not.toContainText("98765 43210");
    await expect(card).not.toContainText("9876543210");
    const [entry] = await api.get<Array<{ number_display: string }>>("blocked-callers");
    expect(entry?.number_display).toMatch(MASK_CHARS);
  });
});

test.describe("deleting call data", () => {
  test("delete content keeps the record but removes the transcript; delete call removes it from history", async ({ page, api }) => {
    const call = await api.seedCall("bank-otp-en");
    await page.goto(`/calls/${call.id}`);
    await expect(page.getByTestId("turn").first()).toBeVisible();

    await page.getByTestId("delete-content").click();
    const content = openDialog(page, /Delete this call's content\?/);
    await expect(content).toBeVisible();
    await content.getByRole("button", { name: "Cancel" }).click();
    await expect(content).toBeHidden();
    expect((await api.getCall(call.id)).has_content).toBe(true);

    await page.getByTestId("delete-content").click();
    await openDialog(page, /Delete this call's content\?/).getByRole("button", { name: "Delete content" }).click();
    await expect(notifications(page)).toContainText(/content (was )?deleted|Content deleted/i);
    await expect(page.getByTestId("turn")).toHaveCount(0);
    const after = await api.getCall(call.id);
    expect(after.has_content).toBe(false);
    expect(after.turns).toHaveLength(0);

    await page.getByTestId("delete-call").click();
    await openDialog(page, /Delete this call completely\?/).getByRole("button", { name: "Delete call" }).click();
    await expect(page).toHaveURL(/\/calls$/);
    await expect(page.locator(`[data-testid="history-row"][data-call-id="${call.id}"]`)).toHaveCount(0);
    const gone = await api.request.get(`calls/${call.id}`);
    expect(gone.status()).toBe(404);
  });

  test("an active call cannot be deleted", async ({ page, api }) => {
    const call = await api.seedEscalatedCall();
    await page.goto(`/calls/${call.id}`);
    await expect(page.getByTestId("delete-content")).toBeDisabled();
    await expect(page.getByTestId("delete-call")).toBeDisabled();
  });

  test("delete all call content from the Safety Center asks first, then empties history", async ({ page, api }) => {
    await api.seedCall("bank-otp-en");
    await page.goto("/safety");
    await page.getByTestId("delete-all-content").click();
    const dialog = openDialog(page, /Delete all call content\?/);
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Cancel" }).click();
    expect(await api.get<{ items: unknown[] }>("calls?limit=5").then((page) => page.items.length)).toBe(1);

    await page.getByTestId("delete-all-content").click();
    const confirm = openDialog(page, /Delete all call content\?/);
    await expect(confirm.getByRole("button", { name: "Delete everything" })).toBeDisabled();
    await confirm.getByLabel(/Type .delete. to confirm/).fill("delete");
    await confirm.getByRole("button", { name: "Delete everything" }).click();
    await expect(notifications(page)).toContainText("All your call content was deleted.");
    const remaining = await api.get<{ items: Array<{ has_content: boolean }> }>("calls?limit=5");
    expect(remaining.items.every((item) => !item.has_content)).toBe(true);
  });
});

test.describe("feedback", () => {
  test("the owner can give each kind of feedback once and it is stored with the call", async ({ page, api }) => {
    const call = await api.seedCall("bank-otp-en");
    await page.goto(`/calls/${call.id}`);
    for (const kind of ["correct_classification", "wrong_summary"] as const) {
      await page.getByTestId(`feedback-${kind}`).click();
      await expect(page.getByTestId(`feedback-${kind}`)).toHaveAttribute("aria-pressed", "true");
    }
    const stored = (await api.getCall(call.id)).feedback.map((entry) => entry.kind);
    expect(stored).toEqual(expect.arrayContaining(["correct_classification", "wrong_summary"]));
  });
});
