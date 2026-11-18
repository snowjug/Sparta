import { SCENARIO_TURNS } from "./support/api";
import { sendTypedTurn, startLabCall, waitForAssistantToFinish } from "./support/lab";
import { expect, test } from "./support/test";
import { MASK_CHARS } from "./support/ui";

// The ten-step owner journey from the product brief, against the real backend (simulated telephony, rule-based assistant).
test.use({ skipOnboarding: false });

test("the owner journey: onboarding, a multilingual OTP scam call, refusal, summary, feedback, history", async ({ page, api }) => {
  test.setTimeout(180_000);
  const turns = SCENARIO_TURNS["language-switch-journey"];
  let callId = "";

  await test.step("1. complete onboarding", async () => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/onboarding$/);
    await expect(page.getByTestId("step-title")).toHaveText("Welcome to Sparta");
    for (let step = 2; step <= 9; step += 1) {
      await page.getByTestId("onboarding-next").click();
      await expect(page.getByTestId("step-counter")).toHaveText(`Step ${step} of 9`);
    }
    // The last step is honest about the phone connection: the simulator has no forwarding number.
    await expect(page.getByTestId("telephony-step")).toContainText(/simulat/i);
    await page.getByTestId("onboarding-finish").click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId("protection-card")).toBeVisible();
    expect((await api.get<{ onboarding_completed: boolean }>("preferences")).onboarding_completed).toBe(true);
  });

  await test.step("2. start a simulator call", async () => {
    callId = await startLabCall(page, { scenario: "language-switch-journey" });
    const consolePanel = page.getByTestId("lab-console");
    await expect(consolePanel).toHaveAttribute("data-status", "active");
    await expect(consolePanel.getByText("Simulated", { exact: true }).first()).toBeVisible();
    // Sparta opens by saying it is an AI assistant: the disclosure cannot be skipped.
    const first = page.getByTestId("turn").first();
    await expect(first).toHaveAttribute("data-speaker", "assistant");
    await expect(first).toContainText("AI call assistant");
    await waitForAssistantToFinish(api, callId);
  });

  const callerTurns = page.locator('[data-testid="turn"][data-speaker="caller"]');

  await test.step("3. the caller speaks English", async () => {
    await sendTypedTurn(page, turns[0]);
    await expect(callerTurns).toHaveCount(1);
    await expect(callerTurns.nth(0)).toHaveAttribute("data-language", "en-IN");
    await expect(callerTurns.nth(0)).toContainText("English");
    await expect(page.locator('[data-testid="turn"][data-speaker="assistant"]')).toHaveCount(2);
    await waitForAssistantToFinish(api, callId);
  });

  await test.step("4. the caller switches to Hindi", async () => {
    await sendTypedTurn(page, turns[1]);
    await expect(callerTurns).toHaveCount(2);
    await expect(callerTurns.nth(1)).toHaveAttribute("data-language", "hi-IN");
    await expect(callerTurns.nth(1)).toContainText("Hinglish");
    await expect(page.getByTestId("language-change")).toHaveCount(1);
    await expect(page.getByTestId("language-change").first()).toContainText("English → Hindi");
    await waitForAssistantToFinish(api, callId);
  });

  await test.step("5. the caller switches to Kannada-English (Kanglish)", async () => {
    await sendTypedTurn(page, turns[2]);
    await expect(callerTurns).toHaveCount(3);
    await expect(callerTurns.nth(2)).toContainText("Kanglish");
    await expect(page.getByTestId("language-change")).toHaveCount(2);
    await waitForAssistantToFinish(api, callId);
  });

  await test.step("6. the caller asks for an OTP", async () => {
    await sendTypedTurn(page, turns[3]);
    await expect(callerTurns).toHaveCount(4);
    const risk = page.getByTestId("risk-meter");
    await expect(risk).toHaveAttribute("data-risk", /^(high|critical)$/);
    const otp = page.locator('[data-testid="signal-item"][data-signal="OTP_REQUEST"]');
    await expect(otp).toBeVisible();
    await expect(otp).toContainText(/otp|one-time/i);
  });

  await test.step("7. Sparta refuses and ends the call", async () => {
    const consolePanel = page.getByTestId("lab-console");
    await expect(consolePanel).toHaveAttribute("data-state", "END_SPAM");
    await expect(page.getByTestId("turn").last()).toContainText("I can't share or accept any personal, financial or security information");
    await expect(consolePanel).toHaveAttribute("data-status", "ended", { timeout: 30_000 });
    await expect(page.getByTestId("voice-stage")).toHaveAttribute("data-mode", "ended");
  });

  await test.step("8. a summary is created", async () => {
    const summary = page.getByTestId("lab-summary");
    await expect(summary).toBeVisible({ timeout: 15_000 });
    await expect(summary).not.toBeEmpty();
    const call = await api.getCall(callId);
    expect(call.summary?.text).toBeTruthy();
    expect(call.risk?.risk_level).toMatch(/^(high|critical)$/);
  });

  await test.step("9. the owner marks the classification correct", async () => {
    await page.getByTestId("open-call-detail").click();
    await expect(page).toHaveURL(new RegExp(`/calls/${callId}$`));
    await expect(page.getByTestId("summary-text")).not.toBeEmpty();
    // Only the masked number is ever shown.
    await expect(page.getByTestId("call-detail")).not.toContainText("9800000104");
    const correct = page.getByTestId("feedback-correct_classification");
    await correct.click();
    await expect(correct).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("status").filter({ hasText: "Thanks for the feedback" }).first()).toBeVisible();
    const call = await api.getCall(callId);
    expect(call.feedback.map((entry) => entry.kind)).toContain("correct_classification");
  });

  await test.step("10. the call appears in history", async () => {
    await page.goto("/calls");
    const row = page.locator(`[data-testid="history-row"][data-call-id="${callId}"]`);
    await expect(row).toBeVisible();
    await expect(row.getByTestId("caller-display")).toContainText(MASK_CHARS);
    await expect(row).not.toContainText("9800000104");
    await expect(row).toContainText(/high|critical/i);
    await row.getByRole("button").first().click();
    await expect(row.getByTestId("history-details")).toBeVisible();
    await expect(page.getByTestId("history-count")).toContainText("1");
  });
});
