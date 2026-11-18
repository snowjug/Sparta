import { readStorage, STORAGE_KEYS, writeStorage } from "../storage";

export type AuthMode = "dev" | "oidc";

/** Supplies credentials for API calls. `dev` sends no credentials; `oidc` sends a bearer access token. */
export interface AuthAdapter {
  readonly mode: AuthMode;
  getAuthHeaders(): Promise<Record<string, string>>;
}

const DEV_USER_PATTERN = /^[A-Za-z0-9_.-]{1,40}$/;

export function isValidDevUser(value: string): boolean {
  return DEV_USER_PATTERN.test(value);
}

export function getStoredDevUser(): string | null {
  const stored = readStorage(STORAGE_KEYS.devUser);
  return stored && isValidDevUser(stored) ? stored : null;
}

export function setStoredDevUser(value: string | null): void {
  if (value !== null && !isValidDevUser(value)) throw new Error("Dev identity may only contain letters, digits, '.', '_' and '-' (max 40).");
  writeStorage(STORAGE_KEYS.devUser, value);
}

/**
 * Development auth: no credentials. The optional `X-Sparta-Dev-User` header selects another dev identity
 * (useful for checking that data is isolated between users). The API refuses dev auth in production.
 */
export function createDevAuth(readUser: () => string | null = getStoredDevUser): AuthAdapter {
  return {
    mode: "dev",
    async getAuthHeaders(): Promise<Record<string, string>> {
      const headers: Record<string, string> = {};
      const user = readUser();
      if (user) headers["X-Sparta-Dev-User"] = user;
      return headers;
    },
  };
}
