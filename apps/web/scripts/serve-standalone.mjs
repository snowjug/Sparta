// Runs the production server exactly as the Docker image does: `.next/standalone/server.js` with static assets copied next to it.
//   npm run start                              serve an existing build (`npm run build` first)
//   node scripts/serve-standalone.mjs --build  build first (used by the Playwright webServer so NEXT_PUBLIC_* match the E2E API)
// Environment: PORT (default 3000), HOSTNAME is forced to 127.0.0.1 unless SPARTA_WEB_HOST is set (Windows sets HOSTNAME to the machine name).
import { spawn, spawnSync } from "node:child_process";
import { cpSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const standalone = join(root, ".next", "standalone");

if (process.argv.includes("--build")) {
  const build = spawnSync(process.execPath, [join(root, "node_modules", "next", "dist", "bin", "next"), "build"], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
  });
  if (build.status !== 0) process.exit(build.status ?? 1);
}

if (!existsSync(join(standalone, "server.js"))) {
  console.error("No standalone build found. Run `npm run build` first.");
  process.exit(1);
}

cpSync(join(root, "public"), join(standalone, "public"), { recursive: true });
cpSync(join(root, ".next", "static"), join(standalone, ".next", "static"), { recursive: true });

const child = spawn(process.execPath, ["server.js"], {
  cwd: standalone,
  stdio: "inherit",
  env: { ...process.env, PORT: process.env.PORT ?? "3000", HOSTNAME: process.env.SPARTA_WEB_HOST ?? "127.0.0.1", NODE_ENV: "production" },
});
child.on("exit", (code) => process.exit(code ?? 0));
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
