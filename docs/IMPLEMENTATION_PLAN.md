# Sparta — Implementation Plan & Progress Log

> Living document. Updated at every checkpoint. Statements here describe verified state only; anything not yet built is
> listed in the milestone table (section 4), the external dependencies (section 5) or the open items (section 7).

## 1. Starting conditions (recorded 2026-11-17)

| Item | Value |
| --- | --- |
| Repository | https://github.com/snowjug/Sparta (public) |
| State at start | **Empty**: no commits, branches, issues, PRs, rulesets, README or configuration to preserve |
| Baseline commit (`main`) | `2593eda` — `chore: add repository baseline` (README stub, `.gitignore`, `.gitattributes`, `.editorconfig`) |
| Working branch | `feat/sparta-v1` (cut from `main@2593eda`) |
| Host | Windows 11 (PowerShell 5.1), Node 26, npm 12, Python 3.15 (system) + Python 3.12 via `uv`, Docker Desktop 29 (WSL2) |
| Not preinstalled | JDK, Android SDK, Gradle, `make` (handled: `docs/ANDROID_SETUP.md` covers the Android toolchain; `scripts/tasks.ps1` does the job of `make` on Windows) |
| Push identity | Repository owner account `snowjug`, supplied per-process; no tokens are stored in the repo or git config |

## 2. Scope and honesty rules

* The product ships a **fully functional simulator** (browser/local call simulator) and a **provider-agnostic telephony
  abstraction**. The Azure Communication Services adapter is implemented against documented interfaces and tested with
  mocked provider boundaries; **no live PSTN call has been made** and none is claimed.
* Android uses the platform `CallScreeningService` (allow / silence / reject / caller-ID metadata). Ordinary Android
  apps **cannot** capture or inject cellular call audio; the app never implies two-way AI audio on a cellular call.
  Conversational audio requires the call to reach a programmable telephony number (forwarding concept, see
  `docs/TELEPHONY.md`).
* Evaluation numbers are generated from real runs of `python -m sparta evaluate` only (`docs/EVALUATION.md`,
  `docs/eval/`). The test split is held out; tuning happens on the development split.
* Behaviour that has never run against a live service (Azure Communication Services, Event Grid, Azure Speech, Azure
  OpenAI, Personal Voice, OIDC sign-in, a real Android device) is marked **UNVERIFIED** wherever it is described.

## 3. Architecture decisions (summary: details in `docs/DECISIONS/`)

Numbered decisions have an ADR file. The titles of 0002 to 0005 in the first version of this plan were provisional; the
files below are what was actually decided. Two earlier ideas were not adopted as written: the policy and the language packs
are TOML files, not JSON, and call state is **not** event-sourced (the call is a mutable row, `call_sessions`, with separate
tables for turns, provider events and live events; an injectable clock makes timers and replay deterministic).

| # | Decision | Reason | ADR |
| --- | --- | --- | --- |
| 0001 | Modular monolith (`services/api`, package `sparta`) with internal boundaries for risk engine, orchestrator, providers and telephony | Fewer moving parts; every boundary is an interface plus tests, so services can be split later | [0001](DECISIONS/0001-modular-monolith.md) |
| 0002 | Deterministic safety core: a pure engine, a versioned TOML policy and vetted reply templates decide; a model may only add capped, non-protected signals | Safety before model creativity; auditable; works without credentials | [0002](DECISIONS/0002-deterministic-safety-core.md) |
| 0003 | Honest telephony capability split: Android screening and backend conversational telephony are separate capabilities, and `capabilities` per provider is authoritative | Platform reality (no call audio for third-party Android apps); nothing simulated may look real | [0003](DECISIONS/0003-honest-telephony-capability-split.md) |
| 0004 | Per-mention denial handling: a sensitive term inside a denial is not a request, decided per occurrence and clause | A generic "don't tell anyone" window had suppressed a real request | [0004](DECISIONS/0004-per-mention-denial-handling.md) |
| 0005 | Evaluation discipline: tune on the development split only, publish held-out numbers, separate live outcomes from signal coverage | Numbers must mean something | [0005](DECISIONS/0005-evaluation-discipline.md) |
| 0006 | Two-clock retention: transcripts expire first, summaries and structured risk reasons later | Keep the useful record, drop the most sensitive content early | [0006](DECISIONS/0006-two-clock-retention.md) |
| none | Development identity versus OIDC, with a hard production guard | Safe local run, impossible to enable silently in production. No ADR file; see `Settings.problems()` in `services/api/src/sparta/config.py` | n/a |
| none | Injectable clock | Deterministic timers and the simulator's replay. No ADR file; see `services/api/src/sparta/clock.py` | n/a |

