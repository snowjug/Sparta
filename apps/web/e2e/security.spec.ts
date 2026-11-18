import { test as showcaseTest } from "./support/showcase";
import { API_ORIGIN, expect, test, WEB_ORIGIN } from "./support/test";

const PAGES = ["/", "/calls", "/studio", "/safety", "/simulator", "/live", "/onboarding"];

test.describe("security headers and content policy", () => {
  test("every document carries a nonce-based CSP that matches its scripts, plus nosniff, referrer, permissions and framing headers", async ({ request }) => {
    for (const path of PAGES) {
      const response = await request.get(path);
      expect(response.status(), path).toBe(200);
      const headers = response.headers();
      const csp = headers["content-security-policy"] ?? "";
      expect(csp, path).toContain("default-src 'self'");
      expect(csp, path).toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'(;|$)/);
      expect(csp, path).not.toContain("unsafe-eval");
      expect(csp, path).not.toContain("unsafe-inline");
      expect(csp, path).toContain("object-src 'none'");
      expect(csp, path).toContain("frame-ancestors 'none'");
      expect(csp, path).toContain("base-uri 'self'");
      expect(csp, path).toContain(`connect-src 'self' ${API_ORIGIN} ws://localhost:8100`);
      expect(headers["x-content-type-options"], path).toBe("nosniff");
      expect(headers["referrer-policy"], path).toBe("strict-origin-when-cross-origin");
      expect(headers["permissions-policy"], path).toContain("microphone=(self)");
      expect(headers["permissions-policy"], path).toContain("camera=()");
      expect(headers["x-frame-options"], path).toBe("DENY");
      expect(headers["x-powered-by"], path).toBeUndefined();

      const nonce = /'nonce-([^']+)'/.exec(csp)?.[1];
      expect(nonce, path).toBeTruthy();
      const html = await response.text();
      const scripts = [...html.matchAll(/<script\b[^>]*>/g)].map((match) => match[0]);
      expect(scripts.length, path).toBeGreaterThan(3);
      expect(scripts.every((tag) => tag.includes(`nonce="${nonce}"`)), `${path}: every <script> carries the nonce`).toBe(true);
      expect(html, path).not.toMatch(/\sstyle="/); // no inline style attributes (style-src has no 'unsafe-inline')
      expect(html, path).not.toMatch(/\son[a-z]+="/); // no inline event handlers
    }
  });

  test("the nonce is different on every request", async ({ request }) => {
    const nonces = new Set<string>();
    for (let i = 0; i < 5; i += 1) {
      const csp = (await request.get("/")).headers()["content-security-policy"] ?? "";
      nonces.add(/'nonce-([^']+)'/.exec(csp)![1]!);
    }
    expect(nonces.size).toBe(5);
  });

  test("the microphone is the only powerful feature the page may use", async ({ page }) => {
    await page.goto("/");
    const allowed = await page.evaluate(() => {
      const doc = document as unknown as { permissionsPolicy?: { allowsFeature(name: string): boolean }; featurePolicy?: { allowsFeature(name: string): boolean } };
      const policy = doc.permissionsPolicy ?? doc.featurePolicy;
      if (!policy) throw new Error("This browser does not expose the permissions policy");
      return { microphone: policy.allowsFeature("microphone"), camera: policy.allowsFeature("camera"), geolocation: policy.allowsFeature("geolocation"), payment: policy.allowsFeature("payment") };
    });
    expect(allowed).toEqual({ microphone: true, camera: false, geolocation: false, payment: false });
  });
});

