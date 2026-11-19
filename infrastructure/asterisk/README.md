# Sparta local-SIP Asterisk

A small, locked-down [Asterisk](https://www.asterisk.org/) 22 LTS image so that a **SIP phone on your own network** can call
Sparta and talk to it in both directions, with **no Twilio account, no phone number and no paid service**.

> **This is not a phone-network (PSTN) connection.** A friend who dials your mobile or landline number cannot reach Sparta this
> way. That needs a carrier, a phone number (DID) and a SIP trunk, which cost money, are not part of this image and are not
> delivered. There is deliberately no trunk and no outbound route in this configuration.

How it fits together:

```
SIP phone (Linphone, baresip ...) --SIP/RTP, G.711--> Asterisk --AudioSocket (TCP, 8 kHz PCM)--> Sparta API
                                                          \--HTTP callbacks (dialplan CURL, basic auth)--> Sparta API
```

Sparta is the telephony provider `asterisk` (`SPARTA_TELEPHONY_PROVIDER=asterisk`): it listens for Asterisk's media
connection, runs the same voice-activity detection, recognition, deterministic safety engine and speech synthesis as for any
other provider, and streams the reply back. The reasons for this design (AudioSocket rather than ARI or `chan_websocket`) are
in [docs/DECISIONS/ADR-ASTERISK-MEDIA-BRIDGE.md](../../docs/DECISIONS/ADR-ASTERISK-MEDIA-BRIDGE.md).

## Run it

```bash
python scripts/sip_local.py init                 # random secrets -> .env and .env.sip (both git-ignored); prints nothing secret
docker compose --profile asterisk up --build     # first build compiles Asterisk: about 5-15 minutes, cached afterwards
python scripts/sip_local.py show --reveal        # server address, extension numbers and the SIP passwords for your phone
python -m sparta doctor --provider asterisk --env-file ../../.env       # preflight; run from services/api (init wrote .env in the repository root)
```

Register a SIP client as extension **6001** (password from `show --reveal`), then dial **6000**. The step-by-step phone setup
is in [docs/ANDROID_SIP_TESTING.md](../../docs/ANDROID_SIP_TESTING.md).

| Extension | Purpose |
| --- | --- |
| 6000 | Sparta, the AI call assistant. You *dial* it; it is not an account. The only number anything can dial. |
| 6001 | The test caller: register your phone as this. |
| 6002 | The owner's phone: rung only when the owner presses **Take over** in the Sparta app. |

## What is in this directory

| File | What it does |
| --- | --- |
| `Dockerfile` | Builds Asterisk 22.12.0 from the official source tarball, **SHA-256 pinned** (and the bundled PJPROJECT 2.17, also pinned), with the modules that could run a shell command or open a control API not even built, and no sound or music-on-hold downloads (the build fails if any end up in the image). Runtime image: unprivileged user, no capabilities. |
| `entrypoint.sh` | Validates the secrets it is given (at least 24 characters, at least 8 different), renders `pjsip.conf` from the template, then runs Asterisk. Never prints a secret. |
| `pjsip.conf.template` | Two endpoints (6001, 6002), digest authentication, G.711 only, no anonymous access, no trunk, an RTP timeout, a private-network ACL. |
| `extensions.conf` | The dialplan: only 6000 is routable; everything else hangs up. Limits calls (`GROUP()`) and their length (`TIMEOUT(absolute)`), asks Sparta over HTTP whether to take the call, and hands the media to `AudioSocket()`. |
| `rtp.conf` | A fixed RTP port range (UDP 10000-10019), strict RTP (a third party cannot inject audio into a live call), no STUN/TURN/ICE. |
| `modules.conf`, `asterisk.conf`, `logger.conf`, `http.conf`, `manager.conf` | A module allow-list (autoload off), ARI/AMI/HTTP disabled, verbose and debug logging off so the dialplan never writes the callback secret. |
| `healthcheck.sh` | Healthy when Asterisk is fully booted, both endpoints exist and the media module is loaded. |
| `fail2ban/` | A filter (tested against real output) and a sample jail (not tested) for banning hosts that fail to log in. See below. |
| `e2e/` | The Docker stack and the headless `baresip` caller used by `python scripts/sip_e2e.py`. Test-only. |

## Settings

Set in `.env` (written by `sip_local.py init`) or the environment; the compose file passes them through.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SPARTA_ASTERISK_WEBHOOK_SECRET` | generated | The secret the dialplan sends (HTTP Basic) with every callback. At least 24 characters. |
| `SIP_PASSWORD_6001`, `SIP_PASSWORD_6002` | generated (`.env.sip`) | The phones' digest passwords. Only Asterisk sees them: the API container does not. |
| `SPARTA_ASTERISK_BIND` | `127.0.0.1` | The host address SIP and RTP are published on. Use this computer's **one** LAN address for a phone; never `0.0.0.0`. |
| `SPARTA_ASTERISK_EXTERNAL_IP` | empty | The address Asterisk tells the phone to send audio to. Set it to the same LAN address. |
| `SPARTA_ASTERISK_SIP_PORT` | `5060` | UDP. The RTP range is fixed at 10000-10019 (keep `rtp.conf`, the compose ports and `EXPOSE` in step). |
| `SPARTA_ASTERISK_MAX_CALLS` | `2` | Simultaneous calls (1-8), enforced by the dialplan whatever Sparta says. |
| `SPARTA_ASTERISK_MAX_CALL_SECONDS` | `600` | Longest call (30-3600 s), enforced by Asterisk itself. |
| `SPARTA_ASTERISK_ALLOWED_NETS` | RFC 1918 + loopback | Who may talk SIP to Asterisk before authenticating. IPv4 ranges from `/8` to `/32` only. |

## Security posture, and what it does not do

Written as threats and answers in [docs/THREAT_MODEL.md](../../docs/THREAT_MODEL.md) and
[docs/SECURITY_REVIEW_PHASE3.md](../../docs/SECURITY_REVIEW_PHASE3.md) (an automated review, not a penetration test).

* **No PSTN, no trunk, no outbound route, no international or premium numbers.** The dialplan has no pattern that dials out;
  the one `Dial()` is a literal (`PJSIP/6002`), reachable only when Sparta says so over its authenticated callback.
* **Every phone must authenticate** (digest, random 32-character passwords). There is no anonymous endpoint, and unknown users
  get the same challenge as known ones.
* **Callbacks are authenticated and source-checked.** The dialplan's HTTP callbacks carry the secret, and Sparta also checks
  that they come from Asterisk's address; the media socket is open only to Asterisk, accepts a single-use random id once and
  refuses a second stream.
* **Network.** The compose file puts Asterisk on its **own network shared only with the API**, not with Postgres, Redis or the
  web app. The media port (8090) is never published.
* **Least privilege.** Unprivileged user (uid 10001), read-only root file system, all capabilities dropped,
  `no-new-privileges`, no shell modules, no AMI/ARI/HTTP.
* **Cleartext.** SIP and RTP are not encrypted (no TLS, no SRTP). That is acceptable on a network you trust and not on one you do
  not; encrypted media is future work. The callback secret travels over plain HTTP inside the compose network.

**What it does not do:**

* **Failed logins.** There is **no limit on failed logins** inside the container (a throttle needs `NET_ADMIN`, which the
  container does not get). What protects you is random 32-character passwords, the private-network ACL and loopback-only
  publishing by default. If you expose the SIP port to a network you do not fully control, add a firewall rule that allows only
  your phone's address, or on a **Linux** host run fail2ban with the files in `fail2ban/` (the filter is tested against real
  Asterisk output; the jail is a sample that has not been run).
* **The network ACL and Docker Desktop.** The ACL checks the packet's source address. Docker Desktop (Windows, macOS) rewrites
  the source address of published UDP, so there it cannot tell a LAN phone from any other sender; the firewall and the passwords
  do the work. With Docker's default networking on Linux the source address survives and the ACL is effective.
* **Hardening is not certification.** Nothing here has been penetration-tested.

## Health, doctor and tests

```bash
docker compose --profile asterisk ps                                     # asterisk should be "healthy"
docker compose exec asterisk asterisk -rx "pjsip show contacts"          # your phone, once registered
python -m sparta doctor --provider asterisk --env-file ../../.env [--online]   # from services/api; never prints a secret
python scripts/sip_e2e.py                                                # the real-SIP end-to-end test (Docker, no account)
```

`scripts/sip_e2e.py` starts this image and the Sparta API, and drives them with **baresip**, a separate open-source SIP
client, over real SIP and RTP with real G.711. It is the evidence for "a real external SIP client completed a call", with the
labelled limits written in [docs/PHASE3_ASTERISK_PLAN.md](../../docs/PHASE3_ASTERISK_PLAN.md).

## Licence and upgrading

Asterisk is **GPL-2.0**. Sparta does not link it and talks to it only over network protocols (SIP, AudioSocket, HTTP). The
image is built from the exact tarball named in the `Dockerfile` (`/usr/share/doc/sparta-asterisk/SOURCE` inside the image says
which), so the corresponding source is the upstream release. To upgrade, change `ASTERISK_VERSION` and `ASTERISK_SHA256` (the
published checksum is at `downloads.asterisk.org/pub/telephony/asterisk/asterisk-<version>.sha256`) and, if the release bundles
another PJPROJECT (`third-party/versions.mak`), `PJPROJECT_VERSION` and `PJPROJECT_SHA256`; then run `python scripts/sip_e2e.py`.
