import { test as base, expect } from "@playwright/test";
import { OwnerApi } from "./api";

export const API_ORIGIN = "http://localhost:8100";
export const WEB_ORIGIN = "http://localhost:3100";

export interface OwnerOptions {
  /** Tabs behave as if the owner pressed "Skip for now" in onboarding, so screens load instead of redirecting to /onboarding. */
  skipOnboarding: boolean;
  theme: "dark" | "light" | "system";
  /** Console errors the test provokes on purpose (for example the browser's own log line for an expected 4xx response). One pattern: Playwright reads two-element arrays in test.use() as [value, options] tuples. */
  allowedErrors: RegExp | null;
  /** The simulated assistant speaks in real time; the fastest allowed speaking rate (1.3) keeps seeded calls short. Studio tests switch it off. */
  fastSpeech: boolean;
}

interface OwnerFixtures {
  /** A fresh dev identity per test: every test sees only its own calls, so tests can run in parallel. */
  ownerId: string;
  api: OwnerApi;
}

function newOwnerId(): string {
  return `e2e-${Math.random().toString(36).slice(2, 10)}${Date.now().toString(36).slice(-4)}`;
}

/**
 * `test` with a per-test owner, an API helper bound to that owner and a guard that fails the test on unexpected browser errors
 * (console errors, uncaught exceptions, CSP violations and failed requests all surface as console errors in Chromium).
 */
export const test = base.extend<OwnerOptions & OwnerFixtures>({
  skipOnboarding: [true, { option: true }],
  theme: ["dark", { option: true }],
  allowedErrors: [null, { option: true }],
  fastSpeech: [true, { option: true }],

  ownerId: async ({}, use) => {
    await use(newOwnerId());
  },

  api: async ({ playwright, ownerId, fastSpeech }, use) => {
    const request = await playwright.request.newContext({
      baseURL: `${API_ORIGIN}/api/v1/`,
      extraHTTPHeaders: { "X-Sparta-Dev-User": ownerId },
    });
    const api = new OwnerApi(request);
    if (fastSpeech) await api.useFastSpeech();
    await use(api);
    await api.endActiveCalls();
    await request.dispose();
  },

  context: async ({ context, ownerId, skipOnboarding, theme }, use) => {
    await context.addInitScript(
      ({ owner, skip, preferredTheme }) => {
        try {
          window.localStorage.setItem("sparta.dev_user", owner);
          if (preferredTheme !== "system" && !window.localStorage.getItem("sparta.theme")) window.localStorage.setItem("sparta.theme", preferredTheme);
          if (skip && !window.sessionStorage.getItem("sparta.onboarding.skipped")) window.sessionStorage.setItem("sparta.onboarding.skipped", "1");
        } catch {
          /* storage unavailable: the app falls back to its defaults */
        }
      },
      { owner: ownerId, skip: skipOnboarding, preferredTheme: theme },
    );
    await use(context);
  },

  // Depends on `api` so the owner's speaking rate is set before the browser loads anything.
  page: async ({ page, api, allowedErrors }, use) => {
    void api;
    const problems: string[] = [];
    const allowed = (text: string) => allowedErrors?.test(text) ?? false;
    page.on("console", (message) => {
      if (message.type() === "error" && !allowed(message.text())) problems.push(`console.error: ${message.text()}`);
    });
    page.on("pageerror", (error) => {
      if (!allowed(error.message)) problems.push(`pageerror: ${error.message}`);
    });
    await use(page);
    expect(problems, "unexpected browser errors").toEqual([]);
  },
});

export { expect };
