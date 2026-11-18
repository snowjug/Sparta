import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { OnboardingScreen } from "./onboarding-screen";
import { renderWithApp } from "@/test/render";
import { apiError, createFakeApi } from "@/test/fake-fetch";
import { makeCall, makePreferences, makeProfile, makeStatus } from "@/test/fixtures";
import { makeAssistantRoutes } from "@/test/routes";

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.replace, back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/onboarding",
  useSearchParams: () => new URLSearchParams(),
}));

function api(extra: Record<string, () => unknown> = {}) {
  let prefs = makePreferences();
  let profile = makeProfile();
  return createFakeApi({
    ...makeAssistantRoutes(),
    "GET /api/v1/preferences": () => prefs,
    "PUT /api/v1/preferences": (req: { body: unknown }) => (prefs = req.body as typeof prefs),
    "GET /api/v1/assistant-profile": () => profile,
    "PUT /api/v1/assistant-profile": (req: { body: unknown }) => (profile = req.body as typeof profile),
    "POST /api/v1/assistant-profile/preview": () => ({ disclosure: { text: "Hi, I'm Atharv's AI call assistant.", locale: "en-IN", voice_id: null, rate: 1, style: null, ssml: null, transliteration: null, est_duration_ms: 3200 }, reply: null, risk: null, detected_language: null }),
    "GET /api/v1/voices": () => [{ id: "en-IN-NeerjaNeural", locale: "en-IN", display_name: "Neerja", gender: "female", provider: "azure-speech", verified: true, note: "Default" }],
    "GET /api/v1/simulator/scenarios": () => [
      { id: "bank-otp-en", title: "Bank OTP request (English)", description: "A bank asks for the OTP.", language_profile: "english", languages: ["en-IN"], tags: [], turn_count: 2, expected_action: "refuse_and_end", custom: false },
      { id: "delivery-legit", title: "Delivery executive at the gate", description: "A genuine delivery call.", language_profile: "english", languages: ["en-IN"], tags: [], turn_count: 2, expected_action: "escalate_to_owner", custom: false },
    ],
    "POST /api/v1/simulator/replay": () => ({ call: makeCall(), events: [], checksum: "abcdef0123456789abcdef", checksum_covers: "events" }),
    ...extra,
  });
}

const next = () => userEvent.click(screen.getByTestId("onboarding-next"));

