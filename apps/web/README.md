# Sparta web app

The owner-facing web app for **Sparta** ("Your calls. Your voice. Your shield."): a multilingual (English, Hindi/Hinglish,
Kannada/Kanglish) AI call-screening assistant. This app talks to the FastAPI backend in `services/api` (contract:
`docs/API_CONTRACT.md`, machine-readable: `packages/contracts/openapi.json`). Architecture notes, the state and WebSocket design,
the accessibility approach and the honest list of limitations are in [`docs/WEB_APP.md`](../../docs/WEB_APP.md).

Eight screens, all wired to the real API:

| Screen | Route | What it does |
| --- | --- | --- |
| A. Onboarding | `/onboarding` | 9 steps (AI disclosure, privacy, languages, voice, strictness, trusted contacts, a simulated-call walkthrough, phone connection). Saved through `PUT /preferences` and `PUT /assistant-profile`. |
| B. Home | `/` | Protection status, the next action, today's counters, calls that need you, the last five calls. |
| C. Live call command center | `/live`, `/live/[id]` | Real-time transcript (partial and final, per-turn language chips, Hinglish/Kanglish labels, optional English translation), risk meter with evidence, state-driven voice stage, escalation banner, owner controls, collapsible diagnostics. |
| D. Call history | `/calls` | Search, filters (risk, category, language, status, attention, dates), cursor pagination, expandable rows, export, delete. |
| E. Call detail | `/calls/[id]` | Summary, transcript with language-change markers and evidence highlights, action timeline, feedback, block/trust, deletion, trace id and report download. |
| F. Assistant Studio | `/studio` | Preferences, assistant profile, voices, personal-voice consent and enrolment, safe-reply preview. The AI disclosure is always on. |
| G. Safety Center | `/safety` | Policies and flagged events, blocked/trusted lists, retention, delete-all, personal-voice deletion, audit log, a plain-language prompt-injection explanation. |
| H. Simulator Lab | `/simulator` | Scenario picker and builder, typed/microphone/uploaded-audio caller input, language and network selectors, barge-in and silence, provider status, event log, deterministic replay, diagnostic report. |

## Requirements

