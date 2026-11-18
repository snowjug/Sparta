import type { User } from "oidc-client-ts";
import { safeRoute } from "../routes";
import type { AuthAdapter } from "./dev";

/**
 * OIDC sign-in (authorization code flow with PKCE) through `oidc-client-ts`.
 *
 * NOT VERIFIED against a live identity provider or tenant: it is unit-tested with a fake UserManager only. The access token is
 * sent as `Authorization: Bearer <token>` (the same header the API expects in production) and is kept in sessionStorage, so it
 * is gone when the tab closes. There is no silent renewal: an expired token returns the owner to the sign-in screen.
 * The library is loaded with a dynamic import, so it is never part of the first-load JavaScript of a development build.
 */
export interface OidcConfig {
  authority: string;
  clientId: string;
  scope: string;
  redirectUri: string;
  postLogoutRedirectUri: string;
}

export function isOidcConfigured(): boolean {
  return readOidcConfig("http://localhost") !== null;
}

/** `NEXT_PUBLIC_*` are inlined at build time (public by design: the client id is not a secret, and there is no client secret). */
export function readOidcConfig(origin: string): OidcConfig | null {
  const authority = process.env.NEXT_PUBLIC_OIDC_AUTHORITY?.trim();
  const clientId = process.env.NEXT_PUBLIC_OIDC_CLIENT_ID?.trim();
  if (!authority || !clientId) return null;
  return {
    authority,
    clientId,
    scope: process.env.NEXT_PUBLIC_OIDC_SCOPE?.trim() || "openid profile",
    redirectUri: `${origin}/auth/callback`,
    postLogoutRedirectUri: origin,
  };
}

/** The part of `UserManager` this app uses (so tests can supply a fake). */
export interface UserManagerLike {
  getUser(): Promise<User | null>;
  signinRedirect(args?: { state?: unknown }): Promise<void>;
  signinRedirectCallback(): Promise<User>;
  signoutRedirect(): Promise<void>;
  removeUser(): Promise<void>;
  events: {
    addUserLoaded(callback: () => void): void;
    addUserUnloaded(callback: () => void): void;
    addAccessTokenExpired(callback: () => void): void;
  };
}

export type UserManagerLoader = () => Promise<UserManagerLike>;

export function createUserManagerLoader(config: OidcConfig): UserManagerLoader {
  return async () => {
    const { UserManager, WebStorageStateStore } = await import("oidc-client-ts");
    return new UserManager({
      authority: config.authority,
      client_id: config.clientId,
      redirect_uri: config.redirectUri,
      post_logout_redirect_uri: config.postLogoutRedirectUri,
      response_type: "code",
      scope: config.scope,
      // Tokens live in sessionStorage (per tab, cleared on close), never in localStorage.
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
      stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
      automaticSilentRenew: false,
      loadUserInfo: false,
    });
  };
}

export type OidcStatus = "loading" | "signed_out" | "signed_in";

export interface OidcSession {
  status: OidcStatus;
  name: string | null;
}

export interface OidcAuthAdapter extends AuthAdapter {
  readonly mode: "oidc";
  /** False when NEXT_PUBLIC_AUTH_MODE=oidc but the authority or client id was not provided at build time. */
  readonly configured: boolean;
  getSession(): OidcSession;
  subscribe(listener: () => void): () => void;
  /** Redirects to the identity provider. `returnTo` is one of this app's own routes and is restored after sign-in. */
  signIn(returnTo?: string): Promise<void>;
  /** Called on /auth/callback: finishes the code exchange and returns the route to continue to. */
  completeSignIn(): Promise<string>;
  signOut(): Promise<void>;
}

export function isOidcAuth(adapter: AuthAdapter): adapter is OidcAuthAdapter {
  return adapter.mode === "oidc";
}

const SIGNED_OUT: OidcSession = { status: "signed_out", name: null };

function nameOf(user: User): string | null {
  const profile = user.profile as { name?: unknown; preferred_username?: unknown; email?: unknown };
  for (const value of [profile.name, profile.preferred_username, profile.email]) if (typeof value === "string" && value) return value;
  return null;
}

/**
 * `load` is null on the server (and when OIDC is not configured): the adapter then stays "loading"/inert so that
 * server rendering never touches browser storage.
 */
export function createOidcAuth(load: UserManagerLoader | null, configured: boolean = load !== null): OidcAuthAdapter {
  let session: OidcSession = { status: "loading", name: null };
  const listeners = new Set<() => void>();
  let loaded: Promise<UserManagerLike> | null = null;

  const publish = (next: OidcSession) => {
    if (next.status === session.status && next.name === session.name) return;
    session = next;
    for (const listener of listeners) listener();
  };

  // The manager is created on first use, and its events are followed from then on.
  function manager(): Promise<UserManagerLike | null> {
    if (!load) return Promise.resolve(null);
    loaded ??= load().then((instance) => {
      const onChange = () => void refresh();
      instance.events.addUserLoaded(onChange);
      instance.events.addUserUnloaded(onChange);
      instance.events.addAccessTokenExpired(onChange);
      return instance;
    });
    return loaded;
  }

  async function currentUser(): Promise<User | null> {
    const instance = await manager();
    if (!instance) return null;
    const user = await instance.getUser();
    return user && !user.expired ? user : null;
  }

  async function refresh(): Promise<void> {
    const user = await currentUser().catch(() => null);
    publish(user ? { status: "signed_in", name: nameOf(user) } : SIGNED_OUT);
  }

  async function required(): Promise<UserManagerLike> {
    const instance = await manager();
    if (!instance) throw new Error("OIDC is not configured");
    return instance;
  }

  if (load) void refresh();

  return {
    mode: "oidc",
    configured,
    async getAuthHeaders(): Promise<Record<string, string>> {
      const user = await currentUser();
      return user ? { Authorization: `Bearer ${user.access_token}` } : {};
    },
    getSession: () => session,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async signIn(returnTo) {
      const instance = await required();
      await instance.signinRedirect({ state: { returnTo: safeRoute(returnTo) } });
    },
    async completeSignIn() {
      const instance = await required();
      const user = await instance.signinRedirectCallback();
      await refresh();
      const state = user.state as { returnTo?: unknown } | null | undefined;
      return safeRoute(typeof state?.returnTo === "string" ? state.returnTo : "/");
    },
    async signOut() {
      const instance = await manager();
      if (!instance) return;
      await instance.removeUser();
      await refresh();
      // Ends the session at the identity provider too. Providers without an end-session endpoint just keep the local sign-out.
      await instance.signoutRedirect().catch(() => undefined);
    },
  };
}
