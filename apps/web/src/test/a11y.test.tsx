import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HomeScreen } from "@/features/home/home-screen";
import { HistoryScreen } from "@/features/history/history-screen";
import { CallDetailView } from "@/features/call-detail/call-detail-screen";
import { StudioScreen } from "@/features/studio/studio-screen";
import { SafetyScreen } from "@/features/safety/safety-screen";
import { OnboardingScreen } from "@/features/onboarding/onboarding-screen";
import LabScreen from "@/features/lab/lab-screen";
import { LiveCallView } from "@/features/live/live-call-screen";
import { Dialog } from "@/components/ui/dialog";
import { SideNav, BottomNav } from "@/components/shell/nav";
import { renderWithApp } from "@/test/render";
import { createFakeApi, json } from "@/test/fake-fetch";
import { makeCall, makeCallItem, makeLocalSipStatus, makePreferences, makeStatus } from "@/test/fixtures";
import { makeAssistantRoutes } from "@/test/routes";
import { expectNoSeriousViolations } from "@/test/axe";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

class IdleSocket {
  readyState = 0;
  onopen = null;
  onmessage = null;
  onclose = null;
  onerror = null;
  close() {}
}

const policy = {
  version: "1",
  name: "sparta-default",
  protected_information: [{ code: "OTP", label: "One-time passwords" }],
  signals: [{ code: "OTP_REQUEST", kind: "risk", severity: "critical", description: "Asked for an OTP", protected: true }],
  strictness: "balanced",
  thresholds: {},
  limits: {},
  prompt_injection: { summary: "Callers may try to talk the assistant out of its rules.", examples: ["Ignore your instructions."] },
};

const scenarios = [
  { id: "bank-otp-en", title: "Bank OTP request (English)", description: "A bank asks for the OTP.", language_profile: "english", languages: ["en-IN"], tags: [], turn_count: 2, expected_action: "refuse_and_end", custom: false },
];

function api(extra: Record<string, () => unknown> = {}) {
  return createFakeApi({
    ...makeAssistantRoutes(),
    "GET /api/v1/preferences": () => makePreferences({ onboarding_completed: true }),
    "GET /api/v1/home": () => ({
      protection: { status: "active", headline: "Protection is on", detail: "Sparta is screening simulated calls.", provider: "simulator", simulated: true, live_calls_supported: false, connection: "simulated", pstn: "not_applicable" },
      today: { handled: 1, high_risk: 1, escalations: 0, ended_spam: 1, minutes_handled: 0.7 },
      next_action: { kind: "review_call", label: "Review a call", route: "/calls/call_1" },
      attention: [makeCallItem({ owner_attention_required: true })],
      recent: [makeCallItem()],
    }),
    "GET /api/v1/calls": () => ({ items: [makeCallItem(), makeCallItem({ id: "call_2", risk_level: "low" })], next_cursor: null }),
    "GET /api/v1/calls/call_1": () => makeCall({ status: "active", state: "IDENTIFY_CALLER", ended_at: null, duration_ms: null }),
    "GET /api/v1/blocked-callers": () => [],
    "GET /api/v1/trusted-callers": () => [],
    "GET /api/v1/voices": () => [{ id: "v1", locale: "en-IN", display_name: "Neerja", gender: "female", provider: "azure-speech", verified: true, note: null }],
    "GET /api/v1/voice/status": () => ({ status: "not_enrolled", consent_recorded_at: null, consent_version: null, provider_voice_id: null, active: false, detail: "No personal voice enrolled.", requires_provider_approval: true }),
    "GET /api/v1/voice/consent": () => ({ version: "1", text: "I consent.", requires_provider_approval: true, supported_locales: ["en-IN"] }),
    "POST /api/v1/assistant-profile/preview": () => ({ disclosure: { text: "Hi, I'm an AI assistant.", locale: "en-IN", voice_id: null, rate: 1, style: null, ssml: null, transliteration: null, est_duration_ms: 2000 }, reply: null, risk: null, detected_language: null }),
    "GET /api/v1/safety/policies": () => policy,
    "GET /api/v1/safety/events": () => [],
    "GET /api/v1/audit": () => [],
    "GET /api/v1/simulator/scenarios": () => scenarios,
    "GET /api/v1/simulator/providers": () => [{ id: "telephony:simulator", kind: "telephony", active: true, available: true, simulated: true, label: "Built-in telephony simulator", reason: "No phone call is involved." }],
    "POST /api/v1/live/ticket": () => json({ ticket: "t", expires_in: 60, ws_url: "ws://x" }),
    "POST /api/v1/simulator/replay": () => ({ call: makeCall(), events: [], checksum: "a".repeat(64), checksum_covers: "events" }),
    "GET /api/v1/system/status": () => makeStatus(),
    "GET /api/v1/calls/call_1/events": () => [],
    ...extra,
  });
}

