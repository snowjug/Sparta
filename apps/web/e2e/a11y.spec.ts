import type { Page } from "@playwright/test";
import { expectNoSeriousViolations } from "./support/axe";
import { startLabCall } from "./support/lab";
import { expect, test as showcaseTest } from "./support/showcase";
import { test as ownTest } from "./support/test";
import { labelOf, openDialog } from "./support/ui";

const THEMES = ["dark", "light"] as const;
const AXE_RESULTS: string[] = [];

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState("networkidle");
  await expect(page.locator('[aria-busy="true"]')).toHaveCount(0);
}

// -------------------------------------------------------------------------------------------- axe: 8 screens x 2 themes

for (const theme of THEMES) {
  const audit = async (page: Page, label: string) => {
    const report = await expectNoSeriousViolations(page, `${label} (${theme})`);
    AXE_RESULTS.push(`${label} (${theme}): serious=${report.serious} moderate=${report.moderate} minor=${report.minor}`);
  };

  // The showcase owner is shared and read-only: its history must stay exactly as seeded for the exact-count tests in history.spec.ts.
  showcaseTest.describe(`axe-core in the ${theme} theme: no serious or critical violations`, () => {
    showcaseTest.use({ theme, colorScheme: theme });

    showcaseTest("A. Onboarding", async ({ page }) => {
      await page.goto("/onboarding");
      await expect(page.getByTestId("step-title")).toBeVisible();
      await settle(page);
      await audit(page, "Onboarding step 1");
      for (let step = 2; step <= 9; step += 1) {
        await page.getByTestId("onboarding-next").click();
        await expect(page.getByTestId("step-counter")).toHaveText(`Step ${step} of 9`);
        await settle(page);
        if ([2, 3, 5, 8, 9].includes(step)) await audit(page, `Onboarding step ${step}`);
      }
    });

    showcaseTest("B. Home", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByTestId("recent-list")).toBeVisible();
      await settle(page);
      await audit(page, "Home");
    });

    showcaseTest("D. Call history", async ({ page }) => {
      await page.goto("/calls");
      await expect(page.getByTestId("history-list")).toBeVisible();
      await settle(page);
      await audit(page, "Call history");
      await page.getByTestId("history-row").first().getByRole("button").first().click();
      await expect(page.getByTestId("history-details")).toBeVisible();
      await audit(page, "Call history with an expanded row");
    });

    showcaseTest("E. Call detail", async ({ page, showcase }) => {
      await page.goto(`/calls/${showcase.journey.id}`);
      await expect(page.getByTestId("summary-text")).toBeVisible();
      await settle(page);
      await audit(page, "Call detail");
    });

    showcaseTest("F. Assistant Studio", async ({ page }) => {
      await page.goto("/studio");
      await expect(page.getByTestId("disclosure-preview")).toBeVisible();
      await settle(page);
      await audit(page, "Assistant Studio");
    });

    showcaseTest("G. Safety Center", async ({ page }) => {
      await page.goto("/safety");
      await expect(page.getByTestId("protected-list")).toBeVisible();
      await expect(page.getByTestId("safety-event").first()).toBeVisible();
      await settle(page);
      await audit(page, "Safety Center");
    });

    showcaseTest("a modal dialog", async ({ page }) => {
      await page.goto("/");
      await page.getByRole("button", { name: "Switch identity" }).click();
      await expect(openDialog(page, "Switch development identity")).toBeVisible();
      await audit(page, "Dialog");
    });
  });

  // Screens that start calls use an owner of their own (a call would otherwise appear in the shared history).
  ownTest.describe(`axe-core in the ${theme} theme: no serious or critical violations`, () => {
    ownTest.use({ theme, colorScheme: theme });

    ownTest("C. Live call command center (escalation in progress) and the live index", async ({ page, api }) => {
      const call = await api.seedEscalatedCall();
      await page.goto("/live");
      await expect(page.getByTestId("active-calls")).toBeVisible();
      await settle(page);
      await audit(page, "Live index");
      await page.goto(`/live/${call.id}`);
      await expect(page.getByTestId("escalation-banner")).toBeVisible();
      await expect(page.getByTestId("connection-pill")).toHaveAttribute("data-connection", "open");
      await settle(page);
      await page.locator("summary", { hasText: "Diagnostics" }).click();
      await audit(page, "Live call");
    });

    ownTest("H. Simulator Lab (setup and live console)", async ({ page }) => {
      await page.goto("/simulator");
      await expect(page.getByTestId("scenario-list")).toBeVisible();
      await settle(page);
      for (const summary of ["Custom scenario builder", "Deterministic replay", "Provider status"]) await page.locator("summary", { hasText: summary }).click();
      await audit(page, "Simulator Lab setup");
      await startLabCall(page);
      await expect(page.getByTestId("voice-stage")).toBeVisible();
      await page.locator("summary", { hasText: "Event log" }).click();
      await page.locator("summary", { hasText: "Diagnostics" }).click();
      await audit(page, "Simulator Lab console");
    });
  });
}

