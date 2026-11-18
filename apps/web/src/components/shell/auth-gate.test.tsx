import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AccountChip, AuthGate } from "./auth-gate";
import { CallbackScreen } from "@/features/auth/callback-screen";
import { AuthProvider } from "@/lib/auth/provider";
import { createDevAuth } from "@/lib/auth/dev";
import type { OidcAuthAdapter, OidcSession } from "@/lib/auth/oidc";

const navigation = vi.hoisted(() => ({ pathname: "/calls", replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ replace: navigation.replace, push: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
}));

function fakeOidc(session: OidcSession, overrides: Partial<OidcAuthAdapter> = {}): OidcAuthAdapter {
  return {
    mode: "oidc",
    configured: true,
    getAuthHeaders: async () => ({}),
    getSession: () => session,
    subscribe: () => () => undefined,
    signIn: vi.fn(async () => undefined),
    completeSignIn: vi.fn(async () => "/calls/call_1"),
    signOut: vi.fn(async () => undefined),
    ...overrides,
  };
}

function renderGate(adapter: ReturnType<typeof fakeOidc> | ReturnType<typeof createDevAuth>) {
  return render(
    <AuthProvider adapter={adapter}>
      <AuthGate>
        <p>the app</p>
      </AuthGate>
      <AccountChip />
    </AuthProvider>,
  );
}

beforeEach(() => {
  navigation.pathname = "/calls";
  navigation.replace.mockClear();
});

describe("AuthGate (OIDC sign-in)", () => {
  it("shows the sign-in screen to a signed-out owner and starts the redirect from the current page", async () => {
    const adapter = fakeOidc({ status: "signed_out", name: null });
    renderGate(adapter);
    expect(screen.queryByText("the app")).toBeNull();
    expect(screen.getByRole("heading", { name: "Sign in to Sparta" })).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("sign-in-button"));
    expect(adapter.signIn).toHaveBeenCalledWith("/calls");
  });

  it("explains a failure to start sign-in instead of failing silently", async () => {
    renderGate(fakeOidc({ status: "signed_out", name: null }, { signIn: vi.fn(async () => Promise.reject(new Error("The identity provider could not be reached"))) }));
    await userEvent.click(screen.getByTestId("sign-in-button"));
    expect(await screen.findByRole("alert")).toHaveTextContent("The identity provider could not be reached");
  });

  it("shows a loading state while the stored session is read", () => {
    renderGate(fakeOidc({ status: "loading", name: null }));
    expect(screen.getByRole("status")).toHaveTextContent("Checking your sign-in");
    expect(screen.queryByText("the app")).toBeNull();
  });

  it("says plainly when OIDC is selected but not configured", () => {
    renderGate(fakeOidc({ status: "signed_out", name: null }, { configured: false }));
    expect(screen.getByTestId("oidc-not-configured")).toHaveTextContent("NEXT_PUBLIC_OIDC_AUTHORITY");
    expect(screen.queryByTestId("sign-in")).toBeNull();
  });

  it("shows the app, the account name and a sign-out button to a signed-in owner", async () => {
    const adapter = fakeOidc({ status: "signed_in", name: "Atharv" });
    renderGate(adapter);
    expect(screen.getByText("the app")).toBeInTheDocument();
    expect(screen.getByTestId("account-chip")).toHaveTextContent("Atharv");
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(adapter.signOut).toHaveBeenCalled();
  });

  it("always lets the OIDC redirect target render, because that is where sign-in is completed", () => {
    navigation.pathname = "/auth/callback";
    renderGate(fakeOidc({ status: "signed_out", name: null }));
    expect(screen.getByText("the app")).toBeInTheDocument();
  });

  it("does nothing for development authentication: no gate, no account chip", () => {
    renderGate(createDevAuth());
    expect(screen.getByText("the app")).toBeInTheDocument();
    expect(screen.queryByTestId("account-chip")).toBeNull();
    expect(screen.queryByTestId("sign-in")).toBeNull();
  });
});

describe("CallbackScreen", () => {
  it("finishes sign-in once and continues to the route the owner came from", async () => {
    const adapter = fakeOidc({ status: "loading", name: null });
    render(
      <AuthProvider adapter={adapter}>
        <CallbackScreen />
      </AuthProvider>,
    );
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/calls/call_1"));
    expect(adapter.completeSignIn).toHaveBeenCalledTimes(1);
  });

  it("explains a failed sign-in and offers a way back", async () => {
    const adapter = fakeOidc({ status: "loading", name: null }, { completeSignIn: vi.fn(async () => Promise.reject(new Error("No matching state found in storage"))) });
    render(
      <AuthProvider adapter={adapter}>
        <CallbackScreen />
      </AuthProvider>,
    );
    expect(await screen.findByTestId("callback-problem")).toHaveTextContent("No matching state found in storage");
    await userEvent.click(screen.getByRole("button", { name: "Back to sign in" }));
    expect(navigation.replace).toHaveBeenCalledWith("/");
  });

  it("sends a development-authentication visitor straight home", async () => {
    render(
      <AuthProvider adapter={createDevAuth()}>
        <CallbackScreen />
      </AuthProvider>,
    );
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
  });
});
