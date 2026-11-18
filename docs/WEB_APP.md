# Sparta web app: architecture, state, accessibility and honest limits

Code: `apps/web` (Next.js 16 App Router, React 19, TypeScript strict, Tailwind 4 design tokens, TanStack Query). Setup, scripts and the dependency
list with licences are in [`apps/web/README.md`](../apps/web/README.md). The API it talks to is described in
[`API_CONTRACT.md`](API_CONTRACT.md); the machine-readable contract is `packages/contracts/openapi.json`.

## 1. What is real and what is simulated

The product rule for this app is **honesty**. The UI never pretends that a simulation is a real phone call.

| Topic | Behaviour |
| --- | --- |
| Telephony | A `SIMULATED` / `Real` badge is derived from `GET /system/status` (`telephony.simulated`) and from `CallDetail.capabilities`. Every simulated call carries the badge. |
| Owner controls | *Take over*, *Let Sparta continue*, *End call* and *Block* are enabled or disabled from `CallDetail.capabilities` (`can_take_over`, `can_continue`, `can_end`, `can_block`). The reason is shown from `takeover_note` / `audio_note`. A `409 unsupported_by_provider` is shown as "Not done." with the server's message, never as success. |
| Phone numbers | Only the masked `caller_display` is displayed. The one input that takes a raw number is the Safety Center's block/trust form. |
| AI disclosure | Always on. Assistant Studio shows it as a locked setting and previews the real text with `POST /assistant-profile/preview`. (The preview shows exactly what the API returns; section 6 records a backend defect with owner names of several words that was fixed on 2026-11-18.) |
| Voice | The simulator's text-to-speech produces **no audio**. "Hear the assistant" uses the *browser's* speech synthesis and is labelled "BROWSER voice, not the production voice". |
| Personal voice | Enrolment ends in `pending_provider_approval`; the app says provider approval cannot be completed inside it. |
| Development identity | While `/system/status` says `dev_banner: true` every screen shows a persistent "Development identity" banner with no dismiss control. |
| Translation | The per-turn English rendering comes from `CallTurn.translation` (data, not a feature flag): the assistant's own lines carry one. Nothing translates *caller* speech in this build (`features.translation` is false), so a caller turn that has none says "No translation available for this turn.", and the Studio's "Translate transcripts to" control is **disabled** with the reason while the flag is false (the saved value is left untouched). |
| Settings the engine ignores | `escalate_uncertain_urgent` ("Ask me when a call sounds urgent but Sparta is unsure") is stored by the API, but escalation follows `escalate_categories` only. The Studio shows it **disabled**, with its stored value and the text "Saved, but Sparta does not act on this yet; escalation follows the categories above." Notification preferences say that a push provider is needed. |

## 2. Application structure

```
RootLayout (server)            reads the CSP nonce, loads /theme-init.js (blocking, same origin) before first paint
 └─ Providers (client)         Toast -> Auth -> Api client -> TanStack QueryClient (+ mutation error toaster)
     └─ AppShell               skip link, dev banner, side nav / bottom nav, top bar (provider badge, display menu), onboarding gate
         └─ <Screen/>          one client component per route under src/features/*
```

Every route is rendered per request (`dynamic = 'force-dynamic'`): `src/proxy.ts` creates a fresh nonce for the Content-Security-Policy and Next stamps it
on its own scripts. The screens are client components that read everything through the typed API layer.

### API layer (`src/lib/api`)

* `generated.ts` is produced by `openapi-typescript` from `packages/contracts/openapi.json` (`npm run types:api`). `types.ts` is a thin layer on top: responses
  are `DeepRequired<...>` (the generated "optional with default" fields are always present in responses), requests stay as generated, and the hand-written
  `LiveEvent`, `Page<T>` and query types live here. `enums.ts` holds the runtime enum lists and a **compile-time drift check** against the generated types, so
  a renamed enum value in the backend breaks `npm run typecheck`.
* `client.ts` wraps `fetch`: base URL, auth headers from the pluggable auth layer, `X-Request-ID`, JSON and multipart, blob downloads (`Content-Disposition`
  filename), `Idempotency-Key` on every create/mutation POST, error envelope mapping (`{error:{code,message,trace_id,details}}` to `ApiError` with a `kind`),
  `Retry-After` parsing for 429, and a network-failure error that is distinguishable from an HTTP failure.
