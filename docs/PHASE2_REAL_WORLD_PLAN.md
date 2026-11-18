# Phase 2: the real-world telephony path

**Completion level: A (code-complete).** Phase 2 set out to complete one real telephone call end to end. No real call was
placed, because no provider account, number, Speech resource or public endpoint was available and creating billable
resources needs the owner's authorisation. This document records what was inspected, what was found, what was built, what
was verified and how, and the smallest set of things the owner must provide to reach Level B. It does not describe a
finished real-world product.

Branch `feat/real-world-telephony`, started from `f419af2b56a09264f3dc407f1e139af406a674b7` (Phase 1, merged).

## 1. Starting point (inspected, not assumed)

* `main` at `f419af2`: CI, CodeQL, secret scan and container-image builds green; both images published. Backend baseline on
  that commit: **2021 tests passed** (`pytest`, PostgreSQL 16 and Redis 7 in Docker).
* The Phase 1 report was checked against the code rather than trusted. More existed than the brief assumed: an ACS adapter
  (incoming-call idempotency, answer with bidirectional PCM16 media, a media WebSocket session with paced frames and
  `StopAudio` barge-in, hang-up, transfer, JWT and Event Grid verification), an audio pipeline (voice-activity detection,
  per-utterance recognition, ordered delivery, barge-in), call limits, a takeover flow and latency metrics. Azure OpenAI was
  already advisory-only behind a strict JSON schema.
* Gaps found: no preflight command; Azure speech-to-text was REST per utterance with no partials; the model adapter's
  `max_tokens`/`temperature` choice was fixed; `can_take_over` ignored whether the owner had a takeover number; no daily
  minute cap or per-number throttle; a provider that fails to speak left the call waiting forever; nothing ended a call in
  which neither side could be heard.
* Environment: every `SPARTA_*`/`AZURE_*` variable unset, no `.env` file; `az` logged in to a subscription with **no
  resource groups and no Communication, Speech or OpenAI resources**, and the `Microsoft.Communication`,
  `Microsoft.EventGrid` and `Microsoft.Cache` resource providers not registered (read-only commands only; nothing was
  created); no physical Android device, no emulator image, no tunnel tool.

## 2. What is possible, and the blockers

| # | Blocker | Why it matters | What clears it |
| --- | --- | --- | --- |
| B1 | ACS standalone telephony is being retired (2028-09-30) and a customer without an ACS resource created before 2026-10-23 cannot acquire numbers for it | No ACS number can be obtained for this subscription | Microsoft confirming eligibility, or another provider |
| B2 | ACS offers no India (+91) numbers | The owner's use case is India | Another provider or number route |
| B3 | No provider account or number exists; buying one is a billable act | No external call can reach Sparta | The owner creates an upgraded Twilio account and buys a number (or names another provider), or authorises it |
| B4 | A Twilio **trial** account cannot be used: `<Stream>` and `<Dial><Number>` are removed from its TwiML | Sparta could neither hear the caller nor transfer the call | Upgrade the account (the doctor reports a trial account as BLOCKED) |
| B5 | No Azure Speech resource and no Azure OpenAI deployment; the subscription is empty | No real recognition, synthesis or model output | The owner creates them (centralindia for Speech), or authorises it |
| B6 | No public HTTPS endpoint for the API | Providers cannot reach the webhooks | A deployment (the Bicep is ready, not deployed), or a dev tunnel with `SPARTA_PROVIDER_ONLY_HOSTS` |
| B7 | No physical Android phone, emulator or system image | Nothing about the Android app was run on a device | A phone (Android 10 or later) and `docs/ANDROID_SETUP.md`, "Physical-device validation checklist" |
| B8 | No legal review | AI disclosure, interception and recording rules, number use and retention need a lawyer, not code | A review against the list in `docs/PRIVACY.md` |

Sources and dates for B1 to B4 are in [research/phase2-provider-verification.md](research/phase2-provider-verification.md).
Nothing was bought, created or deployed, no secret was read or printed, and no real person was called.

## 3. Decisions

1. **A second provider behind the existing port, not a redesign.** ACS cannot supply a number (B1, B2), so the real-call path
   is built on **Twilio Media Streams** behind the same `TelephonyProvider` port. The ACS adapter stays. Twilio was chosen for
   a fully documented protocol, request signature and call-control API; the adapter can be replaced by an Indian provider
   without touching the call service. The stored provider kind is the generic `other`, so the API contract, the web app and
   the Android app are unchanged.
2. **The deterministic engine stays the decision maker.** The model is advisory and failing models change nothing
   (controlled test G4). No safety behaviour was changed; every change was covered by regression tests.
3. **A preflight before any real call.** `python -m sparta doctor --provider azure|twilio [--online] [--allow-billable]`
   reports PASS, WARNING, BLOCKED or UNVERIFIED per check, never prints a secret, and always lists what only a real call can
   prove.
4. **Streaming recognition through the Speech SDK** (partials, finals with confidence, language identification), with the REST
   adapter as the fallback.
5. **Fail safe, not silent.** A real call that cannot speak or hear is ended with a summary that says so.
6. **Cost brakes on by default** (daily minutes, calls per number), and honest takeover availability.
7. **Not done on purpose:** Personal Voice (not the blocker, off by default), buying numbers, creating Azure resources,
   deploying, recording audio, any legal claim.

