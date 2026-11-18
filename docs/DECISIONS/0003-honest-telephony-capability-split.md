# ADR 0003 — Honest telephony capability split

* Status: accepted
* Date: 2026-11-18

## Context

The product vision is an AI that answers unknown callers on the owner's behalf. The platform facts, recorded with their
sources in [research/acs-android-verification.md](../research/acs-android-verification.md), are:

* An ordinary Android app can become the call-screening app and allow, silence or reject a call, but it cannot answer the
  call, speak to the caller, bridge it, record it or hear its audio.
* A conversation therefore needs the call to reach a programmable telephony number, with the owner forwarding unknown or
  unanswered calls to it. Azure Communication Services cannot acquire +91 numbers directly, standalone ACS telephony is
  documented as retiring on 2028-09-30, and PSTN transfer, call forwarding behaviour per carrier and several wire details
  could not be verified without live accounts.

A product that showed "AI is answering your calls" for a call that only an Android screening rule touched would be
dishonest, and a UI that offered Take Over where no provider can bridge a call would do nothing.

## Decision

1. **Three separate capabilities**: native Android screening, a built-in simulator, and a programmable-number provider
   (Azure Communication Services, or another provider through a plugin and signed webhooks). Provider selection is
   configuration (`TELEPHONY_PROVIDER=simulator|azure|other`).
2. **Capabilities are declared, not assumed.** `TelephonyCapabilities` (`telephony/base.py`) states what a provider can do
   (answer, play, stop playback, transfer, hang up, receive caller audio, two-way audio, DTMF, simulated, live calls
   supported). `CallDetail.capabilities` turns that into the owner controls that are real for each call, with a reason
   (`takeover_note`, `audio_note`). For ACS, two-way audio is true only while the call has a live media socket.
3. **Unsupported actions fail loudly.** Owner actions the provider cannot perform return 409 `unsupported_by_provider`;
   `POST /calls` is refused for real providers because their calls start when the provider delivers them.
4. **The simulator is a supported mode, not a hidden fake.** It is labelled `simulated: true` on every call and event;
   its takeover is a labelled simulation; its speech recognition cannot transcribe audio and its synthesis produces no
   audio.
5. **Native screening events are recorded as `screening_only` calls** (provider `android_screening`) with no transcript and
   capabilities that offer no take over, continue or end control.
6. **Adapters are built against mocked boundaries and labelled UNVERIFIED** wherever live behaviour is unknown. Nothing
   claims a live call was tested.

## Consequences

* Positive: no screen can promise more than the provider delivers; each provider's limits are visible in the data model
  and in the clients; adding a provider means implementing one port.
* Positive: the whole product, including escalation and takeover flows, can be developed and demonstrated without a phone
  number.
* Negative: on a phone with no provider number and no forwarding, Sparta cannot talk to callers; the owner must obtain a
  number, set up conditional forwarding with the carrier (which Sparta can neither set nor read) and complete legal review.
* Negative: live behaviour of the Azure adapter, PSTN transfer and per-carrier forwarding remain unverified until someone
  runs the checklist in [TELEPHONY.md](../TELEPHONY.md) with real accounts.
* Negative: provider-delivered calls are routed to a single configured owner; per-number multi-owner routing is not
  implemented.

## Alternatives considered

* **Present one "answering" status for every path.** Rejected: untrue for screening-only calls and for the simulator.
* **Implement only Azure Communication Services.** Rejected: ACS cannot provide +91 numbers directly and its standalone
  telephony has a documented retirement date, so the abstraction has to allow other providers.
* **Hide the simulator behind a development flag only.** Rejected: it is the only path that works without credentials, so it
  is part of the product and labelled as such.
* **Fake call audio on Android.** Not possible for an ordinary app according to the verification notes, and not attempted.