* Errors reach people in three ways: inline next to a field (`fieldErrors`, including a fallback for validation errors that carry only a message), as an
  `ErrorState` panel for failed reads, and as a toast for failed mutations (assertive `role="alert"`, with a "Details" disclosure that shows the trace id and
  a "Copy details" button). Reads are retried twice with backoff for network/5xx/503 only; 4xx are never retried; mutations are never retried automatically.
* Auth (`src/lib/auth`): `NEXT_PUBLIC_AUTH_MODE=dev` sends no credentials, plus the optional `X-Sparta-Dev-User` header chosen in the banner's "Switch identity"
  dialog (kept in `localStorage`). `oidc` signs the owner in with `oidc-client-ts` (Authorization Code + PKCE, public client, tokens kept in `sessionStorage`, no silent
  renewal) and sends `Authorization: Bearer <access token>`; `AuthGate` shows a sign-in screen to a signed-out owner (and a plain "not configured" message when the
  authority or client id is missing), `/auth/callback` completes the code exchange and returns to the page the owner came from (only one of the app's own routes can be
  restored), the top bar shows the account with a sign-out button. The library is loaded with a dynamic `import()` so a `dev` build never ships it.
  **This flow has not been run against a real identity provider or tenant**: it is unit-tested against a fake `UserManager` only (section 7).

### Server state (`src/lib/query`)

TanStack Query holds everything that comes from the API: `staleTime` 10 s, no refetch on window focus, cursor pagination with `useInfiniteQuery` for history,
mutations that invalidate the affected keys. Two cross-cutting rules live in `createQueryClient`: failed mutations raise a toast through an error bus
(unless a mutation declares itself `silent` and shows its own inline message, as the audio upload does), and **every successful mutation invalidates the audit
log**, which is what the Safety Center shows. TanStack Query was preferred over SWR for the infinite-query and mutation-cache support.

Small UI preferences (theme, reduced motion, translation toggle, "Hear the assistant", Lab language, the dev identity) are kept in `localStorage`; the
onboarding step and "skipped" flag in `sessionStorage`. They are read through `useSyncExternalStore`, so server and client markup agree and nothing flashes.

## 3. Live calls: WebSocket and state

`src/lib/live`:

* **`LiveConnection`** (`socket.ts`) asks for a **single-use ticket** (`POST /live/ticket`) for *every* connection attempt and opens
  `ws(s)://<api>/api/v1/live/{call_id}?ticket=...`. The URL is built from the configured API origin (the `ws_url` the server returns is not trusted).
  Drops reconnect with exponential backoff (500 ms doubling, capped at 15 s, +/-20 % jitter). Close codes are interpreted: `4401` (bad/used ticket) asks for a
  new ticket, `4403` (origin) and `4404` (unknown call) stop retrying, `4429` (too many connections) backs off. A normal close after the call ended does not
  reconnect. Text frames `{"type":"ping"}` are ignored before they are parsed as events.
* **`liveReducer`** (`reducer.ts`) is a pure reducer, so it is easy to test: the first message of a call socket is `call.snapshot`, which is authoritative;
  events are de-duplicated and ordered by `seq`; a gap in `seq` or a `stream.resync` freezes live application, the hook fetches
  `GET /calls/{id}/events?after_seq=` and then drains the held events in order; REST `TurnResult`s are applied idempotently with the matching WebSocket events;
  the event log is capped (500) and pending events are capped (400), and the transcript renders old turns lazily, so a long call does not thrash layout.
* **Speaking state** is taken from the server's truth where it exists (`CallDetail.assistant_speaking` / `speaking_turn_id`, added in the snapshot) and falls back
  to an inference (newest assistant turn younger than its `est_duration_ms`) for servers that do not send it. `assistant.finished` ends it; a caller turn after the
  estimated end also ends it; a caller turn before the end is **barge-in** (`assistant.interrupted`, and the interrupted turn is marked in the transcript).
* **Escalation outcome**: `escalation.requested` and `owner.takeover` / `owner.action` update the model, but no event reports an *expired* escalation (the owner did
  not answer in time). When the call leaves `ESCALATE` while the model still says `requested`, the hook reads `GET /calls/{id}` once and merges only the escalation and
  owner actions (action `escalations`, helper `staleEscalationId`), so the banner is replaced by "You did not answer in time, so Sparta took a message." A late
  reply can never turn a resolved escalation back into `requested`.

### The voice stage is state-driven, not decorative