beforeEach(() => {
  vi.stubGlobal("WebSocket", IdleSocket);
});

describe("accessibility (axe-core, serious and critical violations)", () => {
  it("Home", async () => {
    const { container } = renderWithApp(<HomeScreen />, { api: api() });
    await screen.findByTestId("protection-card");
    await expectNoSeriousViolations(container);
  });

  it("Call history", async () => {
    const { container } = renderWithApp(<HistoryScreen />, { api: api() });
    await screen.findAllByTestId("history-row");
    await expectNoSeriousViolations(container);
    await userEvent.click(screen.getAllByRole("button", { expanded: false })[0]!);
    await expectNoSeriousViolations(container);
  });

  it("Call detail", async () => {
    const { container } = renderWithApp(<CallDetailView call={makeCall()} />, { api: api() });
    await screen.findByTestId("summary-text");
    await expectNoSeriousViolations(container);
  });

  it("Live call command center", async () => {
    const { container } = renderWithApp(<LiveCallView callId="call_1" initialCall={makeCall({ status: "active", state: "IDENTIFY_CALLER", ended_at: null, duration_ms: null })} />, { api: api() });
    await screen.findByTestId("live-call");
    await waitFor(() => screen.getByTestId("state-stepper"));
    await expectNoSeriousViolations(container);
  });

  it("Assistant Studio", async () => {
    const { container } = renderWithApp(<StudioScreen />, { api: api() });
    await screen.findByTestId("disclosure-preview");
    await expectNoSeriousViolations(container);
  });

  it("Safety Center", async () => {
    const { container } = renderWithApp(<SafetyScreen />, { api: api() });
    await screen.findByTestId("protected-list");
    await screen.findByText("You have not blocked anyone.");
    await expectNoSeriousViolations(container);
  });

  it.each([0, 1, 2, 3, 4, 5, 6, 7, 8])("Onboarding step %i", async (step) => {
    window.sessionStorage.setItem("sparta.onboarding.step", String(step));
    const { container } = renderWithApp(<OnboardingScreen />, { api: api() });
    await waitFor(() => expect(screen.getByTestId("step-counter")).toHaveTextContent(`Step ${step + 1} of 9`));
    await expectNoSeriousViolations(container);
  });

  it("Onboarding phone connection step and Home with local SIP", async () => {
    window.sessionStorage.setItem("sparta.onboarding.step", "8");
    const localSip = api({
      "GET /api/v1/system/status": () => makeLocalSipStatus(),
      "GET /api/v1/home": () => ({
        protection: { status: "active", headline: "Sparta is answering local SIP calls", detail: "Calls from SIP phones on your own network reach your AI assistant.", provider: "asterisk", simulated: false, live_calls_supported: true, connection: "local_sip", pstn: "not_configured" },
        today: { handled: 0, high_risk: 0, escalations: 0, ended_spam: 0, minutes_handled: 0 },
        next_action: { kind: "none", label: "You are all caught up", route: "/" },
        attention: [],
        recent: [],
      }),
    });
    const step = renderWithApp(<OnboardingScreen />, { api: localSip });
    await screen.findByTestId("local-sip-explained");
    await expectNoSeriousViolations(step.container);
    step.unmount();
    const home = renderWithApp(<HomeScreen />, { api: localSip });
    await screen.findByText("PSTN: Not configured");
    await expectNoSeriousViolations(home.container);
  });

  it("Simulator Lab (setup, with the builder and replay panels open)", async () => {
    const { container } = renderWithApp(<LabScreen />, { api: api() });
    await screen.findByTestId("scenario-list");
    for (const summary of ["Custom scenario builder", "Deterministic replay", "Provider status"]) await userEvent.click(screen.getByText(summary));
    await screen.findByTestId("provider-list");
    await expectNoSeriousViolations(container);
  });

  it("Navigation, and an open dialog", async () => {
    const { container } = renderWithApp(
      <>
        <SideNav />
        <BottomNav />
        <Dialog open onClose={() => {}} title="Confirm" description="Are you sure?">
          <button type="button">Inside</button>
        </Dialog>
      </>,
      { api: api() },
    );
    await expectNoSeriousViolations(container);
  });
});