showcaseTest.afterAll(() => {
  if (AXE_RESULTS.length > 0) console.log(`axe results (${AXE_RESULTS.length} audits):\n  ${AXE_RESULTS.join("\n  ")}`);
});

// ------------------------------------------------------------------------------------------ keyboard and structure

showcaseTest.describe("keyboard and structure", () => {
  showcaseTest("the skip link is the first tab stop, becomes visible and moves focus to the main region", async ({ page }) => {
    await page.goto("/calls");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main")).toBeFocused();
  });

  showcaseTest("every screen has one main landmark, one level-one heading and labelled navigation", async ({ page, showcase }) => {
    for (const route of ["/", "/live", "/calls", `/calls/${showcase.bank.id}`, "/studio", "/safety", "/simulator"]) {
      await page.goto(route);
      await settle(page);
      await expect(page.getByRole("main"), route).toHaveCount(1);
      await expect(page.getByRole("heading", { level: 1 }), route).toHaveCount(1);
      await expect(page.getByRole("navigation", { name: "Primary" }), route).toHaveCount(1);
      await expect(page.getByRole("banner"), route).toHaveCount(1);
      await expect(page.getByRole("complementary", { name: "Development identity" }), route).toHaveCount(1);
      await expect(page.locator("html"), route).toHaveAttribute("lang", "en");
    }
  });

  showcaseTest("keyboard focus is always visible, on every kind of control", async ({ page }) => {
    for (const route of ["/", "/calls", "/studio", "/safety", "/simulator"]) {
      await page.goto(route);
      await settle(page);
      const missing: string[] = [];
      for (let stop = 0; stop < 25; stop += 1) {
        await page.keyboard.press("Tab");
        const verdict = await page.evaluate(() => {
          const active = document.activeElement as HTMLElement | null;
          if (!active || active === document.body) return { ok: true, name: "body" };
          const visible = (el: Element | null) => {
            if (!el) return false;
            const style = getComputedStyle(el);
            const outline = style.outlineStyle !== "none" && Number.parseFloat(style.outlineWidth) > 0;
            const shadow = style.boxShadow !== "none";
            return outline || shadow;
          };
          // A native date field has several internal tab stops (day, month, year, picker button); the browser draws its own focus ring on them.
          if (active.tagName === "INPUT" && (active as HTMLInputElement).type === "date") return { ok: true, name: "date input" };
          // Visually hidden inputs (switch, radio) draw their focus ring on the sibling control.
          const ring = visible(active) || visible(active.nextElementSibling) || visible(active.closest("label")?.querySelector("span[aria-hidden='true']") ?? null);
          return { ok: ring, name: `${active.tagName.toLowerCase()} ${(active.getAttribute("aria-label") ?? active.textContent ?? "").trim().slice(0, 40)}` };
        });
        if (!verdict.ok) missing.push(verdict.name);
      }
      expect(missing, `${route}: controls without a visible focus indicator`).toEqual([]);
    }
  });

  showcaseTest("a dialog traps focus, closes with Escape and returns focus to its trigger", async ({ page }) => {
    await page.goto("/");
    const trigger = page.getByRole("button", { name: "Switch identity" });
    await trigger.click();
    const dialog = openDialog(page, "Switch development identity");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel("Identity")).toBeFocused();
    for (let press = 0; press < 12; press += 1) {
      await page.keyboard.press("Tab");
      expect(await dialog.evaluate((element) => element.contains(document.activeElement)), `Tab #${press + 1} stayed in the dialog`).toBe(true);
    }
    for (let press = 0; press < 6; press += 1) {
      await page.keyboard.press("Shift+Tab");
      expect(await dialog.evaluate((element) => element.contains(document.activeElement)), `Shift+Tab #${press + 1} stayed in the dialog`).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(trigger).toBeFocused();
  });

  showcaseTest("History can be operated with the keyboard alone: filter, expand a row, open the call", async ({ page, api }) => {
    await page.goto("/calls");
    await settle(page);
    await page.getByLabel("Risk").focus();
    await page.keyboard.press("ArrowDown"); // a native select changes with the arrow keys
    await expect(page).toHaveURL(/risk_level=/);
    await page.getByLabel("Risk").selectOption("high");
    await expect(page).toHaveURL(/risk_level=high/);
    const high = await api.get<{ items: unknown[] }>("calls?risk_level=high&limit=100");
    await expect(page.getByTestId("history-row")).toHaveCount(high.items.length);
    await settle(page);

    const first = page.getByTestId("history-row").first().locator("button[aria-expanded]").first();
    await first.focus();
    await page.keyboard.press("Enter");
    await expect(first).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter"); // "Open call" link
    await expect(page).toHaveURL(/\/calls\/call_/);
  });

  showcaseTest("segmented radio groups follow the arrow keys", async ({ page }) => {
    await page.goto("/studio");
    await expect(page.getByTestId("disclosure-preview")).toBeVisible();
    const balanced = page.getByRole("radio", { name: /Balanced/ });
    await balanced.focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("radio", { name: /Strict/ })).toBeChecked();
    await expect(page.getByTestId("save-bar")).toBeVisible();
  });

  // Starts a call, so it uses an owner of its own (the shared showcase history is read-only).
  ownTest("live regions: the transcript is polite, an escalation is an assertive alert, the stage and the risk level are announced as status", async ({ page, api }) => {
    const call = await api.seedEscalatedCall();
    await page.goto(`/live/${call.id}`);
    await expect(page.getByTestId("escalation-banner")).toHaveAttribute("role", "alert");
    const transcript = page.getByTestId("live-transcript");
    expect(await transcript.evaluate((element) => (element.closest("[aria-live]") ?? element).getAttribute("aria-live"))).toBe("polite");
    await expect(page.getByTestId("voice-stage-label")).toHaveAttribute("aria-live", "polite");
    await expect(page.getByTestId("risk-announcer")).toHaveAttribute("role", "status");
    await expect(page.getByTestId("connection-pill")).toHaveAttribute("data-connection", "open");
  });

  showcaseTest("information is never carried by colour alone: risk, state and signals always have a text label", async ({ page, showcase }) => {
    await page.goto(`/calls/${showcase.journey.id}`);
    await expect(page.getByTestId("risk-meter")).toContainText(/high|critical/i);
    for (const item of await page.getByTestId("signal-item").all()) await expect(item).not.toHaveText("");
    await page.goto("/calls");
    for (const badge of await page.getByTestId("history-row").first().locator("span", { hasText: /risk|low|medium|high|critical|unknown/i }).all()) {
      await expect(badge).not.toHaveText("");
    }
  });
});

