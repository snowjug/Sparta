import type { User } from "oidc-client-ts";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createOidcAuth, isOidcAuth, readOidcConfig, type UserManagerLike } from "./oidc";
import { createDevAuth } from "./dev";

// The OIDC adapter is tested against a fake UserManager: it has NOT been run against a real identity provider or tenant.

function user(overrides: Record<string, unknown> = {}): User {
  return { access_token: "tok-123", expired: false, profile: { sub: "u1", name: "Atharv" }, state: undefined, ...overrides } as unknown as User;
}

function fakeManager(initial: User | null = null) {
  let current = initial;
  const listeners: Record<"loaded" | "unloaded" | "expired", Array<() => void>> = { loaded: [], unloaded: [], expired: [] };
  const manager: UserManagerLike = {
    getUser: vi.fn(async () => current),
    signinRedirect: vi.fn(async () => undefined),
    signinRedirectCallback: vi.fn(async () => user({ state: { returnTo: "/calls/call_1" } })),
    signoutRedirect: vi.fn(async () => undefined),
    removeUser: vi.fn(async () => {
      current = null;
    }),
    events: {
      addUserLoaded: (callback) => listeners.loaded.push(callback),
      addUserUnloaded: (callback) => listeners.unloaded.push(callback),
      addAccessTokenExpired: (callback) => listeners.expired.push(callback),
    },
  };
  return {
    manager,
    load: async () => manager,
    set: (next: User | null) => {
      current = next;
    },
    fire: (event: "loaded" | "unloaded" | "expired") => listeners[event].forEach((callback) => callback()),
  };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => vi.unstubAllEnvs());

describe("readOidcConfig", () => {
  it("builds the config from the build-time variables and this app's own origin", () => {
    vi.stubEnv("NEXT_PUBLIC_OIDC_AUTHORITY", " https://login.example.com/tenant ");
    vi.stubEnv("NEXT_PUBLIC_OIDC_CLIENT_ID", "sparta-web");
    expect(readOidcConfig("https://app.example.com")).toEqual({
      authority: "https://login.example.com/tenant",
      clientId: "sparta-web",
      scope: "openid profile",
      redirectUri: "https://app.example.com/auth/callback",
      postLogoutRedirectUri: "https://app.example.com",
    });
    vi.stubEnv("NEXT_PUBLIC_OIDC_SCOPE", "openid profile api://sparta/access");
    expect(readOidcConfig("https://app.example.com")?.scope).toBe("openid profile api://sparta/access");
  });

  it("is null unless both the authority and the client id are set", () => {
    vi.stubEnv("NEXT_PUBLIC_OIDC_AUTHORITY", "https://login.example.com");
    vi.stubEnv("NEXT_PUBLIC_OIDC_CLIENT_ID", "");
    expect(readOidcConfig("https://app.example.com")).toBeNull();
  });
});

