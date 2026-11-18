"use client";

import { createContext, useContext, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { getAuthMode } from "../api/config";
import { subscribeStorage } from "../storage";
import { createDevAuth, getStoredDevUser, setStoredDevUser, type AuthAdapter } from "./dev";
import { createOidcAuth, createUserManagerLoader, isOidcAuth, isOidcConfigured, readOidcConfig, type OidcSession } from "./oidc";

const AuthContext = createContext<AuthAdapter | null>(null);

export function AuthProvider({ children, adapter }: { children: ReactNode; adapter?: AuthAdapter }) {
  const value = useMemo<AuthAdapter>(() => adapter ?? createAuthAdapter(), [adapter]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthAdapter {
  const adapter = useContext(AuthContext);
  if (!adapter) throw new Error("useAuth must be used inside <AuthProvider>");
  return adapter;
}

/** Selected development identity (header `X-Sparta-Dev-User`). Null means the API's default dev identity. */
export function useDevUser() {
  const devUser = useSyncExternalStore(subscribeStorage, getStoredDevUser, () => null);
  return { devUser, setDevUser: setStoredDevUser };
}

const ALWAYS_SIGNED_IN: OidcSession = { status: "signed_in", name: null };

/** Sign-in state. Development authentication has no sign-in, so it is always "signed in". */
export function useAuthSession(): OidcSession {
  const adapter = useAuth();
  return useSyncExternalStore(
    (listener) => (isOidcAuth(adapter) ? adapter.subscribe(listener) : () => undefined),
    () => (isOidcAuth(adapter) ? adapter.getSession() : ALWAYS_SIGNED_IN),
    () => (isOidcAuth(adapter) ? adapter.getSession() : ALWAYS_SIGNED_IN),
  );
}

export function createAuthAdapter(): AuthAdapter {
  if (getAuthMode() !== "oidc") return createDevAuth();
  // On the server the OIDC adapter stays inert: it must not touch browser storage while rendering.
  if (typeof window === "undefined") return createOidcAuth(null, isOidcConfigured());
  const config = readOidcConfig(window.location.origin);
  return createOidcAuth(config ? createUserManagerLoader(config) : null, config !== null);
}

export { getAuthMode };
