import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** WCAG 2.x contrast ratio between two #rrggbb colours. */
function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

const css = readFileSync(join(process.cwd(), "src", "app", "globals.css"), "utf8");

function tokens(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  expect(start, `${selector} block exists`).toBeGreaterThan(-1);
  const end = css.indexOf("}", start);
  const block = css.slice(start, end);
  const out: Record<string, string> = {};
  for (const match of block.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) out[match[1]!] = match[2]!;
  return out;
}

const themes = {
  dark: tokens(":root {"),
  light: tokens(':root[data-theme="light"] {'),
};

// Text pairs must reach 4.5:1 (WCAG AA); UI boundaries and focus indicators 3:1.
const TEXT_PAIRS: Array<[string, string]> = [
  ["text", "bg"],
  ["text", "surface"],
  ["text", "raised"],
  ["muted", "bg"],
  ["muted", "surface"],
  ["muted", "raised"],
  ["muted", "sunken"],
  ["accent", "bg"],
  ["accent", "surface"],
  ["accent", "raised"],
  ["accent-ink", "accent"],
  ["success", "surface"],
  ["success", "success-bg"],
  ["warning", "surface"],
  ["warning", "warning-bg"],
  ["danger", "surface"],
  ["danger", "danger-bg"],
  ["info", "surface"],
  ["info", "info-bg"],
  ["text", "success-bg"],
  ["text", "warning-bg"],
  ["text", "danger-bg"],
];

const UI_PAIRS: Array<[string, string]> = [
  ["line-strong", "surface"],
  ["line-strong", "bg"],
  ["focus", "bg"],
  ["focus", "surface"],
];

describe.each(Object.entries(themes))("design tokens (%s theme)", (_name, theme) => {
  it("defines every token used by the contrast checks", () => {
    for (const key of new Set([...TEXT_PAIRS, ...UI_PAIRS].flat())) expect(theme[key], `--${key}`).toBeDefined();
  });

  it.each(TEXT_PAIRS)("text %s on %s meets WCAG AA (4.5:1)", (fg, bg) => {
    expect(contrast(theme[fg]!, theme[bg]!)).toBeGreaterThanOrEqual(4.5);
  });

  it.each(UI_PAIRS)("%s against %s meets 3:1 for UI components and focus", (fg, bg) => {
    expect(contrast(theme[fg]!, theme[bg]!)).toBeGreaterThanOrEqual(3);
  });
});

describe("theme infrastructure", () => {
  it("keeps dark as the default and a no-JavaScript light fallback", () => {
    expect(css).toMatch(/:root\s*\{[^}]*color-scheme:\s*dark/);
    expect(css).toMatch(/@media \(prefers-color-scheme: light\)\s*\{\s*:root:not\(\[data-theme\]\)/);
  });

  it("neutralises animation for reduced motion, both from the OS and from the manual override", () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(css).toMatch(/\[data-motion="reduce"\]/);
  });
});
