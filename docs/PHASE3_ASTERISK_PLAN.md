# Phase 3 plan: free local voice with Asterisk (SIP)

Branch `feat/asterisk-open-voice`. Decision record: [ADR-ASTERISK-MEDIA-BRIDGE](DECISIONS/ADR-ASTERISK-MEDIA-BRIDGE.md).

## 1. Goal, and what it is not

Let a person call Sparta from a SIP client (Linphone on Android, or any softphone) over a local network, and have a real
two-way voice conversation with the assistant, using only free and open-source parts:

```
SIP client ──SIP/RTP (G.711)──▶ Asterisk ──AudioSocket (PCM 8 kHz)──▶ Sparta
 (Linphone)   UDP 5060 + RTP     PJSIP + dialplan      TCP :8090       VAD → STT → safety engine → TTS
     ▲                                                                          │
     └───────────────────────────── audio back, paced in 20 ms frames ◀─────────┘
```

| Name | What it is | Needs a paid service? |
|---|---|---|
| **SIMULATOR** | Typed callers in the Lab, no audio. Works today. | No |
| **LOCAL SIP** (this phase) | Real voice over IP between a SIP client and Sparta through Asterisk on a trusted network. | **No** |
| **PSTN** | An ordinary mobile or landline number reaching Sparta. | **Yes**: a carrier, a phone number (DID) and a SIP trunk. **Not delivered by this phase.** |

Local SIP is not "phone-call support". Nobody can ring Sparta from a normal phone number with it.

## 2. Base branch and the dependency on PR #11

Phase 3 builds on the Twilio/Phase 2 work (`doctor`, streaming STT, cost caps), which is open as PR #11 and is **not
merged**. The branch was therefore created from PR #11's last verified commit (`4409ff9`). The Phase 3 PR targets `main`
(so the repository's CodeQL and dependency-review workflows, which only run for PRs into `main`, also run) and says so; its
compare link against `feat/real-world-telephony` shows only the Phase 3 commits. If PR #11 is merged first the diff
shrinks to the Phase 3 commits; if it is closed, Phase 3 must be rebased.

## 3. Baseline recorded before any change (commit `4409ff9`)

| Suite | Result |
|---|---|
| Backend pytest | 2321 passed |
| Web vitest | 310 passed (from the Phase 2 README) |
| Web Playwright | 112 passed (from the Phase 2 README) |
| Android JVM unit tests | 634 passed; lint 0 errors, 21 warnings (from the Phase 2 README) |
| Dev-split evaluation | recall 0.878, precision 0.9474, protected 33/33, 0 violations |

The final numbers are in the PR description and the final report.

## 4. Decisions

* **Media:** AudioSocket with dialplan HTTP callbacks; Asterisk 22.12.0 built from a pinned tarball. See the ADR.
* **Conversation:** the existing deterministic safety engine. No large language model is added.
* **Local speech (one of each):**
  * STT: **faster-whisper** (MIT; CTranslate2; CPU int8; GPU optional).
  * TTS: **Piper** (engine GPL-3.0-or-later; voices have their own, partly non-commercial, licences).
  * Both are an **optional extra**, never in the default image or lock. Models are downloaded on request, pinned by SHA-256
    and kept outside git. `STT_PROVIDER` and `TTS_PROVIDER` take `azure|local|fake`.
  * Honest capability: English works; Hindi is usable but unmeasured; **Kannada is experimental** (Whisper `small` is
    unusable for it; a community Kannada Piper voice exists and is non-commercial). No native-quality claim is made
    without native-speaker review. Details and the research behind them: [MULTILINGUAL_SPEECH.md](MULTILINGUAL_SPEECH.md).
* **Free end-to-end test:** a mature headless SIP client (baresip) in Docker plays a WAV into a real Asterisk call and
  records what comes back. Tone-coded fake speech (`providers/fake_tone.py`) makes the test deterministic without models;
  a second variant uses real Piper and Whisper audio.

## 5. Work breakdown

| # | Milestone | Status |
|---|---|---|
| 1 | Fake tone STT/TTS, `fake` provider setting, production guard | done |
| 2 | ADR and this plan | done |
| 3 | Asterisk image and configuration (`infrastructure/asterisk/`), compose profile | see git log |
| 4 | Asterisk provider: AudioSocket server, webhooks, pacer, DTMF, transfer, duplicate protection, cleanup | see git log |
| 5 | Local STT/TTS providers, model manifest and fetch command | see git log |
| 6 | Provider matrix tests, malformed/oversized/duplicate/timeout/interruption, multilingual and prompt-injection suites | see git log |
| 7 | `sparta doctor --provider asterisk` | see git log |
| 8 | Minimal UI state (provider, connection, PSTN, takeover) and OpenAPI | see git log |
| 9 | Docker SIP end-to-end, latency measurements, evidence JSON | see git log |
| 10 | Docs, security review, threat model | see git log |
| 11 | Full regression, PR, CI | see PR |

## 6. Completion levels

| Level | Meaning | How Phase 3 proves it |
|---|---|---|
| **A** | Code complete, real SIP call unverified | Provider, image, doctor, tests, docs, PR. |
| **B** | A real external SIP client call verified | baresip (a separate container, real SIP and RTP, real G.711) calls Asterisk, Sparta answers, real audio enters Sparta, a real transcript is produced, the engine replies, TTS audio comes back, the caller interrupts, the call ends and the summary is readable. The speech is synthetic (Piper), not a human voice. |
| **C** | Physical Android phone verified | Needs a phone on the same network. Checklist only until someone runs it. |
| **D** | PSTN | Not required, not claimed. |

The level actually reached is stated in the final report, with the evidence.

## 7. Measurement labels

Latency figures are never estimated. Each is labelled `fake` (tone-coded providers, in process), `unit`, `integration`
(real Sparta provider code with a scripted Asterisk-side client), `local SIP` (real Asterisk and a headless SIP client) or
`physical Android SIP`. Only the labels that were actually run appear in the results.

## 8. Risks

* Docker Desktop UDP handling for a phone on the LAN is unverified here (no phone attached).
* Whisper on this CPU may be too slow for conversational latency with the larger models; reported as measured.
* Kannada recognition and speech output cannot be validated without native speakers.