`src/lib/voice-activity.ts` derives one mode from the live model: `connecting`, `listening`, `caller_speaking` (a `transcript.partial`), `thinking`,
`assistant_speaking` (`assistant.speaking` with its `est_duration_ms`), `interrupted`, `escalated`, `reconnecting`, `ended`. The canvas (`voice-stage.tsx`) draws
outward bars for the assistant and inward bars for the caller; the assistant's progress ring is time since `assistant.speaking` over `est_duration_ms`; the
bar envelope is a deterministic function of the utterance text; in the Simulator Lab, with the browser microphone on, the levels come from a real
`AnalyserNode`. Nothing is random. Only `transform` and `opacity` are animated. With `prefers-reduced-motion` (or the manual "Reduce motion" switch) no animation
frame is scheduled at all: the stage shows a static indicator and a text label (`role="status"`, polite) that says the same thing in words. The E2E suite checks
this by counting `requestAnimationFrame` calls with and without reduced motion.

## 4. Accessibility approach

* Semantic landmarks on every screen (skip link, `header`, labelled `nav`, one `main`, one `h1`), `lang="en"`, `lang` attributes on non-English transcript text.
* Keyboard: every flow works without a pointer; visible focus ring on every control including visually hidden switches/radios (the ring is drawn on the sibling
  control); native `<dialog>` with `showModal()` for modals (focus trap, Escape, focus returns to the trigger).
* Live regions: transcript `aria-live="polite"`, the escalation banner `role="alert"` (assertive), the voice-stage label and the risk announcer `role="status"`,
  toasts `status` or `alert` by severity.
* Colour is never the only signal: risk, state and signals always carry text and an icon. Green is only for verified/low risk, amber for caution, red only for
  high risk. Token pairs are contrast-tested for **WCAG AA in both themes** (`src/styles/tokens.test.ts`), and axe-core runs in a real browser over every screen in both
  themes (`e2e/a11y.spec.ts`): that is how a primary *link* button turned out to be light text on brass (an unlayered `a { color: inherit }` beat Tailwind's layered
  `text-accent-ink`); jsdom and the token test could not see it.
* Dialogs are native `<dialog>` modals with Tab and Shift+Tab wrapped inside (the browser would otherwise let focus escape to its own UI); the display menu stays open
  while the mouse is pressed inside it and closes on an outside click, Tab-away or Escape.
* Touch targets are at least 44 x 44 px (checked on a 375 px viewport for every screen).
* Dark by default with a polished light theme, a system/light/dark switch and no flash (the blocking same-origin `/theme-init.js` sets `data-theme` before paint).

## 5. Security notes

Nonce-based CSP per request (no `unsafe-inline`/`unsafe-eval` in production; `style-src` is `'self'` plus the nonce because the app uses no inline style
attributes), `connect-src` limited to this origin and the API, no framing, `Permissions-Policy` that allows only the microphone for this origin,
`X-Content-Type-Options`, `Referrer-Policy`, no third-party scripts, fonts or analytics, transcripts and all API strings rendered as text, no secrets in client
code. In development Next needs `unsafe-eval` and inline styles for its tooling; production does not.

## 6. Backend behaviour found while testing (reported to the backend owner)

The end-to-end suite runs against the real API (`python -m sparta serve`, in-memory SQLite, `SPARTA_ENV=test`). Status as of 2026-11-18, checked against the
backend code of commit `3236870` (the later `0fd2a84` changed infrastructure files only); the 110 of 110 run was made on that code.

**Fixed in the backend and verified (by the end-to-end suite, 4 parallel workers, no retries, no workaround in the tests, unless a line says otherwise):**

* The first requests of a brand-new development identity (`GET /me`, `/preferences`, `/assistant-profile` in parallel) no longer fail with 500.
* `live_events` / `call_turns` UNIQUE-constraint errors when a request raced a call's own background timer (`/turns`, `/end`, the duration limit) are gone.
* Scripted autoplay (`POST /simulator/calls {autoplay: true}`) runs to the end every time: both autoplay end-to-end tests assert the whole script
  (every scripted caller line, risk high, refusal, hang-up, summary).
* `assistant.finished` is emitted before the caller's next `transcript.final`; `CallDetail.assistant_speaking` / `speaking_turn_id` are used by the UI.
* The AI disclosure for an owner whose display name has several words (`"Atharv S"`, `"Asha Rao"`, `"Atharv Shukla"`, `"Anil K Mehta"`): the output validator now judges a
  full name as a whole, so the preview and the real opening line read "Hi, I'm ...'s AI call assistant ..." again. Verified by backend regression tests across names, styles and
  templates (`services/api/tests/unit/test_planner_validator.py`, `test_engine.py`), not by this suite, which uses one-word owner names.
