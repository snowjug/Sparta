# Security review: Phase 3 (local SIP over Asterisk)

An automated, read-only security review by an AI agent (**not a human penetration test**) of what Phase 3 added on branch
`feat/asterisk-open-voice`: the Asterisk provider and its media layer, the dialplan callbacks, the Docker image and its
configuration (`infrastructure/asterisk/`), the compose changes, `scripts/sip_local.py` and `scripts/sip_e2e.py`, the fake
speech guard, and the documents. It did **not** review `doctor/*`, `providers/*/local.py`, `apps/web` or `apps/android`. The
reviewer did not run Docker, a server or any test; it read the code, read upstream Asterisk 22.12.0 sources and advisories
over HTTPS, and hashed the public PJPROJECT tarball in memory. It reported **no critical, no high and no medium finding** and
three low ones, plus a list of hardening notes. All three, and every note that was cheap and clear, were then fixed by the
author and checked by running the code (below). For the design-level view see [THREAT_MODEL.md](THREAT_MODEL.md) (rows 36 to
47); for the architecture choice see [DECISIONS/ADR-ASTERISK-MEDIA-BRIDGE.md](DECISIONS/ADR-ASTERISK-MEDIA-BRIDGE.md).

**What this does not show.** Nothing was tried against a physical phone, the phone network, a hostile LAN or a fuzzer. SIP and
RTP are cleartext by design (no TLS, no SRTP). A clean automated review is not a clean bill of health.

## Findings as reported

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | ⚪ LOW | `docker-compose.yml` | 147-185 | Asterisk shared the default network with Postgres, Redis (dev passwords) and the no-sign-in dev API | 8/10 |
| 2 | ⚪ LOW | `infrastructure/asterisk/Dockerfile` | 40, 57, 60-71, 77, 104 | Sound and music-on-hold tarballs were downloaded at `make install` with no checksum, outside the SHA-256 pins | 8/10 |
| 3 | ⚪ LOW | `pjsip.conf.template`, `entrypoint.sh`, `docker-compose.yml`, `ANDROID_SIP_TESTING.md` | 14-18, 26-30; 30-35, 73-77; 166-169; 40-41 | No failed-auth throttle, the network ACL is not effective behind Docker's address translation, weak operator secrets were accepted | 7/10 |

## What was found and what changed

1. **Network reach of Asterisk (low).** Asterisk is the one new component that parses unauthenticated SIP and RTP from a LAN, and
   it sat on the default compose network next to Postgres, Redis and the API (which runs the development identity in the dev
   stack). A pre-auth bug in Asterisk or PJSIP would have given an attacker those hosts.
   *Fixed:* Asterisk is now on a dedicated `sip` network that only it and the API join; it cannot reach Postgres, Redis or the
   web app (`docker-compose.yml`). *Not fixed, and said so:* the API itself is still reachable from Asterisk, because the
   callbacks need it, and in the development stack the API has no sign-in. A "provider-only host name" for Asterisk was
   considered and **rejected**: a compromised Asterisk can send any `Host` header, so it would be no boundary. Use
   `SPARTA_AUTH_MODE=oidc` for anything but a trusted local machine.
2. **Unchecked downloads in the image build (low).** The comment said pre-seeding the externals cache meant the build needed no
   further download. `make install` also fetches the core-sound and music-on-hold packages, with no checksum, and the image
   contained 582 such files (3.8 MB of sounds and 17 MB of music, found by listing the image). The dialplan never plays a recorded
   sound.
   *Fixed:* `menuselect` disables the sound, extra-sound and music-on-hold categories; the build **fails** if any file is left in
   `/var/lib/asterisk/sounds` or `/moh`; the comment is corrected. Rebuilt image: 0 such files, 377 MB instead of 456 MB.