* Node.js **>= 22.12** and npm (the lock file is npm's).
* The Sparta API for anything beyond the first paint: from `services/api`, `.venv\Scripts\python.exe -m sparta serve --host 127.0.0.1 --port 8000`
  (Windows) or `python -m sparta serve ...`. With dev authentication the API needs no credentials.

## Run it

```bash
cd apps/web
cp .env.example .env.local        # NEXT_PUBLIC_API_BASE_URL=http://localhost:8000, NEXT_PUBLIC_AUTH_MODE=dev
npm ci
npm run dev                        # http://localhost:3000
```

The API must allow the web origin (`SPARTA_CORS_ORIGINS=http://localhost:3000`).

Behind a corporate npm mirror: set `npm_config_registry` for the install only (never commit an `.npmrc`), then run
`npm run lock:normalize` so every `resolved` URL in `package-lock.json` points at `registry.npmjs.org`; `npm run lock:check` verifies it.

## Scripts

| Script | What it does |
| --- | --- |
| `npm run dev` | Next dev server on :3000. |
| `npm run build` | Production build (`output: 'standalone'`). |
| `npm run start` | Serves the standalone build exactly like the Docker image (`PORT`, default 3000). |
| `npm run build:report` | First-load JavaScript per route (raw and gzip) and the lazy chunks, from `.next/diagnostics`. |
| `npm run lint` | ESLint (zero errors required). |
| `npm run typecheck` | `tsc --noEmit`, strict. Also type-checks the tests and the E2E specs. |
| `npm run test` | Vitest + React Testing Library (jsdom). |
| `npm run e2e` | Playwright against the **real** API and the production build (see below). `npm run e2e:install` downloads Chromium once. |
| `npm run types:api` | Regenerates `src/lib/api/generated.ts` from `packages/contracts/openapi.json` with `openapi-typescript`. |
| `npm run lock:normalize` / `lock:check` | Normalise / verify the registry URLs in `package-lock.json`. |
| `npm run licenses` | Licence of every installed package; fails on anything that is not permissive or reviewed. |

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Where the browser finds the API (HTTP and WebSocket). Inlined at **build** time and also used for the `connect-src` of the Content-Security-Policy. |
| `NEXT_PUBLIC_AUTH_MODE` | `dev` | `dev` = no credentials (the API's development identity; a non-dismissable banner says so). `oidc` = Authorization Code + PKCE sign-in with `oidc-client-ts`: **implemented, unit-tested with a fake `UserManager`, but UNVERIFIED against a real identity provider** (see limitations). |
| `NEXT_PUBLIC_OIDC_AUTHORITY`, `NEXT_PUBLIC_OIDC_CLIENT_ID`, `NEXT_PUBLIC_OIDC_SCOPE` | none, none, `openid profile` | Only for `oidc`. Register `<web origin>/auth/callback` as the redirect URI (and the web origin as the post-logout URI) for a public (no secret) client. The authority is added to the CSP `connect-src`. |

All are public by design: never put a secret in a `NEXT_PUBLIC_*` variable. There are no secrets in this app.

## Layout

```
src/app/                  routes (App Router) + globals.css (design tokens as CSS variables) + error/not-found
src/proxy.ts              per-request CSP nonce (Next 16 "proxy", formerly middleware)
src/features/<screen>/    one folder per screen (home, onboarding, live, history, call-detail, studio, safety, lab)
src/components/           ui kit (button, form, dialog, toast, ...), shell (nav, dev banner, display menu), call (transcript, risk panel, voice stage, owner controls, ...)
src/lib/api/              typed client (errors, idempotency, 429), endpoints, generated.ts + thin types.ts/enums.ts
src/lib/live/             WebSocket client (ticket, backoff, resync), event reducer, useLiveCall
src/lib/query/            TanStack Query client, keys, hooks
src/lib/speech/           Web Speech recognition, browser speech synthesis, microphone level meter
src/lib/*.ts              risk / call-state / voice-activity mappings, formatting, labels, theme, csp
src/test/                 test fixtures, a typed fake fetch, render helpers
e2e/                      Playwright specs, helpers (support/), screenshots/
scripts/                  serve-standalone, report-bundles, list-licenses, generate-api-types, normalize-lockfile
```

## Dependencies and why

Everything is MIT, Apache-2.0 or MPL-2.0 (`npm run licenses` checks all 427 installed packages: 365 MIT, 25 Apache-2.0, 15 ISC, 9 BSD-2-Clause,
3 BSD-3-Clause and a few others). The one exception to read: `sharp`'s prebuilt libvips package (`@img/sharp-*`, `Apache-2.0 AND LGPL-3.0-or-later`) is an
*optional* dependency of Next.js for image optimisation. npm installs it, the app never uses it (no `<Image>`, `images.unoptimized`), and the Dockerfile
deletes it from the image. No third-party scripts, fonts, analytics or icon packs are loaded: fonts are the
system stack, icons are inline SVG, the logo is an original inline SVG shield with a voice wave.

Runtime (shipped to users):

| Package | Licence | Why |
| --- | --- | --- |
| `next` 16.4 | MIT | App Router, production server (`standalone`), `proxy.ts` for a nonce-based CSP, security headers. |
| `react`, `react-dom` 19.3 | MIT | UI. |
| `@tanstack/react-query` 5 | MIT | Server state: caching, de-duplication, retry with backoff for 5xx only, cursor pagination (`useInfiniteQuery`), mutations with invalidation and one place that raises accessible error toasts. Chosen over SWR for the infinite-query and mutation-cache support (about 13 kB gzip). |
| `oidc-client-ts` 3.5 | Apache-2.0 | OIDC Authorization Code + PKCE for `NEXT_PUBLIC_AUTH_MODE=oidc` (it brings `jwt-decode`, MIT). Loaded with a dynamic `import()`, so it is not in the first-load JavaScript of a `dev` build (`npm run build:report` shows it as a separate lazy chunk). Imported by `src/lib/auth/oidc.ts`. **Implemented but UNVERIFIED against a real identity provider.** |

Build and test only (never shipped):

| Package | Licence | Why |
| --- | --- | --- |
| `tailwindcss`, `@tailwindcss/postcss` 4 | MIT (its `lightningcss` engine is MPL-2.0) | Utility CSS; the design tokens are CSS variables (`@theme`), dark default plus a light theme. Build-time only. |
| `typescript` 6.0 | Apache-2.0 | Strict type checking. Pinned `~6.0` because `typescript-eslint` does not accept 6.1+/7 yet. |
| `eslint`, `eslint-config-next` | MIT | Lint (`react-hooks`, `jsx-a11y`, no `dangerouslySetInnerHTML`). |
| `openapi-typescript` 7 | MIT | Generates request/response types from `packages/contracts/openapi.json`. |
| `vitest`, `vite`, `@vitejs/plugin-react`, `jsdom`, `@testing-library/*` | MIT | Unit and component tests. |
| `@playwright/test` | Apache-2.0 | End-to-end tests in a real browser against the real API. |
| `axe-core`, `@axe-core/playwright` | **MPL-2.0** | Accessibility checks in jsdom and in Chromium. MPL-2.0 is file-level copyleft; it is used only by tests and is not distributed with the app. |
| `@types/node`, `@types/react`, `@types/react-dom` | MIT | Types. |

Deliberately not used: MSW (an in-repo typed fake `fetch` is enough), zod (the API contract is typed from OpenAPI), animation libraries
(canvas, CSS and the Web Animations API cover the state-driven voice stage), UI kits and icon libraries.

## Tests

```bash
npm run lint && npm run typecheck && npm run test && npm run build
```

* **Unit and component** (`src/**/*.test.ts(x)`): API client error mapping and idempotency, the WebSocket client and event reducer (sequence gaps,
  backfill, `stream.resync`, reconnect with backoff, snapshot-first, stale snapshots), the voice stage's mode over a whole call (the API's real event order replayed
  frame by frame, `src/lib/live/stage-mode.test.ts`), risk/state/voice mappings, reduced-motion behaviour, design-token contrast
  (WCAG AA in both themes), every screen against a typed fake API, and axe-core over every screen.
* **End to end** (`e2e/*.spec.ts`, `npm run e2e`): Playwright starts the **real API** (`services/api`, in-memory SQLite, `SPARTA_ENV=test`, port 8100)
  and the **production build** (standalone server, port 3100, built with `NEXT_PUBLIC_API_BASE_URL=http://localhost:8100`) and drives Chromium through
  the ten-step journey from the brief, takeover/continue, block/trust, deletion, deterministic replay, audio upload, WebSocket reconnect and resync,
  error handling, security headers, keyboard and focus behaviour, touch targets, theme handling and axe-core on every screen in both themes.
  It also writes the responsive screenshots to `e2e/screenshots/` (phone 375, tablet 768, desktop 1280; light theme at 375 and 1280).

  First run: `npm run e2e:install` (Chromium). Every test signs in as its own development identity (`X-Sparta-Dev-User`), so tests share no data and run in
  parallel (4 workers by default, `E2E_WORKERS=n`) with no retries: a flaky test is a bug to fix. Read-only specs share one seeded "showcase" owner per worker
  (a realistic history); anything that starts a call uses an owner of its own. The deterministic-replay tests (`e2e/replay.spec.ts`) run in the same project and in
  parallel with the rest (the API's replay endpoint used to answer 500 when replays overlapped; it now waits by a wall-clock deadline).
  Useful switches: `E2E_REUSE_SERVERS=1` reuses servers that are already running (the web server must have been built for `http://localhost:8100`);
  `SPARTA_API_COMMAND` replaces the command that starts the API (it runs inside `services/api`; the default is the `.venv` interpreter).
  The simulated assistant speaks in real time, so scripted-call tests take a while (about 16 s for `bank-otp-en`, about 27 s for `language-switch-journey`).

**Last verified, 2026-11-18** (Windows 11, Node 26.13, npm 12.2, Next 16.4.6, Playwright 1.65 with Chromium 1254, API from the repository's working tree):
`npm run lint` 0 problems; `npm run typecheck` 0 errors; `npm run test` 22 files and 310 tests passed; `npm run build` OK (first-load JavaScript 167 to 191 kB gzip per
route, `npm run build:report`); `npm run lock:check` clean; `npm run e2e` **112 passed, 0 failed, 0 flaky** in 7.7 minutes (4 workers, no retries, one project; the two
deterministic-replay tests run in parallel with the others); axe-core found 0 serious, 0 moderate and 0 minor violations on onboarding (steps 1, 2, 3, 5, 8 and 9), home, live index, live call,
call history (also with an expanded row), call detail, Assistant Studio, Safety Center, Simulator Lab (setup and live console) and a modal dialog, in the dark and the
light theme; 45 screenshots (4.1 MB) were regenerated in `e2e/screenshots/`.

## Security

* Nonce-based **Content-Security-Policy** per request (`src/proxy.ts`): scripts only with the nonce (`'strict-dynamic'`), no `unsafe-inline`/`unsafe-eval` in
  production, `connect-src` limited to this origin and the API (HTTP and WebSocket), `frame-ancestors 'none'`, `object-src 'none'`.
  `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` (`microphone=(self)` and everything else denied), `X-Frame-Options`, COOP via `next.config.ts`.
* Transcripts and every other string from the API are rendered as text. There is no `dangerouslySetInnerHTML`, no inline `style` attribute and no inline script
  (the theme is applied by the same-origin `/theme-init.js` before first paint).
* Only the masked `caller_display` is ever shown. The one place a number is typed is the Safety Center's block/trust form.
* WebSockets use a single-use ticket; the browser never puts a credential in a URL.

## Docker

```bash
docker build -t sparta-web --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com .
docker run --rm -p 3000:3000 sparta-web
```

Multi-stage (deps, build, runtime), Next `output: 'standalone'`, runs as a non-root user, `HEALTHCHECK` on `/`. `NEXT_PUBLIC_*` are build arguments (API address, auth
mode, OIDC authority/client id/scope). Behind a corporate npm mirror add `--build-arg NPM_REGISTRY=<mirror url>`. The runtime stage drops `sharp` (LGPL libvips,
unused) and the npm CLI and corepack (never needed at run time: `CMD` is `node server.js`), which also removes the npm CLI's bundled dependencies, and their CVEs, from
the image.
Verified on 2026-11-18 with Docker 29.9 after that change: the image builds (about 308 MB), runs as uid 100 `sparta`, `npm`, `npx` and `corepack` are gone, `/`,
`/calls`, `/studio`, `/safety`, `/simulator`, `/live`, `/onboarding` and `/auth/callback` answer 200 with the nonce Content-Security-Policy, and the container reports
`healthy`. On GitHub the `container` workflow builds it, scans it with Trivy (HIGH and CRITICAL, fixable findings only: no finding on the last run)
and, on `main`, publishes it to GHCR as `ghcr.io/snowjug/sparta-web` (published on 2026-11-18; the published image itself was not run, see
[../../docs/DEPLOYMENT.md](../../docs/DEPLOYMENT.md)).

## Known limitations

See `docs/WEB_APP.md` for the full, honest list. In short: **OIDC sign-in is implemented with `oidc-client-ts` but is UNVERIFIED: it has never been run against a real
identity provider** (it is unit-tested with a fake `UserManager` only), the simulator produces no audio (text only; "Hear the assistant" uses the browser's own
voice and is labelled so), personal-voice enrolment ends at `pending_provider_approval` (provider approval cannot be completed in the app), caller-speech
translation is not available (the Studio control says so and is disabled), the browser microphone path (Web Speech API) was tested against a scriptable
recogniser, not a real speech service, and only Chromium was exercised.