test.describe("what the browser loads, stores and shows", () => {
  test("a tour of every screen: no CSP violation, no third-party request, only Sparta's own origins, no secrets in storage, no raw phone numbers", async ({ page, api }) => {
    test.setTimeout(150_000);
    const finished = await api.seedCall("bank-otp-en");
    const escalated = await api.seedEscalatedCall();
    await page.addInitScript(() => {
      const violations: string[] = [];
      document.addEventListener("securitypolicyviolation", (event) => violations.push(`${event.violatedDirective}: ${event.blockedURI}`));
      Object.assign(window, { __csp: violations });
    });
    const origins = new Set<string>();
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.protocol === "http:" || url.protocol === "https:") origins.add(url.origin);
    });
    // Playwright reports WebSockets separately from HTTP requests.
    const sockets: string[] = [];
    page.on("websocket", (socket) => {
      sockets.push(socket.url());
      origins.add(new URL(socket.url()).origin);
    });

    const routes = ["/", "/live", `/live/${escalated.id}`, "/calls", `/calls/${finished.id}`, "/studio", "/safety", "/simulator", "/onboarding"];
    for (const route of routes) {
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      // Phone numbers are shown masked only: a run of eight or more digits is never rendered (dates and generated ids are not numbers).
      const text = (await page.locator("body").innerText())
        .replace(/\b[a-z]+_[a-z0-9]+\b/gi, "")
        .replace(/\b[a-f0-9]{16,}\b/gi, "")
        .replace(/\b\d{4}-\d{2}-\d{2}\b/g, "");
      expect(/\d[\d\s-]{7,}\d/.exec(text)?.[0] ?? null, `${route}: a raw phone number is on screen`).toBeNull();
      expect(await page.evaluate(() => (window as unknown as { __csp: string[] }).__csp), `${route}: CSP violations`).toEqual([]);
    }

    // The live call opened its WebSocket to the API, with a single-use ticket and no credential in the URL.
    expect(sockets.length, "the live call opened a WebSocket").toBeGreaterThan(0);
    for (const url of sockets) {
      const parsed = new URL(url);
      expect(parsed.origin).toBe("ws://localhost:8100");
      expect([...parsed.searchParams.keys()]).toEqual(["ticket"]);
    }
    expect([...origins].sort()).toEqual([API_ORIGIN, "ws://localhost:8100", WEB_ORIGIN].sort());
    const storage = await page.evaluate(() => ({ local: Object.entries(localStorage), session: Object.entries(sessionStorage) }));
    for (const [key, value] of [...storage.local, ...storage.session]) {
      expect(key.startsWith("sparta."), `unexpected storage key ${key}`).toBe(true);
      expect(value, `storage value of ${key} looks like a token`).not.toMatch(/eyJ[\w-]{10,}\.|Bearer /i);
    }
  });

  showcaseTest("the development-identity banner is on every screen and cannot be dismissed", async ({ page, showcase }) => {
    for (const route of ["/", "/live", "/calls", `/calls/${showcase.bank.id}`, "/studio", "/safety", "/simulator", "/onboarding"]) {
      await page.goto(route);
      const banner = page.getByTestId("dev-banner");
      await expect(banner, route).toContainText("Development identity");
      await expect(banner, route).toContainText(showcase.ownerId);
      await expect(banner.getByRole("button"), route).toHaveCount(1);
      await expect(banner.getByRole("button", { name: "Switch identity" })).toBeVisible();
    }
    // Client-side navigation keeps it, too.
    await page.goto("/");
    await page.getByRole("navigation", { name: "Primary" }).first().getByRole("link", { name: /Safety/ }).click();
    await expect(page).toHaveURL(/\/safety$/);
    await expect(page.getByTestId("dev-banner")).toBeVisible();
  });

  showcaseTest("external links open safely", async ({ page }) => {
    for (const route of ["/", "/safety", "/studio", "/simulator"]) {
      await page.goto(route);
      const links = await page.locator("a[href]").evaluateAll((anchors) =>
        anchors.map((anchor) => ({ href: (anchor as HTMLAnchorElement).href, target: anchor.getAttribute("target"), rel: anchor.getAttribute("rel") ?? "" })),
      );
      for (const link of links) {
        if (!link.href.startsWith("http") || new URL(link.href).origin === location_origin(WEB_ORIGIN)) continue;
        expect(link.rel, `${route}: ${link.href}`).toMatch(/noopener/);
        expect(link.rel, `${route}: ${link.href}`).toMatch(/noreferrer/);
      }
    }
  });
});

test.describe("untrusted text", () => {
  test("a caller who sends HTML or script is shown as plain text everywhere and nothing runs", async ({ page, api }) => {
    const payload = `<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</script> **bold** <b>tag</b>`;
    const call = await api.startCall();
    await api.waitForSilence(call.id);
    await api.sendTurn(call.id, payload);
    await api.waitForSilence(call.id);

    for (const route of [`/live/${call.id}`, `/calls/${call.id}`]) {
      await page.goto(route);
      const turn = page.locator('[data-testid="turn"][data-speaker="caller"]');
      await expect(turn).toHaveCount(1);
      await expect(turn).toContainText('<img src=x onerror="window.__pwned=1">');
      await expect(turn).toContainText("<b>tag</b>");
      await expect(page.locator('img[src="x"]')).toHaveCount(0);
      await expect(turn.locator("b")).toHaveCount(0);
      expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
    }
  });
});

function location_origin(origin: string): string {
  return new URL(origin).origin;
}
