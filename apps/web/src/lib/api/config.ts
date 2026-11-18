export type AuthMode = "dev" | "oidc";

/** Inlined by Next.js at build time. Public by design: never put secrets in NEXT_PUBLIC_* variables. */
export function getApiBaseUrl(): string {
  const raw = process.env.NEXT_PUBLIC_API_BASE_URL;
  return (raw && raw.trim() ? raw.trim() : "http://localhost:8000").replace(/\/+$/, "");
}

export function getAuthMode(): AuthMode {
  return process.env.NEXT_PUBLIC_AUTH_MODE === "oidc" ? "oidc" : "dev";
}

/** http(s) API base -> matching ws(s) origin. */
export function toWebSocketBase(httpBase: string): string {
  const url = new URL(httpBase);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString().replace(/\/+$/, "");
}