## 4. What was built and how it was verified

| Commit | Change | Verified by |
| --- | --- | --- |
| `3967114` | `sparta doctor` and `SPARTA_PROVIDER_ONLY_HOSTS` (a tunnel host serves only health, webhooks and media) | 67 tests (doctor 47, provider hosts 20) |
| `2ef9805` | Streaming Speech SDK recognition: partials, finals, confidence, language, `stt_service` latency, thread-safe callbacks, static error mapping; hash-pinned lock for the SDK | 27 tests against a threaded fake SDK plus a contract test against the real SDK 1.53.1 |
| `7219fcf` | Azure OpenAI request adapts to the model family (`max_tokens` or `max_completion_tokens`, `temperature`) from structured 400 errors | 7 tests |
| `ccec1c8` | Android: Take Over stays disabled once taken over (a stale snapshot bug); physical-device checklist | Android unit tests (634), lint, debug build; checklist rows all say NOT RUN |
| `305dd40` | Twilio adapter (signed webhooks and media upgrade, per-call token, mu-law, marks, clear, `<Dial>` takeover, `<Reject>`), doctor support, Event Grid caller pinning, v2 endpoint for continuous language identification, TTS required in production | 100+ adapter, codec, API and doctor tests |
| `53b2406` | Honest takeover capability, cost caps, safe provider-failure closure, abandoned-playback fix, stage latency metrics, the controlled matrix | 12 matrix tests ([PHASE2_CONTROLLED_RESULTS.md](PHASE2_CONTROLLED_RESULTS.md)) |
| the commit that adds [SECURITY_REVIEW_PHASE2.md](SECURITY_REVIEW_PHASE2.md) | Fixes from the security review of this path: provider-only hosts compare names and fail closed (and need explicit trusted hosts), a media socket displaces the live stream only after it proves the token, production requires the Event Grid caller pin and refuses to skip the media signature, non-ASCII credentials are refused cleanly, a takeover number is dialled as strict E.164 and never guessed, doctor output from a remote host is sanitised; two documented dummy test values allowlisted in `.gitleaks.toml` | 23 tests in the five affected test files fail on the earlier code and pass now (plus `test_numbers.py`, which cannot import `dial_number` there), and the whole suite passes |

Later commits on the branch add the infrastructure parameters and the documentation. The final regression results are in
the pull request.

Other verified facts: the API image builds with the Speech SDK, and the SDK imports and builds a streaming recogniser
(continuous language identification, 8 kHz push stream) in the `python:3.12-slim` runtime image without extra system
packages; the Bicep templates compile and lint with Bicep 0.48.1 (they have not been deployed).

## 5. Completion level, honestly

| Level A requirement | State |
| --- | --- |
| Real-provider code | Implemented (Twilio, ACS) against fakes; UNVERIFIED live |
| Real Speech integration | Implemented (SDK streaming and REST; TTS mu-law for Twilio); UNVERIFIED live |
| Real model integration | Implemented (Azure OpenAI, advisory, strict JSON schema, adaptive request); UNVERIFIED live |
| Callbacks secured | Twilio signatures and per-call stream tokens; ACS and Event Grid JWTs with the calling application pinned; replay and duplicate handling; tested with forged and replayed requests |
| Provider preflight | `sparta doctor` |
| Tests pass with fakes | See the pull request for the exact commands and counts |
| Deployment code ready | Bicep and the deploy workflow, extended; not deployed |
| Exact external requirements documented | Section 6 |
| Branch pushed, pull request created | Yes; not merged |

**Not Level B**: no real call reached Sparta, no AI disclosure was heard by a person, no caller speech reached real
recognition, no real voice was heard, no multilingual journey or scam refusal was verified on a real line, no real latency
was recorded. **Not Level C**: nothing ran on a phone, no deployment is monitored, no real failure path was exercised.

## 6. The smallest ask to reach Level B

Any one of these routes works; the first is the shortest.

1. **A Twilio account that is upgraded (not a trial), one voice-capable number on it** (a US number is enough to prove the
   path; an Indian `+91800` toll-free number needs a regulatory bundle), and its Account SID and Auth Token handed to the
   deployment as secrets (`SPARTA_TWILIO_ACCOUNT_SID`, `SPARTA_TWILIO_AUTH_TOKEN`), never pasted into chat or the repository.
2. **An Azure Speech resource in `centralindia`** (key and region), and optionally an Azure OpenAI deployment.
3. **A public HTTPS URL** for the API: either authorise the Azure deployment (`docs/DEPLOYMENT.md`; it creates billable
   resources and says which ones to stop afterwards) or run the API locally behind a dev tunnel with
   `SPARTA_PROVIDER_ONLY_HOSTS` and `SPARTA_TRUSTED_HOSTS` set (both are required).
4. **A second phone you control** to place the test call, and your consent to be recorded if you want audio kept (none is
   stored by default).
5. Then run `python -m sparta doctor --provider twilio --online --allow-billable` (cents), place the call, and follow
   `docs/TELEPHONY.md`, section 6.

For Level C add a physical Android phone, a deployed and monitored environment, several real calls and a legal review.
