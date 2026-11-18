import type { CallDetail } from "../../src/lib/api/types";
import { OwnerApi } from "./api";
import { API_ORIGIN, test as base, expect } from "./test";

export interface Showcase {
  ownerId: string;
  /** Bank OTP scam: English, high risk, refused and ended. */
  bank: CallDetail;
  /** English, Hindi (Hinglish), Kannada-English (Kanglish) and an OTP request: refused and ended. */
  journey: CallDetail;
  /** A genuine recruiter call that escalated and was ended by the owner. */
  recruiter: CallDetail;
  /** How many filler calls exist besides the three rich ones (so history needs "Load more"). */
  fillerCount: number;
}

const FILLER_CALLS = 20;

/**
 * One owner with a realistic history, created once per worker and shared by the read-only specs (accessibility, screenshots,
 * history filters). Tests that change data use their own owner instead.
 */
export const test = base.extend<{ ownerId: string }, { showcase: Showcase }>({
  showcase: [
    async ({ playwright }, use) => {
      const ownerId = `e2e-show-${Math.random().toString(36).slice(2, 8)}`;
      const request = await playwright.request.newContext({ baseURL: `${API_ORIGIN}/api/v1/`, extraHTTPHeaders: { "X-Sparta-Dev-User": ownerId } });
      const api = new OwnerApi(request);
      await api.useFastSpeech();
      const bank = await api.seedCall("bank-otp-en");
      const journey = await api.seedCall("language-switch-journey");
      const recruiter = await api.seedCall("recruiter-callback", { waitForEnd: false });
      await api.waitForSilence(recruiter.id);
      await api.endCall(recruiter.id);
      await api.waitForStatus(recruiter.id, "ended");
      await api.seedEndedCalls(FILLER_CALLS);
      await use({ ownerId, bank: await api.getCall(bank.id), journey: await api.getCall(journey.id), recruiter: await api.getCall(recruiter.id), fillerCount: FILLER_CALLS });
      await request.dispose();
    },
    { scope: "worker", timeout: 360_000 },
  ],

  ownerId: async ({ showcase }, use) => {
    await use(showcase.ownerId);
  },
});

export { expect };