3. **Failed logins, the ACL and weak secrets (low).**
   * *Throttle.* There is still **no limit on failed logins inside the container**: it would need `NET_ADMIN`, which the
     container deliberately does not get. Added instead: documentation of exactly that, a fail2ban filter for Linux hosts
     (`infrastructure/asterisk/fail2ban/`) whose regular expression the end-to-end test applies to Asterisk's real log output
     (this caught that Asterisk colours every field of its log lines, which would have made the filter silently match nothing;
     the image now runs `asterisk -n`), and a sample jail that is **not tested**.
   * *The ACL and Docker.* The check uses the packet's source address, and Docker Desktop rewrites it (observed: a request from
     the host arrived as `172.17.0.1`). The documents now say the ACL is effective only where the source address survives (Linux
     with default networking) and that on Docker Desktop the firewall and the passwords are the controls.
   * *Weak secrets.* The entrypoint now refuses a secret shorter than 24 characters or with fewer than 8 different ones, two equal
     SIP passwords, and any allowed network wider than a `/8` or with an invalid octet (a bad range now stops the container: it used
     to be skipped silently inside a process substitution).
   *Tests:* `tests/e2e_sip` `test_the_container_refuses_weak_secrets_and_a_network_that_is_too_wide` (9 cases),
   `test_the_container_starts_with_good_secrets_and_a_private_network`, and the fail2ban assertion in
   `test_a_sip_client_registers_with_its_password_and_only_with_it`.

### Hardening notes from the review, and what was done

| Note | Done |
| --- | --- |
| The peer check on callbacks means nothing behind a proxy that the server trusts for `X-Forwarded-For` | A callback carrying `X-Forwarded-For`, `Forwarded` or `X-Real-IP` is refused (`api/routers/webhooks.py`; test `test_a_callback_that_came_through_a_proxy_is_refused_even_with_the_right_secret`) |
| `SPARTA_ASTERISK_MEDIA_PEERS` rejected only `/0` | Nothing wider than a `/8` (IPv4) or `/7` (IPv6) is accepted (`config.py`; `test_a_media_peer_may_not_be_nearly_the_whole_internet`, 12 cases) |
| The entrypoint accepted `0.0.0.0/0` as an allowed network | Refused, as above |
| `sip_local.py` created the secrets file with default permissions and then restricted it | Created owner-only from the first byte (`os.open` with mode `0o600`) |
| `sip_local.py show` printed the SIP passwords by default | Hidden unless `--reveal` is given |
| `incoming_call` passed a carrier's caller name for every provider, so a spoofable name now appeared in the owner's UI | The name is used only for a caller with no number (a SIP extension); the Azure incoming-call test asserts it is not shown beside a number |
| The harness docstring said secrets are "never written to disk" | Corrected: the caller's SIP password is in the run's scenario file in a temp directory that is deleted |
| SIP and RTP are cleartext | Accepted and documented (see below) |
| `docs/SECURITY_REVIEW_PHASE3.md` was linked but missing | This document |

## What was found while testing, not by the review

Both were found by the real-SIP end-to-end run and are product fixes, not hardening:

* **The first call after a restart was rejected.** Sparta's first `/incoming` webhook took 6.7 s (the owner's name-specific
  matchers were built inside it), longer than the dialplan waits, so Asterisk answered the caller with a rejection. The server now
  builds them at start-up (`Container.warm_up`); the first webhook takes about 0.1 s.
* **The real log output defeated the fail2ban filter** (colour codes), as above.

## The threat list, answered

The Phase 3 brief asked for these threats to be checked. "Evidence" is something that was run, not something that was read.

