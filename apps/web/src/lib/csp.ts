/**
 * Content-Security-Policy builder. Pure so it can be unit-tested; src/proxy.ts calls it once per request with a fresh nonce.
 *
 * Production policy: scripts run only with the per-request nonce ('strict-dynamic' lets those scripts load their own
 * chunks), styles only from same-origin files or the nonce, nothing is framed, no plugins, and the browser may talk only to
 * this origin and to the Sparta API (HTTP and WebSocket) plus an optional OIDC authority.
 */
export interface CspOptions {
  nonce: string;
  /** Next.js dev server needs eval for React's debugging features and inline styles for its error overlay. */
  dev: boolean;
  apiBaseUrl: string;
  /** Additional origins the browser may call (for example the OIDC authority). */
  extraConnectOrigins?: readonly string[];
}

/** 128 random bits, base64 encoded. Works in the Node.js and Edge runtimes. */
export function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function parseOrigin(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

/** API origin plus the matching ws(s) origin (live call sockets). Invalid values are ignored rather than crashing every request. */
export function connectOrigins(apiBaseUrl: string, extra: readonly string[] = []): string[] {
  const origins = new Set<string>(["'self'"]);
  const api = parseOrigin(apiBaseUrl);
  if (api) {
    origins.add(api.origin);
    const socket = new URL(api.origin);
    socket.protocol = api.protocol === "https:" ? "wss:" : "ws:";
    origins.add(socket.origin);
  }
  for (const value of extra) {
    const parsed = value ? parseOrigin(value) : null;
    if (parsed) origins.add(parsed.origin);
  }
  return [...origins];
}

export function buildContentSecurityPolicy({ nonce, dev, apiBaseUrl, extraConnectOrigins = [] }: CspOptions): string {
  const api = parseOrigin(apiBaseUrl);
  const directives: Array<[string, ...string[]]> = [
    ["default-src", "'self'"],
    ["script-src", "'self'", `'nonce-${nonce}'`, "'strict-dynamic'", ...(dev ? ["'unsafe-eval'"] : [])],
    ["style-src", "'self'", ...(dev ? ["'unsafe-inline'"] : [`'nonce-${nonce}'`])],
    ["img-src", "'self'"],
    ["font-src", "'self'"],
    ["connect-src", ...connectOrigins(apiBaseUrl, extraConnectOrigins)],
    ["media-src", "'self'"],
    ["object-src", "'none'"],
    ["frame-src", "'none'"],
    ["base-uri", "'self'"],
    ["form-action", "'self'"],
    ["frame-ancestors", "'none'"],
  ];
  // Only when the API itself is served over https: upgrading would break a plain-http localhost API during development.
  if (api?.protocol === "https:") directives.push(["upgrade-insecure-requests"]);
  return directives.map((parts) => parts.join(" ")).join("; ");
}
