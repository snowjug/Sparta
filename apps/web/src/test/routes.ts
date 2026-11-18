import type { Handler } from "./fake-fetch";
import { makeProfile, makePreferences, makeStatus } from "./fixtures";

const P = "/api/v1";

/** Default read routes for tests that only care about a few endpoints. Override per test with `api.on(...)`. */
export function makeAssistantRoutes(): Record<string, Handler> {
  return {
    [`GET ${P}/system/status`]: () => makeStatus(),
    [`GET ${P}/me`]: () => ({ id: "dev-owner", display_name: "Atharv", auth_mode: "dev" }),
    [`GET ${P}/preferences`]: () => makePreferences({ onboarding_completed: true }),
    [`GET ${P}/assistant-profile`]: () => makeProfile(),
  };
}