// -------------------------------------------------------------------------------------------------- touch targets

// An owner with its own data: the page loads of a nine-screen sweep must not eat the shared showcase owner's rate limit (240 requests a minute).
ownTest.describe("touch targets on a phone", () => {
  ownTest.use({ viewport: { width: 375, height: 812 }, hasTouch: true });

  ownTest("every operable control is at least 44 x 44 px on all screens", async ({ page, api }) => {
    ownTest.setTimeout(240_000);
    const finished = await api.seedCall("bank-otp-en");
    const escalated = await api.seedEscalatedCall();
    const routes = ["/", "/live", `/live/${escalated.id}`, "/calls", `/calls/${finished.id}`, "/studio", "/safety", "/simulator", "/onboarding"];
    const offenders: string[] = [];
    for (const route of routes) {
      await page.goto(route);
      await settle(page);
      if (route === "/calls") await page.getByTestId("history-row").first().getByRole("button").first().click();
      for (const summary of await page.locator("summary").all()) await summary.click().catch(() => undefined);
      const found = await page.evaluate(() => {
        const MIN = 44;
        const out: string[] = [];
        const controls = document.querySelectorAll<HTMLElement>('button, a[href], summary, select, textarea, input:not([type="hidden"]), [role="button"]');
        for (const element of controls) {
          const style = getComputedStyle(element);
          if (style.visibility === "hidden" || style.display === "none") continue;
          // A visually hidden input (switch, radio) and a small checkbox are operated through their label.
          const target = element instanceof HTMLInputElement && (element.classList.contains("sr-only") || element.type === "checkbox" || element.type === "radio") ? (element.closest("label") ?? element) : element;
          const rect = target.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) continue;
          // Links inside running text are exempt (WCAG 2.5.8, inline exception).
          if (element.tagName === "A" && style.display === "inline" && element.closest("p, dd, li")) continue;
          if (element.closest("[class*='sr-only']") && element.tagName === "A") continue; // the skip link while hidden
          if (rect.width < MIN - 0.5 || rect.height < MIN - 0.5) {
            const name = (element.getAttribute("aria-label") ?? element.textContent ?? element.getAttribute("type") ?? "").trim().slice(0, 40);
            out.push(`${element.tagName.toLowerCase()} "${name}" is ${Math.round(rect.width)}x${Math.round(rect.height)}`);
          }
        }
        return out;
      });
      offenders.push(...found.map((item) => `${route}: ${item}`));
    }
    expect([...new Set(offenders)], "controls smaller than 44 x 44 px").toEqual([]);
  });
});

