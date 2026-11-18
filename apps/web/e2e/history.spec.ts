import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import { expect, test as base } from "./support/test";
import { test as showcaseTest } from "./support/showcase";
import { toggleSwitch } from "./support/ui";

type CallPage = { items: Array<{ id: string }>; next_cursor: string | null };

const rows = (page: Page) => page.getByTestId("history-row");

showcaseTest.describe("call history (a realistic history: 3 rich calls + 20 short ones)", () => {
  showcaseTest("the first page has 20 calls and Load more fetches the rest with the cursor", async ({ page, showcase, api }) => {
    await page.goto("/calls");
    await expect(rows(page)).toHaveCount(20);
    const first = await api.get<CallPage>("calls?limit=20");
    expect(first.next_cursor).toBeTruthy();
    await expect(rows(page).first()).toHaveAttribute("data-call-id", first.items[0]!.id);

    const next = page.waitForRequest((request) => request.url().includes("cursor="));
    await page.getByTestId("load-more").click();
    await next;
    await expect(rows(page)).toHaveCount(3 + showcase.fillerCount);
    await expect(page.getByTestId("load-more")).toHaveCount(0);
    await expect(page.getByTestId("history-count")).toContainText(String(3 + showcase.fillerCount));
    const ids = await rows(page).evaluateAll((items) => items.map((item) => item.getAttribute("data-call-id")));
    expect(new Set(ids).size).toBe(ids.length); // no duplicates across pages
  });

  showcaseTest("search (q) narrows the list and matches what the API returns for the same query", async ({ page, api, showcase }) => {
    await page.goto("/calls");
    await expect(rows(page)).toHaveCount(20);
    await page.getByLabel("Search", { exact: true }).fill("State Bank");
    await expect(page).toHaveURL(/q=State(\+|%20)Bank/);
    const expected = (await api.get<CallPage>("calls?q=State%20Bank&limit=100")).items.map((item) => item.id);
    expect(expected).toContain(showcase.bank.id);
    await expect(rows(page)).toHaveCount(expected.length);
    await expect(rows(page).first()).toHaveAttribute("data-call-id", showcase.bank.id);

    await page.getByLabel("Search", { exact: true }).fill("zzz-no-such-caller");
    await expect(page.getByRole("heading", { name: "No calls match these filters" })).toBeVisible();
    await page.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(rows(page)).toHaveCount(20);
    await expect(page.getByLabel("Search", { exact: true })).toHaveValue("");
  });

  showcaseTest("risk, language, category, status and attention filters agree with the API and live in the URL", async ({ page, api, showcase }) => {
    const idsFor = async (query: string) => (await api.get<CallPage>(`calls?${query}&limit=100`)).items.map((item) => item.id).sort();
    const shown = async () => (await rows(page).evaluateAll((items) => items.map((item) => item.getAttribute("data-call-id") ?? ""))).sort();

    await page.goto("/calls");
    await page.getByLabel("Risk").selectOption("high");
    await expect(page).toHaveURL(/risk_level=high/);
    const high = await idsFor("risk_level=high");
    expect(high).toEqual(expect.arrayContaining([showcase.bank.id, showcase.journey.id]));
    await expect(rows(page)).toHaveCount(high.length);
    expect(await shown()).toEqual(high);

    await page.getByLabel("Risk").selectOption("");
    await page.getByLabel("Language").selectOption("hi-IN");
    const hindi = await idsFor("language=hi-IN");
    expect(hindi).toContain(showcase.journey.id);
    await expect(rows(page)).toHaveCount(hindi.length);
    expect(await shown()).toEqual(hindi);

    await page.getByLabel("Language").selectOption("");
    await page.getByLabel("Category").selectOption({ index: 1 });
    await expect(page).toHaveURL(/category=/);
    const category = new URL(page.url()).searchParams.get("category");
    expect(category).toBeTruthy();
    const byCategory = await idsFor(`category=${category}`);
    await expect(rows(page)).toHaveCount(byCategory.length);

    await page.goto("/calls?status=active");
    await expect(page.getByRole("heading", { name: "No calls match these filters" })).toBeVisible();

    // Deep links restore the filters.
    await page.goto("/calls?risk_level=high");
    await expect(page.getByLabel("Risk")).toHaveValue("high");
    await expect(rows(page)).toHaveCount(high.length);

    await page.goto("/calls");
    await toggleSwitch(page, "Needs my attention");
    await expect(page).toHaveURL(/attention=1/);
    const attention = await idsFor("attention=true");
    await expect(rows(page)).toHaveCount(attention.length);
  });

  showcaseTest("a date range includes today's calls and excludes other days", async ({ page }) => {
    const today = new Date().toLocaleDateString("en-CA"); // yyyy-mm-dd in the browser's locale/timezone
    const tomorrow = new Date(Date.now() + 36 * 3_600_000).toLocaleDateString("en-CA");
    await page.goto(`/calls?from=${today}&to=${today}`);
    await expect(rows(page).first()).toBeVisible();
    await page.goto(`/calls?from=${tomorrow}`);
    await expect(page.getByRole("heading", { name: "No calls match these filters" })).toBeVisible();
    await expect(page.getByLabel("From")).toHaveValue(tomorrow);
  });

  showcaseTest("a row expands in place, exports the call as JSON and opens the call detail", async ({ page, showcase }) => {
    await page.goto("/calls?risk_level=high");
    const row = page.locator(`[data-testid="history-row"][data-call-id="${showcase.bank.id}"]`);
    const first = row.locator("button[aria-expanded]").first();
    await first.click();
    await expect(first).toHaveAttribute("aria-expanded", "true");
    await expect(row.getByTestId("history-details")).toBeVisible();

    const [download] = await Promise.all([page.waitForEvent("download"), row.getByRole("button", { name: "Export JSON" }).click()]);
    expect(download.suggestedFilename()).toContain(showcase.bank.id);
    const exported = JSON.parse(readFileSync((await download.path())!, "utf8")) as { id?: string; call?: { id: string } };
    expect(exported.id ?? exported.call?.id).toBe(showcase.bank.id);

    await row.getByRole("link", { name: "Open call" }).click();
    await expect(page).toHaveURL(new RegExp(`/calls/${showcase.bank.id}$`));
  });
});

base.describe("history without calls", () => {
  base("a new owner sees a useful empty state that leads to the Simulator Lab", async ({ page }) => {
    await page.goto("/calls");
    await expect(page.getByRole("heading", { name: "No calls yet" })).toBeVisible();
    await page.getByRole("link", { name: "Run a simulated call" }).click();
    await expect(page).toHaveURL(/\/simulator$/);
  });
});
