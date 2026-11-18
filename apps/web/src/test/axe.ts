import axe from "axe-core";
import { expect } from "vitest";

/**
 * Runs axe-core on a rendered subtree and fails on serious or critical violations. jsdom has no layout or computed
 * colour, so contrast is checked separately (design-token test + Playwright axe in real browsers).
 */
export async function expectNoSeriousViolations(root: HTMLElement): Promise<void> {
  const results = await axe.run(root, {
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] },
    rules: {
      "color-contrast": { enabled: false },
      // Screens are rendered without the app shell here, so page-level landmark rules do not apply.
      region: { enabled: false },
      "landmark-one-main": { enabled: false },
      "page-has-heading-one": { enabled: false },
    },
  });
  const serious = results.violations
    .filter((violation) => violation.impact === "serious" || violation.impact === "critical")
    .map((violation) => `${violation.id} (${violation.impact}): ${violation.help}\n    ${violation.nodes.map((node) => node.html.slice(0, 160)).join("\n    ")}`);
  expect(serious, serious.join("\n")).toEqual([]);
}