* `POST /simulator/replay` no longer answers 500 when replays overlap: the replay driver waits by a 30 s wall-clock deadline instead of counting polls, and a replay that
  really runs out of time is a 503 `provider_unavailable`. Verified on 2026-11-18 by 110 of 110 end-to-end tests run in one Playwright project, with the replay specs in parallel
  with the rest.

**Still open:**

1. **An escalation's outcome is not announced by any event.** When the owner does not answer in time the API emits `state.changed` (`ESCALATE` -> `SAFE_CONTINUE`)
   and the message-taking turn, but nothing says the escalation is now `expired` (`GET /calls/{id}` has the right `escalations[].status`). The live screen therefore
   notices that the call left `ESCALATE` while its escalation still reads `requested` and re-reads the call once (`staleEscalationId`, `src/lib/live`). An
   `escalation.resolved` event (or the escalation inside `state.changed`) would remove that read.

Not a defect, but good to know: an owner may have at most 5 active calls, and an ended call counts as active until the assistant has finished its sentence.

## 7. Honest limitations

* **OIDC is implemented but UNVERIFIED against a real identity provider.** The Authorization Code + PKCE flow (`oidc-client-ts`), the sign-in gate, the callback route, bearer-token
  headers and sign-out are implemented and unit-tested with a fake `UserManager`; no real identity provider (Entra ID or otherwise), consent screen, token lifetime, clock
  skew, `end_session_endpoint` behaviour or the API's token validation was exercised, and the end-to-end suite runs in `dev` mode only. There is no silent token
  renewal: an expired token returns the owner to the sign-in screen. Treat it as a starting point to be verified, not as proven.
* **Web Speech API**: feature detection, the fallback message, the interim/final request flow, the language hint and the error messages are tested against a
  scriptable recogniser and Chromium's fake microphone. The real browser speech service (which, in Chrome and Edge, receives the audio) and real recognition
  quality were not tested; headless browsers cannot.
* **Browsers**: only Chromium was exercised (Playwright). Firefox and Safari have no Web Speech recognition and are covered by the fallback message only in theory.
* **Audio upload**: the simulator has no speech-to-text; without a transcript hint the API answers `422 stt_unavailable` and the app shows the explanation. Real
  transcription of an uploaded clip depends on a configured speech provider.
* **Telephony**: only the simulator exists. Nothing here was run against a real phone call, Azure Communication Services or a forwarded number.
* **Performance**: first-load JavaScript is about 165 to 190 kB gzip per route (see `npm run build:report`); the Simulator Lab is a separate lazy chunk. No real-user measurements.
* **Screenshots** document the layout; they are not pixel-diff baselines (timestamps and generated ids change).
* **Docker image**: built and run on a developer machine (Docker 29, Linux/musl, through a corporate npm mirror) after the runtime stage dropped `sharp`, the npm CLI and
  corepack: non-root (uid 100), `npm`/`npx`/`corepack` absent, eight routes answer 200 with the nonce CSP, `healthy`. I did not scan it for vulnerabilities (the infrastructure
  team does, with Trivy), it is not built in CI and not pushed anywhere.
* **Hand-written enum layer**: `src/lib/api/enums.ts` mirrors the API's string enums; `src/lib/api/types.ts` has a compile-time drift guard against the generated
  OpenAPI types, so a changed enum fails `npm run typecheck`. Request/response shapes come from `src/lib/api/generated.ts` (`npm run types:api`).

## 8. Verification record (2026-11-18)

Commands and results are in `apps/web/README.md` ("Last verified"): lint 0 problems, typecheck 0 errors, 20 test files / 294 tests, production build OK, lock file
clean, **110 of 110 end-to-end tests passed** (4 parallel workers, no retries, real API on port 8100 and the production build on 3100), axe-core 0 serious/moderate/minor
violations on every screen in both themes, 45 screenshots.

Defects that the end-to-end suite and axe found in **the web app itself** (all fixed, each now covered by a test): the interrupted assistant turn was not marked in the
live transcript; a validation error without `details` showed nothing inline; primary link buttons were light text on brass at 1.96:1 (an unlayered `a { color: inherit }`
beat Tailwind's layers); Home's counters were an invalid `<dl>`; heading levels skipped; Tab could leave a modal dialog; the display menu closed under the mouse; two
landmarks shared one accessible name; the audit log was stale after a mutation; the **"waiting for you" banner never cleared when the owner did not answer in time**
(the API sends no event for it, see section 6); and **a History filter change could be lost** when a second one was made before the router had committed the first.
