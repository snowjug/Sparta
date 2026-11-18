import { expect, test } from "./support/test";

// Deterministic replay (Simulator Lab). These run in parallel with everything else: the API replays a scenario on a virtual clock and
// waits by a wall-clock deadline, so overlapping replays are fine (they used to answer 500 `the replayed call did not go quiet`).

test.describe("deterministic replay", () => {
  test("running a scenario twice gives the identical checksum; another scenario gives a different one", async ({ page }) => {
    await page.goto("/simulator");
    await page.locator('[data-testid="scenario-option"][data-scenario-id="bank-otp-en"]').click();
    await page.locator("summary", { hasText: "Deterministic replay" }).click();
    await page.getByTestId("replay-twice").click();

    await expect(page.getByTestId("replay-equality")).toContainText("Checksums are identical");
    const first = (await page.getByTestId("checksum-1").textContent())?.trim() ?? "";
    const second = (await page.getByTestId("checksum-2").textContent())?.trim() ?? "";
    expect(first).toMatch(/^[0-9a-f]{64}$/);
    expect(second).toBe(first);
    await expect(page.getByTestId("replay-result")).toContainText("virtual timestamps");

    await page.locator('[data-testid="scenario-option"][data-scenario-id="kyc-hinglish"]').click();
    await page.getByTestId("replay-once").click();
    const other = (await page.getByTestId("checksum-1").textContent())?.trim() ?? "";
    expect(other).toMatch(/^[0-9a-f]{64}$/);
    expect(other).not.toBe(first);
  });

  test("a custom scenario replays deterministically too, and the UI shows the same checksum the API returns", async ({ page, api }) => {
    const created = await api.post<{ id: string }>("simulator/scenarios", {
      title: "E2E replayed OTP scam",
      language_profile: "english",
      turns: [
        { text: "This is the fraud team. Please read out the OTP now.", language: "en-IN", delay_ms: 700 },
        { text: "Hurry, your account will be blocked today.", language: "en-IN", delay_ms: 600 },
      ],
    });
    const direct = await api.post<{ checksum: string }>("simulator/replay", { scenario_id: created.id });

    await page.goto("/simulator");
    const option = page.locator(`[data-testid="scenario-option"][data-scenario-id="${created.id}"]`);
    await option.click();
    await page.locator("summary", { hasText: "Deterministic replay" }).click();
    await page.getByTestId("replay-twice").click();
    await expect(page.getByTestId("replay-equality")).toContainText("Checksums are identical");
    expect((await page.getByTestId("checksum-1").textContent())?.trim()).toBe(direct.checksum);
  });
});