## 4. Milestones

Legend: Not started · Partial (partly done, or present in the working tree but not committed) · Committed (on `feat/sparta-v1`).
A status of Committed says the work is in git; the results of the checks that back it are recorded in the progress log
(section 6), not implied here. Commit dates are in section 6.

| # | Milestone | Status | Commits and notes |
| --- | --- | --- | --- |
| M0 | Repository baseline, branch, plan, monorepo skeleton | Committed | `2593eda` baseline on `main`; the skeleton is the directory layout in the README |
| M1 | Backend foundation: settings, logging/redaction, domain contracts, DB models, migrations, OpenAPI export | Committed | `f7b4174` settings, logging, domain models; `e6f56d7` encrypted persistence layer and migrations; `0df79a8` OpenAPI export and `packages/contracts/openapi.json`; `01f5e37` migrations bundled in the wheel; `62d7f7e` readable start-up failures |
| M2 | Language engine (en/hi/kn, Hinglish/Kanglish, registry for future languages) | Committed | `f7b4174`; `8723432` broader en/hi/kn lexicon; `b09c936` code-switch matrix language. Hindi and Kannada packs not native-reviewed; mr, ta, te, ml, bn are `planned` (detected as unsupported) |
| M3 | Risk & safety engine, versioned policy, prompt-injection defense | Committed | `f7b4174`; `8723432` per-mention denial handling (ADR 0004); `b09c936` legitimate-category fixes; `117752e` bounded input work, deletion of invisible characters and folding of look-alike letters. Policy `2026.11.2`; residual misses are listed in `docs/SAFETY_MODEL.md` |
| M4 | Conversation orchestrator (state machine, planner, validator, barge-in, silence, takeover, summary) | Committed | `d7aec99`; `45accdf` ordering and first-request fixes; `2975796` barge-in in the audio pipeline. Takeover on the simulator is a labelled simulation; the `FAILED` state is defined but never set |
| M5 | Provider layer (STT/TTS/LLM/VAD, resilience), telephony abstraction, simulator + Azure adapters, webhooks | Committed | `0485e15` ports, simulators, resilience and metrics; `59417ed` provider settings and STT flush; `c733a88` composition root; `a97f969` Azure Speech, Azure OpenAI, ACS adapters and webhook verification; `2975796` real-time caller audio pipeline; `ac59c3e` SSML attribute escaping. Azure adapters and the audio pipeline are tested against fakes only |
| M6 | REST + WebSocket API, auth, rate limits, idempotency, audit, retention | Committed | `8570e6c` owner, simulator and audit services; `0df79a8` HTTP API, live socket, webhooks, retention, jobs; `117752e` security-review fixes (cached-response retention, WAV header walk, per-owner matcher cache and profile-save limit, screening-event cap, batched retention, development-identity bind guard; `docs/SECURITY_REVIEW.md`); `58e3a9a` live-event sequence numbers come from one atomic `UPDATE ... RETURNING`, SQLite files begin every transaction with `BEGIN IMMEDIATE`, and migration `0002` links a cached response to the call it created so that deleting the call forgets it; `ff4a6a8` OpenTelemetry spans (request, provider call, engine step) and the owner's name replaced before a model provider is called; `4316669` `/readyz` waits for the migrations the code needs; then the fixes recorded in section 6 (keyed idempotency fingerprint, list deletions that forget cached responses, FastAPI's own telemetry switched off, a wall-clock replay deadline, a screening-event cap counted by receipt time). OIDC validation never run against a real identity provider |
| M7 | Backend tests + multilingual evaluation suite and generated report | Committed | tests ship with the commits above; `a5c694b` dataset v1; `879e666` harness; `ef1e21f` first results; `41d3b6c` `docs/EVALUATION.md`; `4c02212` tests for spans, import direction, the model-signal allow-list and the owner-name replacement; `a7e796d` a contract test of the shared-state stores that also runs against a real Redis when `SPARTA_TEST_REDIS_URL` is set |
| M8 | Web experience (all required screens) | Committed | `7b7e47a` `apps/web`: onboarding, Home, Live, History, Call detail, Assistant Studio, Safety Center, Simulator Lab. OIDC sign-in is implemented but UNVERIFIED against a real identity provider; only Chromium was exercised |
| M9 | Web tests: unit, a11y, Playwright E2E (10-step scenario + extras) | Committed | `7b7e47a` Vitest (including axe over every screen) and Playwright tests against the real API and the production build, extended in `b507647` (voice stage) and `5f980d1`; on the final code 310 Vitest tests and 112 Playwright tests passed (the final-verification entry of section 6) |
| M10 | Android app + build + unit tests | Committed | `07a119e` app and `docs/ANDROID_SETUP.md`. Instrumented tests compile but have never run; no device or emulator was available |
| M11 | Docker, Compose, scripts, Bicep, CI/CD, repo hygiene files | Committed | `484e69b` hash-pinned API image (`services/api/Dockerfile`, the `requirements*.lock` image locks), compose stack, `.env.example`, `.gitleaks.toml`; `7966187` `Makefile` and `scripts/` for Windows and Linux (`scripts/journey.py` came earlier, in `b88d48d`); `affe463` `.github/` (workflows `ci`, `codeql`, `container`, `dependency-review`, `deploy`, `secret-scan`; Dependabot, CODEOWNERS, issue and PR templates); `8b674ee` `infrastructure/azure` (Bicep; its header says it compiles and lints but has not been deployed); `77af0d0` `SECURITY.md`, `CONTRIBUTING.md`, `docs/DEPLOYMENT.md`, `docs/RELEASE_CHECKLIST.md`; `0fd2a84` fixes from the second security review (deploy only from `main`'s history, per-secret Key Vault access, CI path filter, gitleaks allowlist). The workflows ran on GitHub for the first time on pull request 1 (results in the final-verification entry of section 6); the parts that run on `main` only ran after the merge: both images were published to GHCR and the deploy workflow skipped itself because the Azure variables are not set (the entry after it). The deploying job has not run |
| M12 | Documentation set, ADRs, threat model, deployment checklist | Committed | `docs/EVALUATION.md` (`41d3b6c`, updated in `9352d0d`), `docs/ANDROID_SETUP.md` (`07a119e`), `docs/SECURITY_REVIEW.md` (`9352d0d`, second review added at the end), ADR 0001, `docs/DEPLOYMENT.md` and `docs/RELEASE_CHECKLIST.md` (`77af0d0`, updated in `0fd2a84`); `README.md`, `docs/{ARCHITECTURE,SAFETY_MODEL,MULTILINGUAL_SPEECH,TELEPHONY,PRIVACY,THREAT_MODEL,WEB_APP}.md`, ADRs 0002 to 0006 and `experiments/unsloth/README.md` in the final `docs:` commit of the branch |
| M13 | Final verification, PR, merge, report | Merged | The verification is recorded in the final-verification entry of section 6 and the merge in the entry after it: pull request 1 was merged into `main` as `603bc19` after all 16 checks passed on its head `f9db96e` |

## 5. External dependencies that cannot be completed inside this environment

Each item names what it blocks and where the details are. Nothing below has been done; no live service was used for any
statement in this repository.

| Dependency | Blocks | Details |
| --- | --- | --- |
| An Azure subscription with an Azure AI Speech resource in a region that supports `en-IN`, `hi-IN` and `kn-IN` speech-to-text and text-to-speech, and optionally an Azure OpenAI deployment | Real speech recognition and synthesis; model-assisted signals and summaries | `docs/research/azure-speech-openai-verification.md`; settings in `.env.example` |
| An Azure Communication Services resource with an Event Grid subscription delivering `IncomingCall` to an Entra-secured webhook, plus `SPARTA_ACS_*`, `SPARTA_ENTRA_TENANT_ID` and `SPARTA_EVENT_GRID_AUDIENCE` | Every provider-wiring and conversation step of the live-test checklist | `docs/TELEPHONY.md` section 6 |
| A phone number that can receive calls in India. The research note records that ACS cannot acquire +91 numbers directly and lists the alternatives (Teams Phone Extensibility with Direct Routing or an approved Operator Connect carrier; an Indian programmable-voice provider that speaks a WebSocket media-stream protocol, which would need a `SPARTA_TELEPHONY_PLUGIN` implementation that does not ship) | Any real call reaching Sparta | `docs/research/acs-android-verification.md`, `docs/TELEPHONY.md` |
| Owner-side conditional call forwarding to the provider number: the codes are carrier-specific, Android exposes no API to read forwarding state, and no carrier has been tested | The AI conversation for a real owner | `docs/TELEPHONY.md`, `docs/ANDROID_SETUP.md` section 10 |
| Microsoft Limited Access approval for Azure AI Speech Personal Voice (`en-IN` and `hi-IN` only, region-limited, per the research note). Sparta records consent and stops at `pending_provider_approval`; nothing makes a personal voice usable | Personal voice | `docs/research/azure-speech-openai-verification.md`, `docs/PRIVACY.md` |
| An OpenID Connect issuer (for example a Microsoft Entra ID tenant) and app registrations. The API validates bearer tokens and the web app's sign-in (`oidc-client-ts`, Authorization Code with PKCE; `apps/web/src/lib/auth/oidc.ts`) is implemented, but neither has run against a real issuer; the Android app's OIDC sign-in is not implemented | Production authentication, any real user other than the development identity | `docs/WEB_APP.md` section 7, `docs/ANDROID_SETUP.md` sections 4 and 10 |
| A Firebase Cloud Messaging project and client and backend code for it (not implemented) | Instant escalation alerts on Android; today the app learns of an escalation on its next sync | `docs/ANDROID_SETUP.md` section 7 |
| A physical Android device, or an emulator with hardware acceleration | Call-screening role enrolment against a real incoming call, the instrumented tests, the R8 release build at runtime, TalkBack, and an end-to-end session of the app against a running backend | `docs/ANDROID_SETUP.md` sections 10 and 11 |
| Native speakers of Hindi and Kannada | Review of the Hindi and Kannada vocabularies and templates and of the evaluation dataset, none of which has been reviewed | `docs/MULTILINGUAL_SPEECH.md` |
| Legal review for the country where calls will be received | Any use with real callers | `docs/PRIVACY.md` section 13 |
| An Azure subscription in which to try `infrastructure/azure` (never deployed) by following `docs/DEPLOYMENT.md` and `docs/RELEASE_CHECKLIST.md`, whose own "What is not verified" section lists what stays untested | A production deployment | The Bicep header; `docs/DEPLOYMENT.md` |

## 6. Progress log

Dates are commit dates in UTC+05:30.

| Date | Commit | Entry |
| --- | --- | --- |
| 2026-11-17 | `2593eda` | Repository was empty; baseline pushed to `main`; `feat/sparta-v1` created and pushed |
| 2026-11-17 | `f7b4174` | Domain contracts, language engine and deterministic risk engine |
| 2026-11-17 | `d7aec99` | Conversation engine, planner, validator, summaries and unit tests |
| 2026-11-17 | `0485e15`, `59417ed` | Provider and telephony ports, simulators, resilience and metrics; provider settings and STT flush |
| 2026-11-17 | `e6f56d7` | Encrypted persistence layer, migrations and call service |
| 2026-11-17 | `a5c694b` | Synthetic multilingual evaluation dataset v1 (70 development and 70 held-out test scenarios) |
| 2026-11-17 | `c733a88` | Composition root, provider factory and end-to-end call-service tests |
| 2026-11-17 | `a97f969` | Azure Speech STT and TTS, Azure OpenAI and ACS adapters, webhook verification |
| 2026-11-17 | `8570e6c` | Owner, simulator and audit services; per-owner response models |
| 2026-11-18 | `0df79a8` | HTTP API, live socket, webhooks, retention and background jobs |
| 2026-11-18 | `8723432` | Per-mention denial handling and a broader en/hi/kn lexicon |
| 2026-11-18 | `879e666` | Evaluation harness with recognition coverage, Wilson intervals and noise sweep |
| 2026-11-18 | `45accdf` | First-request race, `assistant.finished` ordering and speaking state in call detail fixed |
| 2026-11-18 | `b09c936` | Code-switch matrix language, claim extraction and legitimate-category fixes |
| 2026-11-18 | `ef1e21f` | First evaluation results on the development and held-out test splits (policy `2026.11.2`) |
| 2026-11-18 | `2975796` | Real-time caller audio pipeline (voice-activity detection, per-utterance recognition, barge-in) |
| 2026-11-18 | `07a119e` | Android call-screening app and `docs/ANDROID_SETUP.md` |
| 2026-11-18 | `41d3b6c` | `docs/EVALUATION.md`; caller display separator fix; dead flag removed; translation flag default |
| 2026-11-18 | `01f5e37` | Wheel installs can migrate; pip-installable hashed lock file; stale docs and an unused setting corrected |
| 2026-11-18 | `f263382` | Summary no longer repeats a generic organisation word |
| 2026-11-18 | `62d7f7e` | Readable start-up failures when the database or Redis is unreachable |
| 2026-11-18 | `ac59c3e` | Quote-safe SSML attributes; clean `bandit` run |
| 2026-11-18 | `6572adc` | `features.translation` is always false until caller-speech translation exists |
| 2026-11-18 | `721f603` | Android Studio: the translation chooser is read-only while the backend reports no translation |
| 2026-11-18 | `117752e` | Security-review fixes: bounded input work (NFKC before the cap, 32 denial mentions), invisible-character deletion and look-alike folding, per-owner matcher cache with off-loop builds and a profile-save limit, bounded WAV header walk, shorter and deletable cached responses, development-identity bind guard, screening-event cap, batched retention |
| 2026-11-18 | `9352d0d` | `docs/SECURITY_REVIEW.md`; `docs/EVALUATION.md` note on engine changes after the test run |
| 2026-11-18 | `b88d48d` | `scripts/journey.py`: walks a running API through the screening journey |
| 2026-11-18 | `58e3a9a` | Live-event sequence race fixed (it stalled Simulator Lab autoplay): one atomic `UPDATE ... RETURNING`, `BEGIN IMMEDIATE` on SQLite files, a one-connection pool for in-memory SQLite; migration `0002`: a cached response is forgotten with the call it created |
| 2026-11-18 | `ff4a6a8` | OpenTelemetry spans for requests, provider calls and engine steps; the owner's name is replaced before a model provider is called |
| 2026-11-18 | `4c02212` | Tests for the spans, the import direction (ADR 0001), the model-signal allow-list and the owner-name replacement |
| 2026-11-18 | `4316669` | `/readyz` reports `migrations_pending` (503) until `python -m sparta migrate` has run |
| 2026-11-18 | `a7e796d` | Contract test of the shared-state stores, also against a real Redis when `SPARTA_TEST_REDIS_URL` is set |
| 2026-11-18 | `484e69b`, `7966187`, `affe463`, `8b674ee`, `77af0d0` | Hash-pinned API image and compose stack; scripts and `Makefile`; CI workflows and repository templates; Bicep for Azure; security policy, contributing guide, deployment guide and release checklist |
| 2026-11-18 | `531e665`, `2ea11c5`, `2c63616`, `3236870` | Fixes after `77af0d0`: the output validator judges a full owner name as a whole, so the AI disclosure is no longer replaced for names of several words (`531e665`); the replay driver waits by a 30 s wall-clock deadline and a replay that runs out of time is a 503 (`2ea11c5`); FastAPI's own OpenTelemetry instrumentation is switched off (it exported raw request paths and query strings and let a caller's `traceparent` choose a trace id), the idempotency request fingerprint is an HMAC keyed with the pepper and scoped to the owner, removing a blocked or trusted entry forgets the cached `POST` responses of that list, the owner-name replacement before a model call compares words in the detectors' canonical form, and the daily screening-event cap counts by the time the server received an event (`2c63616`); `tests/unit/test_transactions.py` pins the short-transaction property (`3236870`) |
| 2026-11-18 | `7b7e47a` | `apps/web`: owner console and Simulator Lab |
| 2026-11-18 | `0fd2a84` | Second security review, infrastructure part: deploy only from `main`'s history, per-secret Key Vault access, CI path filter, gitleaks allowlist, tag-protection and image-provenance notes |
| 2026-11-18 | `4f0160a` | The documentation set: README, architecture, safety model, multilingual speech, privacy, telephony, threat model, web notes, ADRs 0002 to 0006, this plan, the security review record |
| 2026-11-18 | `f934d0e`, `a17b54e` | First GitHub run, CodeQL: a case-sensitive tag regexp in an E2E test, two regex-range classes in production code (replaced by Unicode-category and translate-table code, equivalence checked on 20,000 random strings) and a 1024-bit RSA key generated by a test (the test now writes the public JWK directly; mutation-checked). Dependency review skips with a warning where the dependency graph is off (it answered 403) |
| 2026-11-18 | `a2d381a`, `99023e2` | Three flaky Android unit tests found by GitHub's runner, fixed by waiting for the settled state or the released file; the suite then passed four times in a row under full CPU load |
| 2026-11-18 | `13bb2eb` | The first GitHub runs recorded in the documentation; the E2E API no longer rate-limits its own test traffic |
| 2026-11-18 | `b507647` | The voice stage never shows "Call ended" before the closing sentence, and a stale snapshot cannot revive a finished call (found by GitHub's first Playwright run; `docs/WEB_APP.md` section 3) |
| 2026-11-18 | `5f980d1` | **An owner's display name can no longer cost a call its AI disclosure** (found by GitHub's Playwright run: a random owner id with four digits): the validator no longer judges the name as something the assistant said, a line that still fails is spoken without the name before the deflection, an e-mail address is not read aloud (`docs/SAFETY_MODEL.md` section 2) |
| 2026-11-18 | `99023e2` (the code of this branch; later commits change documentation only) | **Final verification**, on one Windows 11 machine, with the backend, web and end-to-end rows run one commit earlier (`5f980d1`, which differs only in one Android test file). `scripts\check.ps1 -Security`: all 13 steps passed (ruff, format, mypy on 107 files, `pytest` with PostgreSQL 16 and Redis 7: 2021 passed, OpenAPI contract current, dev-split evaluation unchanged (recall 87.8%, precision 94.7%, protected 33/33, no violations), `pip-audit` no known vulnerabilities, `bandit` clean, web lockfile, `eslint`, `tsc`, 310 `vitest` tests, `next build`). Web `npm run e2e`: 112 of 112 passed against the real API and the production build (Chromium only). Android `testDebugUnitTest`: 632 tests, four runs in a row under full CPU load, 0 failures; `lintDebug assembleDebug assembleRelease bundleRelease` (at `a17b54e`): lint 0 errors and 21 warnings, debug APK 22.7 MB, unsigned release APK 2.4 MiB, AAB 5.3 MiB. Docker Compose (PostgreSQL, Redis, API, web): healthy, `/readyz` ok at migration `0002`, `scripts\smoke.ps1` and `scripts\journey.py` passed. `gitleaks`: no leaks in the tree and the 52 commits. **GitHub** (pull request 1, `ubuntu-24.04`, the first runs of every workflow): all 16 checks passed on `99023e2`, including both Trivy image scans, CodeQL for three languages and the informational Playwright job; dependency review skipped because the repository's dependency graph is off. Not verified: anything that needs a live account, device or number, the deploy and publish steps (they run on `main` only) and any Azure deployment (README, "Never verified") |
| 2026-11-18 | `f9db96e` (head of pull request 1) and `603bc19` (the merge commit on `main`) | **Merged** (a merge commit; the branch is kept). The head differs from `99023e2` by documentation only and passed all 16 checks again. After the merge, on `main`: CI (including the informational Playwright job), CodeQL (no open code-scanning alert) and the secret scan passed; the container workflow built, scanned and **published** `ghcr.io/snowjug/sparta-api` and `ghcr.io/snowjug/sparta-web` (tags `main`, `latest` and `sha-<commit>`, with provenance and an SBOM; an anonymous request for the manifest answered 200), and the API image pulled by its digest answered `/readyz` and passed `scripts\journey.py`; the deploy workflow's `workflow_run` trigger fired and its preflight skipped the deploy because the three `AZURE_*` repository variables are not set. Dependabot, which now reads its configuration from the default branch, opened eight pull requests (#2 to #9: `redis` 8, `postgres` 18, an npm group, `typescript` 7, `@types/node` 26, `eslint` 10, a Python group and a Gradle group); none has been reviewed or merged. Not verified: the deploying job and any Azure deployment, the web image run from GHCR, branch protection and environment settings (none is set) |

