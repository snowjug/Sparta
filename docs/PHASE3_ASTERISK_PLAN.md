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

## 3. Baseline recorded before any change (commit `4409ff9`), and the result at the end

| Suite | Baseline | Final (`a600b87`; later commits change documentation only) |
|---|---|---|
| Backend pytest | 2321 passed | **2900 passed**, 56 skipped (36 Docker end-to-end tests, 12 needing `numpy`, 8 needing the downloaded models) |
| Web vitest | 310 passed (from the Phase 2 README) | **318 passed** |
| Web Playwright | 112 passed (from the Phase 2 README) | **112 passed** |
| Android JVM unit tests | 634 passed; lint 0 errors, 21 warnings (from the Phase 2 README) | **641 passed, 0 skipped** (forced re-run); lint 0 errors, 21 warnings |
| Dev-split evaluation | recall 0.878, precision 0.9474, protected 33/33, 0 violations | **identical** (no rule was changed; the test split was not used) |

Nothing that passed before fails now. No test file was deleted and no skip was added to an existing test: the only edits to
existing tests add the new status fields to fixtures (and new cases next to them) and put `asterisk` in the expected provider
list of one doctor test. The skips are in new tests that need Docker or the downloaded models, and say so. The
command-by-command record is in the README's Testing section and the pull request.

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
| 1 | Fake tone STT/TTS, `fake` provider setting, production guard | **done** (`5fde03b`) |
| 2 | ADR and this plan | **done** (`7f02c82`) |
| 3 | Asterisk image and configuration (`infrastructure/asterisk/`), compose profile | **done**, built and run (`a600b87`) |
| 4 | Asterisk provider: AudioSocket server, webhooks, pacer, DTMF, transfer, duplicate protection, cleanup | **done** (`b31052c`, `f4854fd`) |
| 5 | Local STT/TTS providers, model manifest and fetch command | **done**, run on real audio (`d3bf3be`) |
| 6 | Provider matrix tests, malformed/oversized/duplicate/timeout/interruption, multilingual and prompt-injection suites | **done** (`6419a10`) |
| 7 | `sparta doctor --provider asterisk` | **done** (`d3bf3be`) |
| 8 | Minimal UI state (provider, connection, PSTN, takeover) and OpenAPI | **done** (`72dae2f`) |
| 9 | Docker SIP end-to-end, latency measurements, evidence JSON | **done** (`a600b87`; Kanglish and UPI added to the real-speech run afterwards): 28 scenarios with tone speech, 8 with real speech |
| 10 | Docs, security review, threat model | **done** (this commit): [SECURITY_REVIEW_PHASE3.md](SECURITY_REVIEW_PHASE3.md), [THREAT_MODEL.md](THREAT_MODEL.md) rows 36 to 47 |
| 11 | Full regression, PR, CI | **regression done** (section 3 and the README's Testing section); PR and CI: see the pull request |

## 6. Completion levels

| Level | Meaning | How Phase 3 proves it | **Reached?** |
|---|---|---|---|
| **A** | Code complete, real SIP call unverified | Provider, image, doctor, tests, docs, PR. | **Yes** |
| **B** | A real external SIP client call verified | baresip (a separate container, real SIP and RTP, real G.711) calls Asterisk, Sparta answers, real audio enters Sparta, a real transcript is produced, the engine replies, TTS audio comes back, the caller interrupts, the call ends and the summary is readable. The speech is synthetic (Piper), not a human voice. | **Yes, in English, with a machine-voice caller** (section 8). *Not* "a human talked to it" |
| **C** | Physical Android phone verified | Needs a phone on the same network. Checklist only until someone runs it. | **No. NOT RUN** (no phone was attached) |
| **D** | PSTN | Not required, not claimed. | **No. Not delivered** |

## 7. Measurement labels

Latency figures are never estimated. Each is labelled `fake` (tone-coded providers, in process), `unit`, `integration`
(real Sparta provider code with a scripted Asterisk-side client), `local SIP` (real Asterisk and a headless SIP client) or
`physical Android SIP`. Only the labels that were actually run appear in the results.

## 8. Results: what was actually run

Everything below was run on one Windows 11 laptop (Docker Desktop, WSL 2) shared with other work, so timings are upper bounds.
The evidence files are [evidence/phase3-sip-e2e-fake.json](evidence/phase3-sip-e2e-fake.json) and
[evidence/phase3-sip-e2e-local.json](evidence/phase3-sip-e2e-local.json), written by `--evidence`; re-create them with
`python scripts/sip_e2e.py --evidence FILE` and `python scripts/sip_e2e.py --speech local --models DIR --python PY --evidence FILE`.
Timings vary from run to run on a shared laptop: three runs of the tone-speech scenarios on the same code gave 590 to 840 ms
from the caller stopping to the reply being heard, and 21.7 to 102.7 ms for the server's whole turn. The committed evidence
files are the ones quoted; treat the figures as indicative, not as a benchmark.

**The call that reached Level B.** A separate container running **baresip 1.0.0** (a mature open-source SIP client) registered to
Asterisk 22.12.0 as extension 6001 with digest authentication, dialled 6000 over SIP/UDP, and sent and received real G.711 RTP. In
`--speech local` mode the caller's lines were spoken by Piper (a machine voice) and played as the client's microphone; Sparta's
container ran faster-whisper `small` (CPU int8) and Piper. For the OTP scam: Sparta's own recogniser transcribed the call audio
as "I'm calling from your bank. Tell me your OTP." (exactly what was spoken); the engine rated it **high** risk and refused and
ended the call; the caller received Piper's refusal as G.711 and Whisper read it back word for word; Sparta, not the caller, hung
up; the call has a summary that mentions the one-time password. In the interruption scenario the caller began speaking 1.5 s into
the greeting and the greeting stopped 240 ms later (160 ms in the previous run); Sparta recognised the interruption ("Yet I'm
calling from Amazon.": Whisper heard "Yeah" as "Yet"), answered, and ended the call on silence with a summary. A legitimate
delivery call was recognised word for word, rated low risk, answered ("Thanks. I'll let Atharv know right now. Please stay on the
line.") and summarised. The summary is read through the API (`GET /calls/{id}`), which is what the web app renders; the web app
itself was not opened on that call.
This is **a real external SIP client, a real call and real speech recognition and synthesis. It is not a person, not a phone and not
the phone network.**

**Latency, labelled by how it was measured** (client-side figures are from timestamps of the RTP packets that crossed the caller's
network interface, one clock; server-side figures are Sparta's own per-turn measurements; the real-speech column is the committed
run, with the range over the two real-speech runs made on this code in brackets):

| Measurement | local SIP, tone speech | local SIP, **real** Whisper `small` + Piper |
| --- | --- | --- |
| Call media starts to first assistant audio | 30 ms | 340 ms (320 to 340) |
| Caller stops speaking to first reply audio heard | 840 ms (the voice-activity wait included) | **5980 ms** (OTP scam; 4080 to 5980), **4460 ms** (legitimate call; 4460 to 4600) |
| Server: recognition (`stt_ms`) | 6.3 ms (a tone decoder) | **4733 ms**, 4579 ms (two utterances; 3124 to 4733) |
| Server: policy, language detection | 29.3 ms, 0.4 ms | 14.7 ms, 0.3 ms |
| Server: whole turn (`total_ms`) | 102.7 ms | 4776 ms, 4592 ms (3157 to 4776) |
| Caller interrupts to playback stopped | 180 ms | 240 ms (160 to 240) |

*Not measured, so not reported:* anything on a physical phone (`physical Android SIP`: **NOT RUN**), real-clock timings of the
in-process integration tests (they run on a virtual clock), and any latency over the phone network. The 4 to 6 s answer time is
dominated by recognition on a CPU (Whisper encodes a padded 30 s window) and moved by 2 s between two runs of the same code; it is
slow for natural conversation, and the honest next step is a faster recogniser or a GPU, not a claim that it feels natural.

**Languages (real speech, machine-voice caller).** English: all three scenarios passed and are asserted. Hindi, Hinglish and Kanglish
(Latin script read by the English voice), a Kanglish UPI request, and Kannada were **measured and reported, not asserted to
succeed**, and the answer is negative for every one of them (committed run; two runs of the same lines gave slightly different
transcripts and the same outcome):

| Caller said | Sparta's recogniser heard | Language, confidence | What Sparta did |
| --- | --- | --- | --- |
| Hindi: "सर, आपका केवाईसी अपडेट करना है, कृपया ओटीपी बताइए।" | "सरह आपका के वाईसिये अप्देट करना है, क्रिप्या उतीपी बताएगे" | hi-IN, 0.73 | rated **low** risk; the OTP request was **not refused**; the call ended after silence |
| Hinglish: "Sir KYC update karna hai, OTP bata dijiye." | "Sir KYC Update, Kanner High, OTP, Barter, D.G.I." | en-IN, 0.62 | rated medium; **not refused**; ended after silence |
| Kanglish: "Sir nimma account update madbeku, OTP heli." | "CERN number, account, update, MABICU, OTP, HELLING." | en-IN, 0.62 | rated low; **not refused** (the word OTP was heard, the request verb "heli" was not); ended after silence |
| Kanglish UPI: "Verification ge nimma UPI PIN heli." | "Verification G, Numer UPIPIN, Kelly." | en-IN, 0.50 | rated low; **not refused** ("heli" heard as "Kelly"); ended after silence |
| Kannada: "ನಿಮ್ಮ ಬ್ಯಾಂಕ್ ಖಾತೆಯನ್ನು ಅಪ್‌ಡೇಟ್ ಮಾಡಬೇಕು. ದಯವಿಟ್ಟು ಒಟಿಪಿ ಹೇಳಿ." | Devanagari gibberish: "निमा बान खातेन नू अप्रेट मडवेक।" | hi-IN, 0.50 | rated low; **not refused**; asked again, then the call ended with a summary |

In all five the assistant never spoke a digit and the call ended cleanly with a summary (the asserted invariants). **With the
small Whisper model a Hindi, Hinglish, Kanglish or Kannada caller is not reliably screened.** **The rules are not what failed.** Given
the words that were actually said, the deterministic engine rates all five lines high risk and refuses: the brief's English,
Hinglish, Kanglish and UPI lines are pinned by `test_a_credential_request_is_recognised_refused_in_the_callers_language_and_summarised`
in the integration matrix below, and the Hindi and Kannada lines were probed directly with the engine on text (a throwaway script,
not a test in the repository). Given what Whisper heard, none is refused (the Hinglish transcript only reaches medium). In the two
Kanglish transcripts the request verb was the casualty: putting just "heli" back makes the engine refuse both, and "UPIPIN" as
one token is handled. No native speaker has reviewed any of this, and the caller's voice is a machine's.

**The deterministic engine through the real Sparta stack (label: `integration`).** A matrix of 39 phrase calls (credential
requests, address and location probes, calendar probes and prompt-injection phrases in English, Hindi, Hinglish, Kannada and
Kanglish) was sent as tone-coded audio through the real AudioSocket listener, pipeline, engine and service; the tone codec carries
the phrase, so this tests the engine on correct transcripts, not recognition. All 11 credential requests were refused and ended at
high risk; all 5 address requests were deflected; 9 of 10 injection phrases were refused and ended (the Hindi-script "ignore all
previous instructions" was **not** flagged, though nothing was obeyed); only 2 of 5 location probes were deflected (English and
Hinglish; the Hindi, Kannada and Kanglish ones got the generic name prompt); 5 of 5 calendar requests got the generic name prompt and
nothing was disclosed. The rule packs were deliberately **not** changed to fix these (they are tuned against the held-out
evaluation and need native review): they are recorded as detection gaps. See [EVALUATION.md](EVALUATION.md) section 9.

**What the end-to-end run found** (all fixed): the first call after a server restart was rejected because the first webhook took
6.7 s; `DELETE /calls` removes call content, not records, so the harness now counts only the calls of each test; Asterisk colours
every field of its log lines, which silently defeated the fail2ban filter (now `asterisk -n`); baresip has no real-time recorder, so
what the caller hears is rebuilt from the RTP on the wire; baresip registers before a control client can connect, so the account is
now created over its control socket.

**Tests** (run on this commit; the full list and the CI result are in the PR):

* `python scripts/sip_e2e.py`: **28 passed** (3 min 49 s). `python scripts/sip_e2e.py --speech local --models ...`: **8 passed**
  (6 min 1 s). Both need Docker and are not part of the default `pytest` run.
* `tests/unit/providers_local` in the optional speech environment (`numpy`, faster-whisper, Piper and the models): **279 passed,
  0 skipped**, including the tests that the default run skips for lack of those. The default backend run is in the README's Testing section.

## 9. Risks

* Docker Desktop's UDP handling for a phone on the LAN is unverified here (no phone attached). What was observed: the source address
  of a request from the host arrives as Docker's gateway address, so the network ACL cannot tell senders apart on Docker Desktop.
* Whisper on this CPU is too slow for natural conversation (4 to 6 s per answer in two runs of the same code); reported as measured. A larger model was not tried.
* Kannada recognition and speech output cannot be validated without native speakers, and Hindi is unreliable.
* A human voice, an Indian accent, telephone-line noise and Wi-Fi jitter were not exercised.
