// Reports first-load JavaScript per route (raw and gzip) from the production build, and lists chunks that are lazy-loaded.
// Next.js 16 (Turbopack) no longer prints these sizes, but it writes .next/diagnostics/route-bundle-stats.json.
// Usage: npm run build && npm run build:report
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const statsPath = join(root, ".next", "diagnostics", "route-bundle-stats.json");
if (!existsSync(statsPath)) {
  console.error("No build found. Run `npm run build` first.");
  process.exit(1);
}

const sizeCache = new Map();
function sizes(path) {
  const normalised = path.replaceAll("\\", "/");
  if (!sizeCache.has(normalised)) {
    const bytes = readFileSync(join(root, normalised));
    sizeCache.set(normalised, { raw: bytes.length, gzip: gzipSync(bytes, { level: 9 }).length });
  }
  return sizeCache.get(normalised);
}

const kb = (n) => `${(n / 1024).toFixed(1)} kB`;
const routes = JSON.parse(readFileSync(statsPath, "utf8")).sort((a, b) => a.route.localeCompare(b.route));

const firstLoad = new Set();
const rows = routes.map((entry) => {
  const chunks = [...new Set(entry.firstLoadChunkPaths.map((p) => p.replaceAll("\\", "/")))].filter((p) => p.endsWith(".js"));
  chunks.forEach((chunk) => firstLoad.add(chunk));
  const total = chunks.reduce((sum, chunk) => ({ raw: sum.raw + sizes(chunk).raw, gzip: sum.gzip + sizes(chunk).gzip }), { raw: 0, gzip: 0 });
  return { route: entry.route, chunks: chunks.length, ...total };
});

console.log("First-load JavaScript per route (shared chunks included once per route)");
console.log("route".padEnd(16), "chunks".padStart(6), "raw".padStart(11), "gzip".padStart(11));
for (const row of rows) console.log(row.route.padEnd(16), String(row.chunks).padStart(6), kb(row.raw).padStart(11), kb(row.gzip).padStart(11));

const chunkDir = join(root, ".next", "static", "chunks");
const walk = (dir) => readdirSync(dir).flatMap((name) => (statSync(join(dir, name)).isDirectory() ? walk(join(dir, name)) : [join(dir, name)]));
const lazy = walk(chunkDir)
  .filter((file) => file.endsWith(".js"))
  .map((file) => file.slice(root.length + 1).replaceAll("\\", "/"))
  .filter((file) => !firstLoad.has(file));

const markers = {
  "Simulator Lab (scenario builder, replay, audio upload)": "Custom scenario builder",
  "OIDC sign-in library (oidc-client-ts, only used when NEXT_PUBLIC_AUTH_MODE=oidc)": "signinRedirect",
};
console.log("\nLazy-loaded chunks (not part of any route's first load)");
for (const [label, marker] of Object.entries(markers)) {
  const hits = lazy.filter((file) => readFileSync(join(root, file), "utf8").includes(marker));
  for (const file of hits) console.log(`  ${label}: ${file}  ${kb(sizes(file).raw)} raw, ${kb(sizes(file).gzip)} gzip`);
  if (hits.length === 0) console.log(`  ${label}: not found as a lazy chunk (is it bundled into a first-load chunk?)`);
}
const lazyTotal = lazy.reduce((sum, file) => ({ raw: sum.raw + sizes(file).raw, gzip: sum.gzip + sizes(file).gzip }), { raw: 0, gzip: 0 });
console.log(`  all lazy chunks: ${lazy.length} files, ${kb(lazyTotal.raw)} raw, ${kb(lazyTotal.gzip)} gzip`);
