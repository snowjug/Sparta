import { expect, type Locator, type Page } from "@playwright/test";
import type { OwnerApi } from "./api";
import { toggleSwitch } from "./ui";

export interface StartLabCallOptions {
  /** Scenario id (data-scenario-id). Omit for free play. */
  scenario?: string;
  autoplay?: boolean;
  language?: string;
  network?: "ideal" | "mobile_4g" | "congested";
  label?: string;
}

/** Opens the Simulator Lab, starts a call with the given setup and returns its id once the live console is on screen. */
export async function startLabCall(page: Page, options: StartLabCallOptions = {}): Promise<string> {
  await page.goto("/simulator");
  await expect(page.getByTestId("scenario-list")).toBeVisible();
  await page.locator(`[data-testid="scenario-option"][data-scenario-id="${options.scenario ?? ""}"]`).click();
  if (options.language) await page.getByTestId("language-select").selectOption(options.language);
  if (options.network) await page.getByTestId("network-select").selectOption(options.network);
  if (options.label) await page.getByLabel("Caller label (optional)").fill(options.label);
  if (options.autoplay) await toggleSwitch(page, /Play the scripted caller automatically/);
  await page.getByTestId("start-call").click();
  const console = page.getByTestId("lab-console");
  await expect(console).toBeVisible();
  const callId = await console.getAttribute("data-call-id");
  if (!callId) throw new Error("The live console has no call id");
  return callId;
}

/** Types a caller turn in the Lab and sends it. */
export async function sendTypedTurn(page: Page, text: string): Promise<void> {
  await page.getByTestId("caller-text").fill(text);
  await page.getByTestId("send-turn").click();
}

/**
 * Waits until the assistant has finished speaking, using the backend's own truth (`assistant_speaking`). Typing the next caller
 * turn while the assistant is speaking is barge-in (correct product behaviour), so scripted journeys wait for the end of speech.
 */
export async function waitForAssistantToFinish(api: OwnerApi, callId: string, timeout = 30_000): Promise<void> {
  await expect.poll(async () => (await api.getCall(callId)).assistant_speaking, { timeout, intervals: [600, 600, 1000] }).toBe(false);
}

/** The transcript turns on screen (live console or live view). */
export function transcriptTurns(page: Page): Locator {
  return page.getByTestId("turn");
}