describe("createOidcAuth", () => {
  it("sends the access token as a bearer credential, and nothing when signed out or expired", async () => {
    expect(await createOidcAuth(fakeManager(user()).load).getAuthHeaders()).toEqual({ Authorization: "Bearer tok-123" });
    expect(await createOidcAuth(fakeManager(null).load).getAuthHeaders()).toEqual({});
    expect(await createOidcAuth(fakeManager(user({ expired: true })).load).getAuthHeaders()).toEqual({});
  });

  it("publishes the session: loading first, then signed in with a display name, and follows the library's events", async () => {
    const { load, set, fire } = fakeManager(user());
    const auth = createOidcAuth(load);
    expect(auth.getSession()).toEqual({ status: "loading", name: null });
    const changed = vi.fn();
    auth.subscribe(changed);
    await settle();
    expect(auth.getSession()).toEqual({ status: "signed_in", name: "Atharv" });
    expect(changed).toHaveBeenCalledTimes(1);

    set(user({ expired: true })); // the access token expired
    fire("expired");
    await settle();
    expect(auth.getSession()).toEqual({ status: "signed_out", name: null });
    expect(changed).toHaveBeenCalledTimes(2);
  });

  it("falls back from name to preferred_username to email, or no name at all", async () => {
    for (const [profile, expected] of [
      [{ preferred_username: "atharv@example.com" }, "atharv@example.com"],
      [{ email: "a@example.com" }, "a@example.com"],
      [{ sub: "u1" }, null],
    ] as const) {
      const auth = createOidcAuth(fakeManager(user({ profile })).load);
      await settle();
      expect(auth.getSession().name).toBe(expected);
    }
  });

  it("redirects to sign in and remembers only one of this app's own routes", async () => {
    const { manager, load } = fakeManager();
    const auth = createOidcAuth(load);
    await auth.signIn("/calls/call_1");
    expect(manager.signinRedirect).toHaveBeenLastCalledWith({ state: { returnTo: "/calls/call_1" } });
    await auth.signIn("https://evil.example/steal");
    expect(manager.signinRedirect).toHaveBeenLastCalledWith({ state: { returnTo: "/" } });
    await auth.signIn();
    expect(manager.signinRedirect).toHaveBeenLastCalledWith({ state: { returnTo: "/" } });
  });

  it("completes the code exchange and returns the stored route, never an off-site one", async () => {
    const { manager, load, set } = fakeManager();
    const auth = createOidcAuth(load);
    manager.signinRedirectCallback = vi.fn(async () => {
      set(user());
      return user({ state: { returnTo: "/calls/call_1" } });
    });
    await expect(auth.completeSignIn()).resolves.toBe("/calls/call_1");
    expect(auth.getSession().status).toBe("signed_in");

    manager.signinRedirectCallback = vi.fn(async () => user({ state: { returnTo: "//evil.example" } }));
    await expect(auth.completeSignIn()).resolves.toBe("/");
    manager.signinRedirectCallback = vi.fn(async () => user({ state: undefined }));
    await expect(auth.completeSignIn()).resolves.toBe("/");
  });

  it("surfaces a failed code exchange to the caller", async () => {
    const { manager, load } = fakeManager();
    manager.signinRedirectCallback = vi.fn(async () => Promise.reject(new Error("No matching state found in storage")));
    await expect(createOidcAuth(load).completeSignIn()).rejects.toThrow("No matching state found in storage");
  });

  it("signs out locally and at the identity provider; a provider without an end-session endpoint still signs out", async () => {
    const { manager, load } = fakeManager(user());
    const auth = createOidcAuth(load);
    await settle();
    await auth.signOut();
    expect(manager.removeUser).toHaveBeenCalled();
    expect(manager.signoutRedirect).toHaveBeenCalled();
    expect(auth.getSession().status).toBe("signed_out");

    const noEndSession = fakeManager(user());
    noEndSession.manager.signoutRedirect = vi.fn(async () => Promise.reject(new Error("no end_session_endpoint")));
    await expect(createOidcAuth(noEndSession.load).signOut()).resolves.toBeUndefined();
  });

  it("loads the library lazily, once, and only when it is needed", async () => {
    const { manager } = fakeManager(user());
    const load = vi.fn(async () => manager);
    const auth = createOidcAuth(load);
    await settle();
    await auth.getAuthHeaders();
    await auth.getAuthHeaders();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("is inert without a loader (server rendering, or OIDC not configured)", async () => {
    const auth = createOidcAuth(null);
    expect(auth.configured).toBe(false);
    expect(auth.getSession()).toEqual({ status: "loading", name: null });
    expect(await auth.getAuthHeaders()).toEqual({});
    await expect(auth.signIn("/")).rejects.toThrow("not configured");
    expect(createOidcAuth(null, true).configured).toBe(true);
  });

  it("is told apart from development authentication", () => {
    expect(isOidcAuth(createOidcAuth(null))).toBe(true);
    expect(isOidcAuth(createDevAuth())).toBe(false);
  });
});
