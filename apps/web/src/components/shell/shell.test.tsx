import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DevBanner } from "./dev-banner";
import { DisplayMenu } from "./display-menu";
import { SystemProviderBadge, SimulationBadge } from "./provider-badge";
import { AppShell } from "./app-shell";
import { renderWithApp } from "@/test/render";
import { apiError, createFakeApi } from "@/test/fake-fetch";
import { makePreferences, makeStatus } from "@/test/fixtures";
import { makeAssistantRoutes } from "@/test/routes";
import { findOpenDialog } from "@/test/dialog";

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), pathname: "/" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: nav.push, replace: nav.replace, back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(),
}));

describe("DisplayMenu", () => {
  const openMenu = async () => {
    render(
      <>
        <DisplayMenu />
        <button type="button">Somewhere else</button>
      </>,
    );
    const trigger = screen.getByRole("button", { name: /Display settings/ });
    await userEvent.click(trigger);
    return { trigger, panel: screen.getByRole("group", { name: "Display settings" }) };
  };

  it("stays open while the mouse is pressed inside it (focus moves to nothing), so the choice lands", async () => {
    const { trigger, panel } = await openMenu();
    // Pressing on a label or empty panel space blurs the trigger with no new focus target; that must not close the menu.
    fireEvent.blur(trigger, { relatedTarget: null });
    expect(screen.getByRole("group", { name: "Display settings" })).toBe(panel);
    await userEvent.click(within(panel).getByText("Light"));
    expect(screen.getByRole("group", { name: "Display settings" })).toBeInTheDocument();
    expect(document.documentElement.dataset.themePref ?? window.localStorage.getItem("sparta.theme")).toBeTruthy();
    expect(within(panel).getByRole("radio", { name: "Light" })).toBeChecked();
  });

  it("closes when the owner clicks elsewhere, tabs to another control, or presses Escape (focus returns to the button)", async () => {
    const { trigger } = await openMenu();
    await userEvent.click(screen.getByText("Somewhere else"));
    expect(screen.queryByRole("group", { name: "Display settings" })).toBeNull();

    await userEvent.click(trigger);
    expect(screen.getByRole("group", { name: "Display settings" })).toBeInTheDocument();
    fireEvent.blur(trigger, { relatedTarget: screen.getByText("Somewhere else") });
    expect(screen.queryByRole("group", { name: "Display settings" })).toBeNull();

    await userEvent.click(trigger);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: "Display settings" })).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("offers the manual reduced-motion switch", async () => {
    const { panel } = await openMenu();
    const reduce = within(panel).getByRole("switch", { name: /^Reduce motion/ });
    await userEvent.click(reduce);
    expect(document.documentElement.dataset.motion).toBe("reduce");
    expect(reduce).toBeChecked();
  });
});

describe("DevBanner", () => {
  it("shows the persistent Development identity banner when the API says dev_banner: true", async () => {
    renderWithApp(<DevBanner />);
    const banner = await screen.findByRole("complementary", { name: "Development identity" });
    expect(banner).toHaveTextContent("Development identity");
    expect(await within(banner).findByText("dev-owner")).toBeInTheDocument();
    // it cannot be dismissed: the only control is "Switch identity"
    expect(within(banner).getAllByRole("button")).toHaveLength(1);
    expect(within(banner).queryByRole("button", { name: /close|dismiss|hide/i })).toBeNull();
  });

  it("is hidden when the API reports real authentication", async () => {
    const api = createFakeApi({ ...makeAssistantRoutes(), "GET /api/v1/system/status": () => makeStatus({ dev_banner: false, auth_mode: "oidc" }) });
    renderWithApp(<DevBanner />, { api });
    await waitFor(() => expect(api.callsTo("GET /api/v1/system/status")).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Development identity" })).toBeNull());
  });

  it("still warns while the API is unreachable (dev mode is the configured default)", async () => {
    const api = createFakeApi({ "GET /api/v1/system/status": () => apiError(503, "provider_unavailable", "down"), "GET /api/v1/me": () => apiError(503, "provider_unavailable", "down") });
    renderWithApp(<DevBanner />, { api });
    expect(await screen.findByRole("complementary", { name: "Development identity" })).toBeInTheDocument();
  });

  it("lets the tester switch identity (X-Sparta-Dev-User) and validates the value", async () => {
    const reload = vi.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { ...window.location, reload } });
    renderWithApp(<DevBanner />);
    await userEvent.click(await screen.findByRole("button", { name: "Switch identity" }));
    const dialog = await findOpenDialog();
    const input = within(dialog).getByLabelText("Identity");
    await userEvent.type(input, "bad name!");
    expect(within(dialog).getByText("Use only letters, digits, '.', '_' or '-'.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Switch" })).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "alice-2");
    await userEvent.click(within(dialog).getByRole("button", { name: "Switch" }));
    expect(window.localStorage.getItem("sparta.dev_user")).toBe("alice-2");
    expect(reload).toHaveBeenCalled();
  });
});