| Threat | Control | Evidence | Residual |
| --- | --- | --- | --- |
| Anonymous SIP registration | No anonymous endpoint; digest auth; identification by user name only | End-to-end: right password registers; wrong password and an unknown user do not; an unauthenticated INVITE and OPTIONS get nothing but a challenge | None found |
| Weak or default passwords | Random 32-character passwords from `secrets`; the container refuses short or repetitive ones | End-to-end: 9 refusal cases and one pass against the real image | A hand-typed 24-character password with 8 different characters is accepted |
| SIP brute force | Random passwords; private-network ACL; loopback-only publishing by default; fail2ban recipe | The filter matched real failed-login lines | **No throttle in the container.** The ACL is not effective behind Docker Desktop |
| Open relay; unrestricted outbound calls; international and premium numbers | The only routable number is 6000; no trunk, no pattern, no outbound registration module; the one `Dial()` is the literal `PJSIP/6002` | End-to-end: six numbers (a national number, an international number, `112`, `6001`, `6002`, `9`) were refused; the dialplan has exactly one `Dial` | None found. **PSTN is not delivered** |
| ARI, AMI, HTTP, shell exposure | Not built, not loaded (allow-list), disabled in their own configuration | End-to-end: module list, `manager show settings`, `http show status` | The allow-list is trusted as reviewed |
| Media-socket spoofing; channel hijacking; a second stream; replay | Peer allow-list; single-use random id claimed atomically; first message within 3 s; id dies with the call or after 10 s | In-process integration tests; end-to-end: a host that is not Asterisk could not open a connection | Anyone allowed as a peer who also knows a live id |
| RTP injection | `strictrtp`; fixed port range | Configuration checked; **not attacked** | Cleartext RTP; a LAN host can listen or inject during the learning window |
| Malformed and oversized audio | Length-prefixed framing, 4 KiB payload cap, whole samples only, protocol errors end the session | Unit and integration tests, including random garbage | Not fuzzed beyond that |
| Resource exhaustion; infinite calls; simultaneous calls | Asterisk-enforced call limit and absolute duration; Sparta's own caps; bounded queues and connection counts | End-to-end: a call over the limit was ended by Asterisk at 29.9 s of a 30 s limit | A registered phone can hold the lines |
| Log leaks; secrets in container output | Verbose and debug off; the secret is only read at run time | End-to-end: the container output was searched for all three generated secrets after a full session of calls | Log lines contain IP addresses and extension numbers |
| Docker network exposure | Own `sip` network; media port not published; loopback publishing by default | `docker compose --profile asterisk config`: Asterisk is on `sip` only, the API on `default` and `sip`, Postgres, Redis and the web app on `default` only; every published port is on 127.0.0.1 unless a LAN address is set | The API is reachable from Asterisk (dev identity) |
| Prompt injection by voice | Unchanged deterministic engine; matrix of 10 injection phrases through the real stack | 9 of 10 refused and ended; the Hindi-script "ignore all previous instructions" was not flagged and nothing was obeyed ([PHASE3_ASTERISK_PLAN.md](PHASE3_ASTERISK_PLAN.md)) | Detection gaps are recorded, not hidden |

## Accepted risks

* SIP and RTP are cleartext: use a network you trust. Encrypted media (TLS and SRTP) is future work.
* No failed-login throttle in the container (documented, with a recipe).
* The network ACL cannot see real source addresses on Docker Desktop.
* In the development stack the API has no sign-in and Asterisk can reach it.
* The Debian base image is pinned by tag, not by digest.
* Piper (GPL-3.0) and its Hindi and Kannada voices (non-commercial) carry licence conditions: [MULTILINGUAL_SPEECH.md](MULTILINGUAL_SPEECH.md).

## Checked by the reviewer and found not to be a problem

Anonymous identification and user enumeration (unidentified requests get an artificial-endpoint challenge); the Basic-auth
callback check (constant time, secret checked before the body is read, generic rejections); `CURL()` and `FILTER()` handling of
the caller id; the media id's randomness and atomic claim; `entrypoint.sh` expansion and quoting; the Asterisk and PJPROJECT
checksum pins (the reviewer re-derived the PJPROJECT hash); that the fake speech guard cannot be switched on in production; that
takeover can only ring the owner extension; that `X-Forwarded-*` cannot spoof the peer in the shipped stack (proxy headers are off).

## Could not be assessed

Docker Desktop's real UDP behaviour (later observed: the source address is rewritten); runtime Asterisk behaviour that was read
from source rather than run (since then exercised by the end-to-end test, which found the log-colour and first-call problems);
fuzzing of PJSIP and RTP parsing; three May-2026 pjproject advisories that were not opened individually (the Asterisk release
used, 22.12.0, is the newest 22.x at the time of writing); physical-phone behaviour.

**Image scanning.** Trivy 0.76.2 with CI's flags (`--severity HIGH,CRITICAL --ignore-unfixed`) found nothing in the locally built
API image (Debian 13.7, 87 packages, plus its Python packages) or the Asterisk image (Debian 12.15, 120 packages). It reads package
databases, so it **cannot see Asterisk and PJPROJECT, which are compiled from pinned source tarballs**: their security rests on
the pinned versions and the advisory reading above, not on that scan. CI scans the API image only, so the Asterisk image is not
scanned automatically.
