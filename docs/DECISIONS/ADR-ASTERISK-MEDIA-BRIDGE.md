# ADR — One real-time media path for local SIP (Asterisk)

* Status: accepted
* Date: 2026-11-19
* Phase: 3 (free, open-source telephony path). Related: [ADR 0003](0003-honest-telephony-capability-split.md),
  [PHASE3_ASTERISK_PLAN.md](../PHASE3_ASTERISK_PLAN.md), [TELEPHONY.md](../TELEPHONY.md).

## Context

Phase 3 adds `SPARTA_TELEPHONY_PROVIDER=asterisk`: an Android (or desktop) SIP client registers to a local Asterisk, dials
extension 6000 and talks to Sparta in both directions, with no Twilio, no PSTN number and no paid trunk. The call has to
reach Sparta as a live, two-way audio stream so that the existing audio pipeline (VAD, speech-to-text, deterministic safety
engine, text-to-speech) works unchanged, including barge-in.

Requirements taken from the brief: bidirectional real-time audio, low latency, no temporary WAV-file conversation loop,
call-start and call-end events, playback, playback cancellation, caller interruption, clean-up, testability, Docker
compatibility and compatibility with ordinary Android SIP clients. Exactly one primary architecture is to be chosen.

Constraints that shaped the choice: the development machine is Windows with Docker Desktop (WSL2), the stack must be
reproducible from a clean checkout, Asterisk must not become a general-purpose control surface (no PSTN, no open relay),
and every statement about behaviour has to be one we can verify.

## Decision

**AudioSocket is the single media bridge. Call control uses dialplan HTTP callbacks, not ARI.**

* Asterisk 22 LTS (22.12.0), built in Docker from the official source tarball with a pinned SHA-256, runs PJSIP and the
  `AudioSocket()` dialplan application.
* For an accepted call the dialplan asks Sparta over HTTP (`CURL()`, shared-secret authentication) whether to take the call.
  Sparta creates the call through the existing `TelephonyEventSink.incoming_call` and answers with a one-time random UUID.
  The dialplan then runs `Answer()` and `AudioSocket(<uuid>,<sparta-host>:8090)`.
* Asterisk connects to Sparta over TCP. Sparta listens (`telephony/asterisk/`), accepts only an unclaimed, unexpired UUID,
  and attaches the connection to that call. A second connection for a claimed UUID is refused and never replaces the live one.
* ARI, AMI and Asterisk's HTTP server are disabled.

### What travels over the socket (verified in `res_audiosocket.c` and `app_audiosocket.c`, Asterisk 22.12.0)

Every message is `type (1 byte) | payload length (2 bytes, big endian) | payload`.

| Direction | Type | Meaning |
|---|---|---|
| Asterisk → Sparta | `0x01` | the 16-byte UUID, sent once, first |
| Asterisk → Sparta | `0x10` | caller audio, signed 16-bit **little-endian** PCM, mono, **8 kHz** |
| Asterisk → Sparta | `0x03` | one ASCII DTMF digit |
| Sparta → Asterisk | `0x10` | assistant audio, same format; written to the channel immediately |
| Sparta → Asterisk | `0x00` or closing the socket | graceful end: `AudioSocket()` returns 0 and the dialplan continues |

Anything else that Sparta sends (UUID, DTMF, error) is treated by Asterisk as an error and ends the call, and a payload
length of 0 is invalid, so Sparta sends nothing but audio and the hang-up.

### Audio format

* **SIP leg: G.711 only** (`allow=ulaw,alaw`, `disallow=all`). This is what every SIP client supports, it is what the PSTN
  would use later, and it avoids a resampling stage inside Asterisk.
* **Media leg: 16-bit linear PCM, mono, 8 kHz, little-endian**, framed in **20 ms (320-byte) messages**. Asterisk's
  `AudioSocket()` application forces `slin` at 8 kHz, so wideband (G.722/Opus) would be down-sampled by Asterisk anyway.
* Sparta resamples internally where a model needs another rate (16 kHz for Whisper; Piper's 22.05 kHz is brought down to
  8 kHz). Upsampling to 16 kHz adds no information above 4 kHz and the documentation says so.
