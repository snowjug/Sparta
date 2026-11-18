import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { expect } from "@playwright/test";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];

export interface AxeReport {
  serious: number;
  moderate: number;
  minor: number;
}

/**
 * Runs axe-core in the real browser (so colour contrast is computed from the rendered theme) and fails on any serious or
 * critical violation. Moderate and minor findings are returned so the caller can report them.
 */
export async function expectNoSeriousViolations(page: Page, label: string, options: { exclude?: string[] } = {}): Promise<AxeReport> {
  let builder = new AxeBuilder({ page }).withTags(TAGS);
  for (const selector of options.exclude ?? []) builder = builder.exclude(selector);
  const { violations } = await builder.analyze();
  const blocking = violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
  const summary = blocking.map((violation) => {
    const nodes = violation.nodes.slice(0, 5).map((node) => `${node.target.join(" ")}  ${node.html.slice(0, 140)}  ${node.any.map((check) => check.message).join("; ").slice(0, 200)}`);
    return `${violation.id} (${violation.impact}): ${violation.help}\n   ${nodes.join("\n   ")}`;
  });
  expect(summary, `axe: serious/critical violations on ${label}`).toEqual([]);
  return {
    serious: blocking.length,
    moderate: violations.filter((violation) => violation.impact === "moderate").length,
    minor: violations.filter((violation) => violation.impact === "minor").length,
  };
}
