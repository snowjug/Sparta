import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * End-to-end tests run against the REAL backend (services/api) and the production build of this app (Next standalone server):
 *   API   http://127.0.0.1:8100  in-memory SQLite, SPARTA_ENV=test, CORS for the web origin
 *   Web   http://localhost:3100  built with NEXT_PUBLIC_API_BASE_URL=http://localhost:8100
 * Ports 3100/8100 keep these runs away from the dev servers on 3000/8000.
 *
 *   E2E_REUSE_SERVERS=1   reuse servers that are already running (fast local iteration; the web server must have been built for 8100)
 *   E2E_WORKERS=n         parallel workers (default 4)
 *   SPARTA_API_COMMAND    full command that starts the API, run inside services/api (default: the .venv interpreter)
 */
const API_PORT = 8100;
const WEB_PORT = 3100;
const WEB_ORIGIN = `http://localhost:${WEB_PORT}`;
const API_ORIGIN = `http://localhost:${API_PORT}`;

const apiDir = resolve(__dirname, "../../services/api");
const windowsPython = join(".venv", "Scripts", "python.exe");
const unixPython = join(".venv", "bin", "python");
const python = existsSync(join(apiDir, windowsPython)) ? windowsPython : existsSync(join(apiDir, unixPython)) ? unixPython : "python";
const apiCommand = process.env.SPARTA_API_COMMAND ?? `${python} -X utf8 -m sparta serve --host 127.0.0.1 --port ${API_PORT}`;
const reuse = process.env.E2E_REUSE_SERVERS === "1";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  // Every test signs in as its own development identity, so tests share no data and run in parallel. No retries: a flaky test is a bug to fix.
  retries: 0,
  workers: Number(process.env.E2E_WORKERS) || 4,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: WEB_ORIGIN,
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
    colorScheme: "dark",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Chromium's built-in fake microphone: the Lab's real Web Audio analyser needs *a* stream, and headless has no hardware.
    launchOptions: { args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] },
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
  ],
  webServer: [
    {
      command: apiCommand,
      cwd: apiDir,
      url: `http://127.0.0.1:${API_PORT}/readyz`,
      reuseExistingServer: reuse,
      timeout: 60_000,
      env: {
        PYTHONUTF8: "1",
        SPARTA_ENV: "test",
        SPARTA_LOG_JSON: "false",
        SPARTA_DATABASE_URL: "sqlite+aiosqlite:///:memory:",
        SPARTA_CORS_ORIGINS: WEB_ORIGIN,
      },
    },
    {
      // Builds with the E2E API address baked in (NEXT_PUBLIC_* are build-time), then serves the standalone output like the Docker image.
      command: "node scripts/serve-standalone.mjs --build",
      cwd: __dirname,
      url: `${WEB_ORIGIN}/`,
      reuseExistingServer: reuse,
      timeout: 300_000,
      env: {
        PORT: String(WEB_PORT),
        NEXT_PUBLIC_API_BASE_URL: API_ORIGIN,
        NEXT_PUBLIC_AUTH_MODE: "dev",
      },
    },
  ],
});
