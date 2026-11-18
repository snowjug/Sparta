// Rewrites every `resolved` URL in package-lock.json to the public npm registry.
// Needed when dependencies were installed through a corporate mirror: integrity hashes stay valid,
// and CI (which uses https://registry.npmjs.org) can `npm ci` from the committed lockfile.
//
//   node scripts/normalize-lockfile.mjs          rewrite in place
//   node scripts/normalize-lockfile.mjs --check  exit 1 if a rewrite is still needed
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PUBLIC_HOST = "registry.npmjs.org";
const lockPath = join(dirname(fileURLToPath(import.meta.url)), "..", "package-lock.json");
const checkOnly = process.argv.includes("--check");

const raw = readFileSync(lockPath, "utf8");
const lock = JSON.parse(raw);

function packageName(key, entry) {
  if (typeof entry.name === "string" && entry.name) return entry.name;
  const marker = "node_modules/";
  return key.slice(key.lastIndexOf(marker) + marker.length);
}

function canonicalUrl(key, entry) {
  const url = new URL(entry.resolved);
  if (url.host === PUBLIC_HOST) return entry.resolved;
  const file = url.pathname.split("/").pop();
  return `https://${PUBLIC_HOST}/${packageName(key, entry)}/-/${file}`;
}

let rewritten = 0;
for (const [key, entry] of Object.entries(lock.packages ?? {})) {
  if (!key || typeof entry.resolved !== "string" || !/^https?:/.test(entry.resolved)) continue;
  const next = canonicalUrl(key, entry);
  if (next !== entry.resolved) {
    entry.resolved = next;
    rewritten += 1;
  }
}

const output = `${JSON.stringify(lock, null, 2)}\n`;

if (checkOnly) {
  if (rewritten > 0) {
    console.error(`package-lock.json still has ${rewritten} resolved URLs that do not point at ${PUBLIC_HOST}: run \`npm run lock:normalize\`.`);
    process.exit(1);
  }
  console.log("package-lock.json is clean: every resolved URL points at registry.npmjs.org");
} else {
  writeFileSync(lockPath, output);
  console.log(`package-lock.json: rewrote ${rewritten} resolved URLs to https://${PUBLIC_HOST}/`);
}