describe("OnboardingScreen", () => {
  it("walks the nine steps, saves choices with PUT, and marks onboarding complete at the end", async () => {
    const fake = api();
    renderWithApp(<OnboardingScreen />, { api: fake });
    expect(await screen.findByTestId("step-title")).toHaveTextContent("Welcome to Sparta");
    expect(screen.getByTestId("step-counter")).toHaveTextContent("Step 1 of 9");

    await next(); // -> AI disclosure
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Sparta always says it is an AI"));
    expect(await screen.findByTestId("onboarding-disclosure")).toHaveTextContent("Hi, I'm Atharv's AI call assistant.");
    expect(screen.getByText(/always on and cannot be switched off/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Your name, as Sparta says it/), { target: { value: "Atharv S" } });
    await next(); // -> privacy (saves the assistant profile)
    await waitFor(() => expect(fake.callsTo("PUT /api/v1/assistant-profile")).toHaveLength(1));
    expect(fake.callsTo("PUT /api/v1/assistant-profile")[0]?.body).toMatchObject({ owner_display_name: "Atharv S" });

    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Privacy and retention"));
    await userEvent.click(screen.getByRole("radio", { name: /30 days/ }));
    await next(); // -> languages (saves preferences)
    await waitFor(() => expect(fake.callsTo("PUT /api/v1/preferences")).toHaveLength(1));
    expect(fake.callsTo("PUT /api/v1/preferences")[0]?.body).toMatchObject({ retention: { transcript_retention_days: 30, store_raw_audio: false } });

    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Languages"));
    await next(); // voice
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Assistant voice"));
    await next(); // strictness
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("How careful Sparta should be"));
    await userEvent.click(screen.getByRole("radio", { name: /Strict/ }));
    await next(); // trusted contacts
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Trusted contacts"));
    await userEvent.click(screen.getByRole("radio", { name: /Screen them too/ }));
    await next(); // walkthrough
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("See it work"));
    await next(); // telephony
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Phone connection"));
    expect(fake.callsTo("PUT /api/v1/preferences").at(-1)?.body).toMatchObject({ strictness: "strict", trusted_contact_behavior: "screen_anyway", onboarding_completed: false });

    await userEvent.click(screen.getByTestId("onboarding-finish"));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/"));
    expect(fake.callsTo("PUT /api/v1/preferences").at(-1)?.body).toMatchObject({ onboarding_completed: true });
  });

  it("runs a recorded call through the real pipeline in the simulator walkthrough and says it is simulated", async () => {
    window.sessionStorage.setItem("sparta.onboarding.step", "7");
    const fake = api();
    renderWithApp(<OnboardingScreen />, { api: fake });
    expect(await screen.findByTestId("step-title")).toHaveTextContent("See it work");
    await userEvent.click(await screen.findByTestId("run-walkthrough"));
    const result = await screen.findByTestId("walkthrough-result");
    expect(within(result).getByText("Simulated")).toBeInTheDocument();
    expect(within(result).getByText(/Deterministic replay/)).toHaveTextContent("abcdef0123456789");
    expect(fake.callsTo("POST /api/v1/simulator/replay")[0]?.body).toEqual({ scenario_id: "bank-otp-en" });
  });

  it("explains what a missing forwarding number means, honestly, on the telephony step", async () => {
    window.sessionStorage.setItem("sparta.onboarding.step", "8");
    renderWithApp(<OnboardingScreen />, { api: api() });
    expect(await screen.findByTestId("forwarding-number")).toHaveTextContent("Not set");
    expect(screen.getByTestId("forwarding-explained")).toHaveTextContent(/real incoming calls cannot reach Sparta yet/);
    expect(screen.getByText("Not connected")).toBeInTheDocument();
  });

  it("shows a configured forwarding number without the 'not set' explanation", async () => {
    window.sessionStorage.setItem("sparta.onboarding.step", "8");
    const fake = api({ "GET /api/v1/system/status": () => makeStatus({ telephony: { provider: "azure", simulated: false, live_calls_supported: true, forwarding_number: "+1 555 0100", note: "ACS connected" } }) });
    renderWithApp(<OnboardingScreen />, { api: fake });
    expect(await screen.findByTestId("forwarding-number")).toHaveTextContent("+1 555 0100");
    expect(screen.queryByTestId("forwarding-explained")).toBeNull();
    expect(screen.getByText("Real · Azure")).toBeInTheDocument();
  });

  it("stays on the step and shows the API's field error when saving fails", async () => {
    const fake = api({ "PUT /api/v1/assistant-profile": () => apiError(422, "validation_error", "Request validation failed", { details: [{ field: "owner_display_name", message: "String should have at most 60 characters" }] }) });
    renderWithApp(<OnboardingScreen />, { api: fake });
    await screen.findByTestId("step-title");
    await next();
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Sparta always says it is an AI"));
    fireEvent.change(screen.getByLabelText(/Your name, as Sparta says it/), { target: { value: "x".repeat(40) } });
    await next();
    expect(await screen.findByText("String should have at most 60 characters")).toBeInTheDocument();
    expect(screen.getByTestId("step-title")).toHaveTextContent("Sparta always says it is an AI");
    expect(await screen.findByText("Check the highlighted details")).toBeInTheDocument(); // error toast
  });

  it("can be skipped for this session, and the step survives a reload", async () => {
    const fake = api();
    const { unmount } = renderWithApp(<OnboardingScreen />, { api: fake });
    await screen.findByTestId("step-title");
    await next();
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Sparta always says it is an AI"));
    unmount();
    renderWithApp(<OnboardingScreen />, { api: fake });
    expect(await screen.findByTestId("step-title")).toHaveTextContent("Sparta always says it is an AI");
    await userEvent.click(screen.getByTestId("skip-onboarding"));
    expect(window.sessionStorage.getItem("sparta.onboarding.skipped")).toBe("1");
    expect(nav.push).toHaveBeenCalledWith("/");
  });

  it("moves focus to the step title so keyboard and screen-reader users land on the new step", async () => {
    renderWithApp(<OnboardingScreen />, { api: api() });
    await screen.findByTestId("step-title");
    await next();
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveTextContent("Sparta always says it is an AI"));
    await waitFor(() => expect(screen.getByTestId("step-title")).toHaveFocus());
    expect(screen.getByRole("progressbar", { name: "Setup progress" })).toHaveAttribute("aria-valuenow", "2");
  });
});