* RTP's own L16 is big-endian (RFC 3551) while AudioSocket PCM is little-endian. Because AudioSocket is the only path we
  use, the byte-order trap does not arise, and `providers/fake_tone.py` tests prove that a wrong byte order or rate is
  detected rather than silently accepted.

### Playback, pacing and cancellation

Asterisk writes each received audio frame to the channel immediately and does not pace it, so **Sparta paces playback**:
one 20 ms frame every 20 ms on a monotonic clock, with a small lead (40 ms) ahead of real time. Cancelling playback means
no longer sending. Audio already sent (the lead, the RTP hop and the phone's jitter buffer) cannot be recalled, so the
interruption-to-silence time has a floor of roughly 60 to 150 ms. That figure is a design estimate; measured values are in
[PHASE3_ASTERISK_PLAN.md](../PHASE3_ASTERISK_PLAN.md) and the evidence JSON, each labelled with how it was measured. If the
event loop stalls by more than 100 ms the pacer re-anchors its clock instead of sending a catch-up burst (Asterisk resyncs
RTP timestamps above roughly 80 ms of skew, so a long burst would only add jitter). Every message is written with **one**
`write()` call: Asterisk gives a partial payload only 5 ms to complete before it drops the call.

### Security model

* **Media binding.** The UUID is 122 bits from `os.urandom`, single use and short-lived. It maps to exactly one pending
  call record (call id, dialled extension, and the Asterisk channel id reported at call start, kept for correlation) and is
  claimed atomically; the socket itself carries only the UUID, so the UUID is the capability. Only the dialplan that made the
  accepted request learns it. The peer address must be inside `SPARTA_ASTERISK_MEDIA_PEERS`. The first message must arrive within 3 seconds. Payloads above 4 KiB, unknown
  message types, odd-length audio and silence for longer than the idle timeout close the connection. Connection count,
  pending UUID count and per-call buffered audio are bounded.
* **Control plane.** The dialplan callbacks use HTTP Basic authentication with a random secret, compared in constant time,
  and are limited to the Asterisk container's network. The dialplan sanitises (`FILTER()`, `URIENCODE()`) every
  caller-controlled value it forwards; Sparta validates it again.
* **Asterisk.** No anonymous endpoint, `identify_by=username`, `allow_unauthenticated_options=no`, `allow_transfer=no`.
  The only dialplan context is `from-sparta-sip`, which routes exactly **6000** (Sparta): 6001 and 6002 are the two registered
  phones and hang up when dialled, and 6002 is rung only by the take-over step; there is no PSTN, trunk or wildcard outbound
  route. `GROUP()` limits concurrent calls and `TIMEOUT(absolute)` limits call length. SIP and RTP are
  published on loopback by default; a LAN address is an explicit opt-in. Verbose and debug logging are off so that
  dialplan-expanded secrets are never written, and an end-to-end test greps the container output for the generated secrets.
  In the compose file Asterisk is on its own network shared only with the API (not Postgres or Redis), and the container
  refuses secrets that are short or repetitive and allowed networks wider than a /8.
* **What this does not do.** The container has **no limit on failed logins** (it would need `NET_ADMIN`); a fail2ban filter for
  Linux hosts is provided. The network ACL checks the packet's source address, which Docker Desktop rewrites. SIP and RTP are
  cleartext. These are accepted and documented in [SECURITY_REVIEW_PHASE3.md](../SECURITY_REVIEW_PHASE3.md).
* Threats considered in [THREAT_MODEL.md](../THREAT_MODEL.md) and [SECURITY_REVIEW_PHASE3.md](../SECURITY_REVIEW_PHASE3.md).

### Owner takeover

Takeover is by **SIP extension only**. Sparta says a short hand-over line, closes the socket (a graceful return from
`AudioSocket()`), the dialplan asks Sparta for the next step and runs `Dial(PJSIP/6002)`. This is a new local call leg, not
SIP REFER (`allow_transfer=no`). No PSTN or mobile takeover is offered unless a trunk is configured, which this phase does
not do.

## Alternatives evaluated

| Option | Verdict | Reason |
|---|---|---|
| **AudioSocket + dialplan callbacks** | **chosen** | Smallest protocol that gives true two-way streaming; in Asterisk since 18 and in the Ubuntu package as well as a source build; Sparta controls pacing, so cancelling is just stopping; one TCP connection per call is easy to bind, bound and test; no control API to secure. |
| `chan_websocket` (outbound) | rejected for now | Attractive (Asterisk-side pacing, `FLUSH_MEDIA`, `MARK_MEDIA`) but new (22.6+/23) with open reports: over WSS adjacent control frames can be dropped (asterisk#2244), buffered mode can keep a backlog (#2115), and in 22.12.0 `FLUSH_MEDIA` does not clear the paused flag although the documentation says it does. A newer, less exercised code path in a safety-relevant role. Revisit when those are closed. |
| ARI + `externalMedia` (RTP) | rejected | Sparta would own RTP framing, sequence numbers, timestamps, jitter and UDP correlation, and ARI is a full control API to secure. Dynamic payloads such as `slin16` are dropped on receive (asterisk#2268; the fix is not in 22.12.0), so it would be limited to static `ulaw`. |
| Plain RTP to a Sparta port | rejected | Same work as `externalMedia` with no call correlation. |
| EAGI | rejected | Caller audio only (file descriptor 3); no streamed audio back. |
| ARI `Playback`/`Record` into files | rejected | It is the temporary-WAV loop the brief rules out and cannot interrupt at frame granularity. |
| `chan_audiosocket` with `c(slin16)` | not used | Higher-rate message types arrived in 22.7.0; not needed for G.711 callers. A future wideband upgrade could use it. |

## Consequences

* Positive: one small, well-understood, verifiable media path; stop-playback is immediate on Sparta's side; the same
  provider code serves a Docker Asterisk or a native one; no ARI/AMI credentials exist to leak.
* Positive: the end-to-end test uses real SIP and RTP (a mature headless SIP client), real Asterisk and real G.711.
* Negative: no media-plane flush or per-frame acknowledgement, so "playback finished" is "the last frame was sent plus the
  lead", accurate to about 60 ms rather than exact.
* Negative: Sparta cannot send DTMF to the caller or any control message over the socket; transfers and hang-ups work by
  ending the socket and answering the dialplan's follow-up request.
* Negative: Asterisk's `AudioSocket()` gives up after 2 seconds with no channel or socket activity, so a caller who puts the
  call on hold ends it. A partial message that stalls blocks that call's media thread (asterisk#2089); Sparta never sends one.
* Negative: callbacks and media travel unencrypted on the private Docker network. This is acceptable on a single host;
  routed deployments need a VPN or a TLS-terminating proxy. The UUID is protected by single use and the peer allow-list,
  not by secrecy on the wire.
* Negative: Asterisk is built from source (about 5 to 10 minutes the first time, cached afterwards) because Debian has no
  Asterisk package and Ubuntu 24.04 ships 20.6.0. The version and the SHA-256 of the tarball and of the bundled PJPROJECT
  are pinned in the Dockerfile; upgrading means changing two arguments and re-running the end-to-end test.
* Negative: Asterisk is GPLv2. Sparta talks to it over network protocols and does not link or ship it; see
  [TELEPHONY.md](../TELEPHONY.md). This is not legal advice.

## Operating-system and network limitations

* **Linux** is the best case. **Docker Desktop on Windows/macOS** forwards published UDP through a userland proxy, which
  rewrites source addresses: Asterisk is configured for symmetric RTP and `rewrite_contact`, publishes UDP 5060 and a small
  RTP range with identical host and container ports, and needs `SPARTA_ASTERISK_EXTERNAL_IP` set to the host's LAN address
  for a phone on Wi-Fi. A phone on the LAN is **not verified** by Phase 3 automation.
* A phone and the host must be on the same trusted network. NAT between them, client isolation on guest Wi-Fi, firewalls and
  VPN split tunnelling are the usual causes of no audio; [ANDROID_SIP_TESTING.md](../ANDROID_SIP_TESTING.md) lists them.
* Calling Sparta from an ordinary mobile or landline number needs a PSTN carrier and a number. That is a paid, regulated
  service and is **not** delivered by this phase.

## Known limitations

* G.711 narrowband only; speech recognition accuracy at 8 kHz is lower than at 16 kHz.
* One Sparta API process owns the live calls (the same limit as the Twilio adapter); the AudioSocket listener is
  per process.
* Asterisk 22.12.0 is pinned; security releases have to be adopted by changing the pin.