## 7. Open items found while writing the documentation

Checked against the code at `5f980d1` on 2026-11-18 (the last commit that touches `services/api`). Re-verify before a release.

| Item | Evidence | Where it is described |
| --- | --- | --- |
| The cached responses to `POST /voice/enroll` and to the creation of a simulator scenario are not deleted with their record and live up to 24 hours (`DELETE /voice` does not remove the first; no route deletes a scenario) | `forget_cached_creations` is called only by the two list deletions in `api/routers/safety.py` | `docs/PRIVACY.md` section 6 |
| The owner-name replacement before a model call does not replace name words shorter than three letters or a name written in another script than the profile's | `redact_owner_name` in `risk/matchers.py`; "Al Li" and a Devanagari spelling of a Latin-script name were not replaced when run on 2026-11-18 | `docs/SAFETY_MODEL.md` section 9, `docs/PRIVACY.md` section 11 |
| The `FAILED` call state is defined but nothing sets it, so `sparta_call_failures_total` is never incremented | `ConversationEngine.fail` has no callers | `docs/ARCHITECTURE.md` |
| `escalate_uncertain_urgent`, `notify_on_high_risk` and `quiet_hours_start` / `quiet_hours_end` are stored and returned but nothing in the backend reads them (the Android app applies the last three to its own notifications; the web app only saves them) | `domain/models.py` field descriptions; `EscalationAnnouncer` in `apps/android/app/src/main/kotlin/io/github/snowjug/sparta/data/repo/BackgroundSync.kt` | `docs/SAFETY_MODEL.md` section 7 |
| The output validator's check for the owner's private facts is inert in live calls: only the evaluation harness sets `owner_private_markers` | `services/api/src/sparta/evaluation/runner.py` is the only writer | `docs/SAFETY_MODEL.md` |
| No account deletion and no purge of audit events | no code deletes users or `audit_events` | `docs/PRIVACY.md` |
| A blocked caller on the ACS adapter is not rejected: the call rings out | `telephony/azure_acs.py`; the telephony port has no reject operation | `docs/TELEPHONY.md` |
| Items the automated security review left open: the engine still runs on the event loop, matchers are still built per owner name, zero-width joiners next to Indic letters remain word breaks, look-alike folding is partial, and there was no human penetration test | `docs/SECURITY_REVIEW.md` ("What is still open") | `docs/SECURITY_REVIEW.md`, `docs/THREAT_MODEL.md` rows 24 and 25 |

