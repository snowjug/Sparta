import type { Locator, Page } from "@playwright/test";

/** The polite/assertive toast region (its name is distinct from the Studio's "Notifications" settings card). */
export function notifications(page: Page): Locator {
  return page.getByRole("region", { name: "Status messages", exact: true });
}

/** An open modal dialog, by accessible name. */
export function openDialog(page: Page, name: string | RegExp): Locator {
  return page.getByRole("dialog", { name });
}

/**
 * Switches, checkboxes and radios are a visually hidden input plus a drawn control inside a <label>: a person clicks the label,
 * so tests do too (Playwright refuses to click the 1px input because the drawn control sits on top of it).
 */
export function labelOf(control: Locator): Locator {
  return control.locator("xpath=ancestor::label[1]");
}

export async function toggleSwitch(page: Page, name: string | RegExp): Promise<void> {
  await labelOf(page.getByRole("switch", { name })).click();
}

/** Phone numbers are masked by the server with bullet or middle-dot characters; the app only ever shows that form. */
export const MASK_CHARS = /[•·]/;
