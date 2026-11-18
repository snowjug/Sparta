// Prints the license of every installed package and flags anything that is not permissive.
//   npm run licenses            summary + direct dependencies + anything unusual
//   npm run licenses -- --all   every package
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const modules = join(root, "node_modules");
const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const direct = new Set([...Object.keys(manifest.dependencies ?? {}), ...Object.keys(manifest.devDependencies ?? {})]);
const production = new Set(Object.keys(manifest.dependencies ?? {}));

// Permissive licenses, plus MPL-2.0 (file-level copyleft: axe-core is test-only, lightningcss is a build tool; neither is shipped).
const PERMISSIVE = /^(MIT|ISC|0BSD|BSD-2-Clause|BSD-3-Clause|Apache-2\.0|BlueOak-1\.0\.0|CC0-1\.0|CC-BY-4\.0|Unlicense|Python-2\.0|MIT-0|WTFPL|Zlib)$/;
const REVIEWED = new Set(["MPL-2.0"]);
// sharp's prebuilt libvips (LGPL) is an optional dependency of Next for image optimisation. The app has no <Image>, never loads it,
// and the Dockerfile removes it from the image.
const REVIEWED_PACKAGES = (name) => name === "sharp" || name.startsWith("@img/sharp-");

function* packages() {
  for (const entry of readdirSync(modules, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
    if (entry.name.startsWith("@")) {
      for (const scoped of readdirSync(join(modules, entry.name), { withFileTypes: true })) if (scoped.isDirectory()) yield `${entry.name}/${scoped.name}`;
    } else yield entry.name;
  }
}

function licenseOf(info) {
  const raw = info.license ?? (Array.isArray(info.licenses) ? info.licenses.map((l) => l.type).join(" OR ") : undefined);
  return typeof raw === "object" && raw ? raw.type : (raw ?? "UNKNOWN");
}

function isPermissive(expression) {
  return expression
    .replace(/[()]/g, "")
    .split(/\s+(?:OR|AND)\s+/)
    .every((part) => PERMISSIVE.test(part.trim()));
}

const rows = [];
for (const name of packages()) {
  const file = join(modules, name, "package.json");
  if (!existsSync(file)) continue;
  const info = JSON.parse(readFileSync(file, "utf8"));
  rows.push({ name, version: info.version, license: licenseOf(info), direct: direct.has(name), production: production.has(name) });
}

const counts = new Map();
for (const row of rows) counts.set(row.license, (counts.get(row.license) ?? 0) + 1);
console.log(`${rows.length} installed packages`);
for (const [license, count] of [...counts].sort((a, b) => b[1] - a[1])) console.log(`  ${String(count).padStart(4)}  ${license}`);

const show = process.argv.includes("--all") ? rows : rows.filter((row) => row.direct);
console.log(`\n${process.argv.includes("--all") ? "All packages" : "Direct dependencies"}:`);
for (const row of show.sort((a, b) => a.name.localeCompare(b.name))) console.log(`  ${row.name.padEnd(34)} ${row.version.padEnd(10)} ${row.license}${row.production ? "  (runtime)" : ""}`);

const isReviewed = (row) => REVIEWED.has(row.license) || REVIEWED_PACKAGES(row.name);
const unusual = rows.filter((row) => !isPermissive(row.license));
console.log("\nNot on the permissive list (review each):");
if (unusual.length === 0) console.log("  none");
for (const row of unusual.sort((a, b) => a.name.localeCompare(b.name))) console.log(`  ${row.name.padEnd(34)} ${row.version.padEnd(10)} ${row.license}${isReviewed(row) ? "  (reviewed: not shipped)" : "  <-- NEEDS REVIEW"}`);
process.exitCode = unusual.some((row) => !isReviewed(row)) ? 1 : 0;
