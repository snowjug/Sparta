import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { sendTypedTurn, startLabCall, waitForAssistantToFinish } from "./support/lab";
import { expect, test } from "./support/showcase";
import { test as ownTest } from "./support/test";

// Responsive screenshots of every screen (phone, tablet, desktop). They document the layout; they are not pixel baselines.
const DIRECTORY = resolve(__dirname, "screenshots");
const SIZES = [
  { width: 375, height: 812 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
] as const;

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
  await page.evaluate(() => document.fonts.ready);
}

async function capture(page: Page, name: string, theme: "dark" | "light", sizes: ReadonlyArray<{ width: number; height: number }>): Promise<void> {
  mkdirSync(DIRECTORY, { recursive: true });
  for (const size of sizes) {
    await page.setViewportSize(size);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(250); // let the responsive layout settle
    await page.screenshot({ path: resolve(DIRECTORY, `${name}-${size.width}${theme === "light" ? "-light" : ""}.png`), animations: "disabled", caret: "hide" });
  }
}

for (const theme of ["dark", "light"] as const) {
  test.describe(`screenshots (${theme})`, () => {
    test.use({ theme, colorScheme: theme });
    // Dark: all three sizes. Light: phone and desktop.
    const sizes = theme === "dark" ? SIZES : [SIZES[0], SIZES[2]];

    test("onboarding", async ({ page }) => {
      await page.goto("/onboarding");
      await expect(page.getByTestId("step-title")).toBeVisible();
      await settle(page);
      await capture(page, "onboarding", theme, sizes);
    });

    test("home", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByTestId("recent-list")).toBeVisible();
      await settle(page);
      await capture(page, "home", theme, sizes);
    });

    test("call history", async ({ page }) => {
      await page.goto("/calls");
      await expect(page.getByTestId("history-list")).toBeVisible();
      await page.getByTestId("history-row").first().getByRole("button").first().click();
      await settle(page);
      await capture(page, "history", theme, sizes);
    });

    test("call detail", async ({ page, showcase }) => {
      await page.goto(`/calls/${showcase.journey.id}`);
      await expect(page.getByTestId("summary-text")).toBeVisible();
      await settle(page);
      await capture(page, "call-detail", theme, sizes);
    });

    test("assistant studio", async ({ page }) => {
      await page.goto("/studio");
      await expect(page.getByTestId("disclosure-preview")).toBeVisible();
      await settle(page);
      await capture(page, "studio", theme, sizes);
    });

    test("safety center", async ({ page }) => {
      await page.goto("/safety");
      await expect(page.getByTestId("safety-event").first()).toBeVisible();
      await settle(page);
      await capture(page, "safety", theme, sizes);
    });
  });

  // Screens that start calls use an owner of their own: the showcase history stays exactly as seeded.
  ownTest.describe(`screenshots (${theme}): live calls`, () => {
    ownTest.use({ theme, colorScheme: theme });
    const sizes = theme === "dark" ? SIZES : [SIZES[0], SIZES[2]];

    ownTest("live call with an escalation waiting for the owner", async ({ page, api }) => {
      const call = await api.seedEscalatedCall();
      await page.goto(`/live/${call.id}`);
      await expect(page.getByTestId("escalation-banner")).toBeVisible();
      await expect(page.getByTestId("connection-pill")).toHaveAttribute("data-connection", "open");
      await settle(page);
      await capture(page, "live", theme, sizes);
    });

    ownTest("simulator lab: setup, then the live console", async ({ page, api }) => {
      await page.goto("/simulator");
      await expect(page.getByTestId("scenario-list")).toBeVisible();
      await settle(page);
      await capture(page, "lab", theme, sizes);

      const callId = await startLabCall(page, { scenario: "bank-otp-en" });
      await waitForAssistantToFinish(api, callId);
      await sendTypedTurn(page, "Good afternoon, this is Rahul from State Bank of India. Your account has been flagged for suspicious activity.");
      await expect(page.locator('[data-testid="turn"][data-speaker="caller"]')).toHaveCount(1);
      await waitForAssistantToFinish(api, callId);
      await sendTypedTurn(page, "To secure it I just need the OTP that was sent to your phone. Please read it out now.");
      await expect(page.getByTestId("risk-meter")).toHaveAttribute("data-risk", /^(high|critical)$/);
      await settle(page);
      await capture(page, "lab-console", theme, sizes);
    });
  });
}
