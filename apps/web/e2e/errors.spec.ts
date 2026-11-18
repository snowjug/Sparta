import { sendTypedTurn, startLabCall, waitForAssistantToFinish } from "./support/lab";
import { expect, test } from "./support/test";
import { notifications } from "./support/ui";

const CORS = { "access-control-allow-origin": "http://localhost:3100", "access-control-expose-headers": "X-Request-ID, Retry-After" };

function envelope(code: string, message: string, traceId: string, details: Array<{ field: string; message: string }> | null = null) {
  return JSON.stringify({ error: { code, message, trace_id: traceId, details } });
}

test.describe("API errors become accessible messages", () => {
  // The browser logs every non-2xx response it receives; this describe provokes them on purpose.
  test.use({ allowedErrors: /status of (401|409|429|500|503)|ERR_/, permissions: ["clipboard-read", "clipboard-write"] });

  test("401 unauthorized: the page shows the API's message and a copyable trace id, and Try again recovers", async ({ page }) => {
    await page.route("**/api/v1/preferences", (route) =>
      route.request().method() === "GET"
        ? route.fulfill({ status: 401, contentType: "application/json", headers: { ...CORS, "x-request-id": "req-401" }, body: envelope("unauthorized", "Sign in to continue.", "trace-401-xyz") })
        : route.continue(),
    );
    await page.goto("/studio");
    const alert = page.getByRole("alert").filter({ hasText: "Couldn't load your preferences" });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Sign in to continue.");

    await alert.getByText("Technical details").click();
    await expect(alert).toContainText("unauthorized");
    await expect(alert).toContainText("401");
    await expect(alert).toContainText("trace-401-xyz");
    await alert.getByRole("button", { name: "Copy details" }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("trace-401-xyz");

    await page.unroute("**/api/v1/preferences");
    await alert.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByTestId("disclosure-preview")).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "Couldn't load your preferences" })).toHaveCount(0);
  });

  test("429 too many requests: the toast says how long to wait, unsaved changes are kept and a retry succeeds", async ({ page, api }) => {
    await page.goto("/studio");
    await expect(page.getByTestId("disclosure-preview")).toBeVisible();
    await page.route("**/api/v1/assistant-profile", (route) =>
      route.request().method() === "PUT"
        ? route.fulfill({ status: 429, contentType: "application/json", headers: { ...CORS, "retry-after": "4" }, body: envelope("rate_limited", "Rate limit exceeded", "trace-429-abc") })
        : route.continue(),
    );
    await page.getByLabel("Your name, as Sparta says it").fill("RateTest");
    await page.getByTestId("save-settings").click();

    const toast = notifications(page).getByRole("alert");
    await expect(toast).toContainText("Too many requests");
    await expect(toast).toContainText("Try again in 4 seconds");
    await expect(page.getByTestId("save-bar")).toBeVisible(); // nothing was lost
    expect((await api.get<{ owner_display_name: string }>("assistant-profile")).owner_display_name).not.toBe("RateTest");

    await page.unroute("**/api/v1/assistant-profile");
    await page.getByTestId("save-settings").click();
    await expect(notifications(page)).toContainText("Your changes are saved");
    expect((await api.get<{ owner_display_name: string }>("assistant-profile")).owner_display_name).toBe("RateTest");
  });

  test("a transient 5xx on a read is retried with backoff and the page loads without showing an error", async ({ page }) => {
    let attempts = 0;
    await page.route("**/api/v1/home", (route) => {
      attempts += 1;
      return attempts <= 2 ? route.fulfill({ status: 500, contentType: "application/json", headers: CORS, body: envelope("internal_error", "Something went wrong on our side. Please try again.", "trace-500") }) : route.continue();
    });
    await page.goto("/");
    await expect(page.getByTestId("protection-card")).toBeVisible({ timeout: 15_000 });
    expect(attempts).toBe(3);
    // (Next's own route announcer is an empty role=alert: only alerts with text count.)
    await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);
  });

  test("when the API cannot be reached the whole app says so once and recovers on Retry", async ({ page }) => {
    await page.goto("/calls");
    await expect(page.getByTestId("history-count")).toBeAttached();
    await page.route("**/api/v1/**", (route) => route.abort("connectionrefused"));
    await page.reload();
    const notice = page.getByRole("alert").filter({ hasText: "Can't reach the Sparta API." });
    await expect(notice).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("API offline")).toBeVisible();

    await page.unroute("**/api/v1/**");
    await notice.getByRole("button", { name: "Retry" }).click();
    await expect(notice).toHaveCount(0);
    await expect(page.getByTestId("dev-banner")).toContainText("Development identity");
  });

  test("409 conflict: a caller turn refused by the API because the call is already ending is explained in place and never shown as sent", async ({ page, api }) => {
    // The real server's own refusal: send a turn to a call that Sparta has already ended.
    const finished = await api.seedCall("bank-otp-en");
    const refusal = await api.request.post(`calls/${finished.id}/turns`, { data: { text: "Hello? Are you still there?", source: "typed" } });
    expect(refusal.status()).toBe(409);
    const refusalBody = await refusal.text();
    const serverMessage = (JSON.parse(refusalBody) as { error: { message: string } }).error.message;

    // The browser may not know yet that the call is ending (the event is still on its way): replay that exact refusal.
    const callId = await startLabCall(page);
    await waitForAssistantToFinish(api, callId);
    await page.route(`**/api/v1/calls/${callId}/turns`, (route) => route.fulfill({ status: 409, contentType: "application/json", headers: CORS, body: refusalBody }));
    await sendTypedTurn(page, "Hello? Are you still there?");
    const note = page.getByTestId("call-ending-note");
    await expect(note).toBeVisible();
    await expect(note).toContainText(serverMessage);
    await expect(page.locator('[data-testid="turn"][data-speaker="caller"]')).toHaveCount(0);
    await expect(page.getByTestId("caller-text")).toHaveValue("Hello? Are you still there?"); // the text is kept, not swallowed
  });
});

test.describe("validation errors", () => {
  test.use({ allowedErrors: /status of 422/ });

  test("a field error from the API is shown next to the field, announced, and the entered text is not echoed back", async ({ page }) => {
    await page.goto("/safety");
    const card = page.getByTestId("blocked-card");
    await card.getByLabel("Phone number").fill("abcdefghij");
    await card.getByRole("button", { name: "Block number" }).click();
    const field = card.getByLabel("Phone number");
    await expect(field).toHaveAttribute("aria-invalid", "true");
    const describedBy = (await field.getAttribute("aria-describedby")) ?? "";
    const messages = await Promise.all(describedBy.split(" ").filter(Boolean).map((id) => page.locator(`[id="${id}"]`).textContent()));
    expect(messages.join(" ")).not.toContain("abcdefghij");
    expect(messages.join(" ").trim().length).toBeGreaterThan(0);
    await expect(card.getByTestId("blocked-item")).toHaveCount(0);
  });
});