## 8. Phase 2: the real-world telephony path

Branch `feat/real-world-telephony`, from `f419af2` (Phase 1, merged). Goal: one real telephone call end to end. Result:
**completion level A (code-complete)**; no real call was placed. The full account (inspection, blockers, decisions, what
was verified and how, the smallest ask to reach a real call) is [PHASE2_REAL_WORLD_PLAN.md](PHASE2_REAL_WORLD_PLAN.md); the
controlled whole-call tests are [PHASE2_CONTROLLED_RESULTS.md](PHASE2_CONTROLLED_RESULTS.md); the provider facts and their
sources are [research/phase2-provider-verification.md](research/phase2-provider-verification.md).

| # | Milestone | Status | Notes |
| --- | --- | --- | --- |
| P2-1 | `sparta doctor` provider preflight; `SPARTA_PROVIDER_ONLY_HOSTS` for tunnels | Committed (`3967114`) | Offline, `--online` (free, read-only) and `--allow-billable` (cents) checks; never prints a secret; always lists what only a real call can prove |
| P2-2 | Streaming Azure Speech recognition through the Speech SDK | Committed (`2ef9805`) | Partials, confidence, language identification; REST fallback; hash-pinned SDK lock. Never run against Azure |
| P2-3 | Azure OpenAI request adapts to the model family | Committed (`7219fcf`) | `max_tokens` or `max_completion_tokens`, `temperature`, from structured 400 answers |
| P2-4 | Twilio Media Streams adapter, doctor support, Event Grid caller pinning | Committed (`305dd40`) | A second provider because ACS cannot supply a number; mu-law codec; signed webhooks and media socket; `<Dial>` takeover; never run against Twilio |
| P2-5 | Honest takeover capability, cost caps, safe provider-failure closure, controlled matrix | Committed (`53b2406`) | 12 whole-call tests with scripted speech services |
| P2-6 | Android: stale-state bug fix, physical-device checklist | Committed (`ccec1c8`) | No device or emulator was available: every checklist row says NOT RUN |
| P2-7 | Infrastructure parameters (Twilio secret, caps, cost tag) and documentation | Committed (`db66c1c`) | The Bicep compiles and lints; not deployed |
| P2-7b | Security review of the new path and its fixes | On the branch | [SECURITY_REVIEW_PHASE2.md](SECURITY_REVIEW_PHASE2.md): no critical or high finding; one medium (conditional) and three low, the first three fixed and the fourth accepted and documented; three smaller defects fixed |
| P2-8 | A real call (Level B) | **Not started: blocked on external resources** | [PHASE2_REAL_WORLD_PLAN.md](PHASE2_REAL_WORLD_PLAN.md), section 6 |

New external dependencies (in addition to section 5): an **upgraded** Twilio account with one voice-capable number (a trial
account cannot be used); a public HTTPS URL for the API; a second phone to place the test call.
