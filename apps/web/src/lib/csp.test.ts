import { describe, expect, it } from "vitest";
import { buildContentSecurityPolicy, connectOrigins, createNonce } from "./csp";

function directive(policy: string, name: string): string[] {
  const found = policy.split("; ").find((part) => part.startsWith(`${name} `) || part === name);
  return found ? found.split(" ").slice(1) : [];
}

describe("Content-Security-Policy", () => {
  const nonce = "abc123==";

  it("production: scripts need the nonce, nothing inline-unsafe, nothing framed, no plugins", () => {
    const policy = buildContentSecurityPolicy({ nonce, dev: false, apiBaseUrl: "http://localhost:8000" });
    expect(directive(policy, "script-src")).toEqual(["'self'", `'nonce-${nonce}'`, "'strict-dynamic'"]);
    expect(directive(policy, "style-src")).toEqual(["'self'", `'nonce-${nonce}'`]);
    expect(policy).not.toContain("unsafe-eval");
    expect(policy).not.toContain("unsafe-inline");
    expect(directive(policy, "object-src")).toEqual(["'none'"]);
    expect(directive(policy, "frame-ancestors")).toEqual(["'none'"]);
    expect(directive(policy, "base-uri")).toEqual(["'self'"]);
    expect(directive(policy, "default-src")).toEqual(["'self'"]);
  });

  it("lets the browser call only this origin and the Sparta API over HTTP and WebSocket", () => {
    const policy = buildContentSecurityPolicy({ nonce, dev: false, apiBaseUrl: "http://localhost:8100/" });
    expect(directive(policy, "connect-src")).toEqual(["'self'", "http://localhost:8100", "ws://localhost:8100"]);
    expect(policy).not.toContain("upgrade-insecure-requests");
  });

  it("uses wss and upgrades insecure requests when the API is https; adds an OIDC authority", () => {
    const policy = buildContentSecurityPolicy({ nonce, dev: false, apiBaseUrl: "https://api.sparta.example/v1", extraConnectOrigins: ["https://login.example.com/tenant/", ""] });
    expect(directive(policy, "connect-src")).toEqual(["'self'", "https://api.sparta.example", "wss://api.sparta.example", "https://login.example.com"]);
    expect(policy).toContain("upgrade-insecure-requests");
  });

  it("development additionally allows eval and inline styles for the Next.js dev tooling", () => {
    const policy = buildContentSecurityPolicy({ nonce, dev: true, apiBaseUrl: "http://localhost:8000" });
    expect(directive(policy, "script-src")).toContain("'unsafe-eval'");
    expect(directive(policy, "style-src")).toContain("'unsafe-inline'");
  });

  it("ignores an invalid API URL instead of throwing", () => {
    expect(connectOrigins("not a url")).toEqual(["'self'"]);
    expect(() => buildContentSecurityPolicy({ nonce, dev: false, apiBaseUrl: "" })).not.toThrow();
  });

  it("creates unguessable, unique, base64 nonces", () => {
    const first = createNonce();
    const second = createNonce();
    expect(first).toMatch(/^[A-Za-z0-9+/]{22}==$/);
    expect(first).not.toBe(second);
  });
});