// ------------------------------------------------------------------------------------- theme and motion preferences

ownTest.describe("theme and motion preferences", () => {
  ownTest.use({ theme: "system" });

  ownTest("system theme follows the operating system live; a manual choice wins, persists and is applied before first paint", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator("html")).toHaveAttribute("data-theme-pref", "system");
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

    await page.getByRole("button", { name: /Display settings/ }).click();
    await labelOf(page.getByRole("radio", { name: "Light" })).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    expect(await page.evaluate(() => localStorage.getItem("sparta.theme"))).toBe("light");

    await page.addInitScript(() => {
      document.addEventListener("DOMContentLoaded", () => Object.assign(window, { __themeAtParse: document.documentElement.dataset.theme }));
    });
    await page.reload();
    expect(await page.evaluate(() => (window as unknown as { __themeAtParse: string }).__themeAtParse)).toBe("light"); // before React hydrates
    await expect(page.locator("html")).toHaveAttribute("data-theme-pref", "light");
  });

  ownTest("reduced motion can also be forced by the owner and is remembered", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Display settings/ }).click();
    await labelOf(page.getByRole("switch", { name: "Reduce motion" })).click();
    await expect(page.locator("html")).toHaveAttribute("data-motion", "reduce");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-motion", "reduce");
  });
});
