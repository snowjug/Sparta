# Sparta — Implementation Plan & Progress Log

> Living document. Updated at every checkpoint. Statements here describe verified state only; anything not yet built is
> listed under *Remaining* or *External dependencies*.

## 1. Starting conditions (recorded 2026-11-17)

| Item | Value |
| --- | --- |
| Repository | https://github.com/snowjug/Sparta (public) |
| State at start | **Empty**: no commits, branches, issues, PRs, rulesets, README or configuration to preserve |
| Baseline commit (`main`) | `2593eda` — `chore: add repository baseline` (README stub, `.gitignore`, `.gitattributes`, `.editorconfig`) |
| Working branch | `feat/sparta-v1` (cut from `main@2593eda`) |
| Host | Windows 11 (PowerShell 5.1), Node 26, npm 12, Python 3.15 (system) + Python 3.12 via `uv`, Docker Desktop 29 (WSL2) |
| Not preinstalled | JDK, Android SDK, Gradle, `make` (handled: see Android milestone and `scripts/`) |
| Push identity | Repository owner account `snowjug`, supplied per-process; no tokens are stored in the repo or git config |

## 2. Scope and honesty rules

* The product ships a **fully functional simulator** (browser/local call simulator) and a **provider-agnostic telephony
  abstraction**. The Azure Communication Services adapter is implemented against documented interfaces and tested with
  mocked provider boundaries; **no live PSTN call has been made** and none is claimed.
* Android uses the platform `CallScreeningService` (allow / silence / reject / caller-ID metadata). Ordinary Android
  apps **cannot** capture or inject cellular call audio; the app never implies two-way AI audio on a cellular call.
  Conversational audio requires the call to reach a programmable telephony number (forwarding concept, see
  `docs/TELEPHONY.md`).
* Evaluation numbers are generated from real test runs only (`docs/EVALUATION.md`).

## 3. Architecture decisions (summary — details in `docs/DECISIONS/`)

| # | Decision | Reason |
| --- | --- | --- |
| 0001 | Modular monolith (`services/api`, package `sparta`) with internal boundaries for risk engine, orchestrator, providers and telephony | Fewer moving parts; every boundary is an interface + tests, so services can be split later |
| 0002 | Deterministic, data-driven safety policy + language packs (JSON) override any model output | Safety before model creativity; auditable; reusable on-device |
| 0003 | Event-sourced call state (immutable turns/provider events + snapshot) with injectable clock | Deterministic replay, crash recovery, testable timeouts |
| 0004 | Dev identity vs OIDC auth with hard production guard | Safe local run, impossible to enable silently in production |
| 0005 | Android native screening + backend conversational telephony are separate capabilities | Platform reality (no call audio for third-party apps) |

## 4. Milestones

Legend: ☐ not started · ◐ in progress · ☑ done and verified

| # | Milestone | Status | Notes |
| --- | --- | --- | --- |
| M0 | Repository baseline, branch, plan, monorepo skeleton | ◐ | baseline pushed; skeleton in progress |
| M1 | Backend foundation: settings, logging/redaction, domain contracts, DB models, migrations, OpenAPI export | ☐ | |
| M2 | Language engine (en/hi/kn, Hinglish/Kanglish, registry for future languages) | ☐ | |
| M3 | Risk & safety engine, versioned policy, prompt-injection defense | ☐ | |
| M4 | Conversation orchestrator (state machine, planner, validator, barge-in, silence, takeover, summary) | ☐ | |
| M5 | Provider layer (STT/TTS/LLM/VAD, resilience), telephony abstraction, simulator + Azure adapters, webhooks | ☐ | |
| M6 | REST + WebSocket API, auth, rate limits, idempotency, audit, retention | ☐ | |
| M7 | Backend tests + multilingual evaluation suite and generated report | ☐ | |
| M8 | Web experience (all required screens) | ☐ | |
| M9 | Web tests: unit, a11y, Playwright E2E (10-step scenario + extras) | ☐ | |
| M10 | Android app + build + unit tests | ☐ | |
| M11 | Docker, Compose, scripts, Bicep, CI/CD, repo hygiene files | ☐ | |
| M12 | Documentation set, ADRs, threat model, deployment checklist | ☐ | |
| M13 | Final verification, PR, merge, report | ☐ | |

## 5. External dependencies that cannot be completed inside this environment

Filled in as they are confirmed (see `docs/TELEPHONY.md`, `docs/DEPLOYMENT.md`, `docs/ANDROID_SETUP.md`):

* Azure subscription, Speech resource, Azure OpenAI deployment, ACS resource and a PSTN-capable number or SBC.
* Azure AI Speech *Personal Voice* requires Microsoft Limited Access approval; Sparta ships the full consent/enrollment
  flow with a predefined-voice fallback.
* Firebase/FCM project for OS-level push to Android (the app and backend ship the notifier interface, live-channel
  notifications and WorkManager sync without it).
* A physical Android device for end-to-end role enrollment against a real incoming call.
* Legal review items listed in `docs/DEPLOYMENT.md` (AI disclosure, recording consent, interception rules, number
  acquisition, retention, cross-border transfer, personal voice, India-specific obligations).

## 6. Progress log

| Date | Commit | Entry |
| --- | --- | --- |
| 2026-11-17 | `2593eda` | Repository was empty; baseline pushed to `main`; `feat/sparta-v1` created and pushed |