describe("provider badges (honesty: real vs simulated)", () => {
  it("labels a simulated provider as SIMULATED and a real one as Real", () => {
    const { unmount } = renderWithApp(<SimulationBadge simulated provider="simulator" />);
    expect(screen.getByText("Simulated")).toBeInTheDocument();
    unmount();
    renderWithApp(<SimulationBadge simulated={false} provider="azure" />);
    expect(screen.getByText("Real · Azure")).toBeInTheDocument();
  });

  it("derives the app-wide badge from /system/status and explains it to screen readers", async () => {
    renderWithApp(<SystemProviderBadge />);
    expect(await screen.findByText("Simulated")).toBeInTheDocument();
    expect(screen.getByText(/Calls are simulated; no real phone call is involved/)).toBeInTheDocument();
  });

  it("says when the API is offline instead of guessing", async () => {
    const api = createFakeApi({ "GET /api/v1/system/status": () => apiError(503, "provider_unavailable", "down") });
    renderWithApp(<SystemProviderBadge />, { api });
    expect(await screen.findByText("API offline")).toBeInTheDocument();
  });
});

describe("AppShell", () => {
  it("has landmarks, a skip link, primary navigation with the current page marked, and the dev banner", async () => {
    nav.pathname = "/calls/call_1";
    renderWithApp(
      <AppShell>
        <h1>Call detail</h1>
      </AppShell>,
    );
    const skip = screen.getByRole("link", { name: "Skip to main content" });
    expect(skip).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    const navs = screen.getAllByRole("navigation", { name: "Primary" });
    expect(navs.length).toBeGreaterThanOrEqual(1);
    for (const navigation of navs) expect(within(navigation).getByRole("link", { name: /history/i })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(await screen.findByRole("complementary", { name: "Development identity" })).toBeInTheDocument();
  });

  it("sends an owner who has not finished setup to onboarding, unless they skipped it this session", async () => {
    nav.pathname = "/";
    nav.replace.mockClear();
    const api = createFakeApi({ ...makeAssistantRoutes(), "GET /api/v1/preferences": () => makePreferences({ onboarding_completed: false }) });
    const { unmount } = renderWithApp(<AppShell>content</AppShell>, { api });
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/onboarding"));
    unmount();

    nav.replace.mockClear();
    window.sessionStorage.setItem("sparta.onboarding.skipped", "1");
    renderWithApp(<AppShell>content</AppShell>, { api });
    await waitFor(() => expect(api.callsTo("GET /api/v1/preferences").length).toBeGreaterThan(1));
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("hides the navigation chrome during onboarding and shows an API-offline notice with retry", async () => {
    nav.pathname = "/onboarding";
    const api = createFakeApi({ "GET /api/v1/system/status": () => apiError(503, "provider_unavailable", "The API is down"), "GET /api/v1/me": () => apiError(503, "x", "x"), "GET /api/v1/preferences": () => makePreferences() });
    renderWithApp(<AppShell>content</AppShell>, { api });
    expect(screen.queryByRole("navigation", { name: "Primary" })).toBeNull();
    const alert = await screen.findByText(/Can't reach the Sparta API/);
    expect(alert).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
