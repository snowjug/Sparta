/**
 * Routes handed to us by the API (HomeSummary.next_action.route) are only followed when they point at one of this app's
 * own screens: an unexpected value can never turn into an open redirect.
 */
const ALLOWED = /^\/(?:(?:onboarding|simulator|studio|safety|calls|live)(?:\/[A-Za-z0-9_-]{1,64})?)?$/;

export function safeRoute(route: string | null | undefined): string {
  return route && ALLOWED.test(route) ? route : "/";
}
