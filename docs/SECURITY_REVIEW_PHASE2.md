# Security review: Phase 2 (the real-call path)

An automated, read-only security review by an AI agent (**not a human penetration test**) of everything Phase 2 added on
branch `feat/real-world-telephony`: `git diff f419af2..db66c1c -- services/api/src infrastructure .github`. That is the
Twilio adapter and its G.711 codec, the provider routes, the calling-application pin for Event Grid tokens, provider-only
hosts, the cost caps and the provider-failure policy, `sparta doctor`, the Speech SDK adapter, the Bicep and `deploy.yml`
changes and the configuration. The reviewer ran the real middleware, the whole app and a real uvicorn WebSocket in-process,
fuzzed the media session (30,000 random sessions that never sent a valid `start`) and tried 18 claim shapes against the
application pin. It reported **no critical and no high finding**: nothing cleared its reporting bar (high at confidence 7
or more, medium at 8, low at 9), so it filed none and tabled the four closest calls. Each was reproduced before it was
fixed or accepted. For the design-level view see [`THREAT_MODEL.md`](THREAT_MODEL.md) (rows 29 to 35); the two reviews of
Phase 1 are in [`SECURITY_REVIEW.md`](SECURITY_REVIEW.md).

**Nothing here was tried against a live Twilio, Azure or Entra account.** Every statement about how those services behave
is documentation, not observation (see [`TELEPHONY.md`](TELEPHONY.md) and
[`research/phase2-provider-verification.md`](research/phase2-provider-verification.md)).

## Findings as reported

| # | Severity | File | Lines | Vulnerability | Confidence |
|---|----------|------|-------|---------------|------------|
| 1 | 🟡 MEDIUM (conditional) | `api/middleware.py` (and `config.py`, `api/main.py`) | 172-178 | Provider-only host guard fails open on any `Host` that is not the exact listed string | 7/10 |
| 2 | ⚪ LOW | `telephony/twilio.py`, `config.py` | 643-647, 947-950; 162-166 | A stranger can evict a live Twilio media stream, but only when `SPARTA_TWILIO_VERIFY_MEDIA_SIGNATURE=false` | 5/10 |
| 3 | ⚪ LOW | `telephony/webhooks.py`, `config.py` | 377-385, 433-452; 143-148 | The Event Grid caller pin is correct but off unless configured | 5/10 |
| 4 | ⚪ LOW | `services/calls.py` | 235-262 | The per-number throttle and the caps can be evaded (spoofed `From`, check-then-act) | 4/10 |

Line numbers are those of `db66c1c`, the commit that was reviewed.

## What was found and what changed

1. **Provider-only host guard (medium, conditional).** With the default `SPARTA_TRUSTED_HOSTS=*` Starlette's trusted-host
   middleware does nothing, so the guard is the only gate, and it matched only the exact `host[:port]` string.
   `Host: <tunnel>.`, `Host: <tunnel>:1:2`, `Host: <tunnel>::` and another name for the same tunnel all reached the whole
   owner API (`GET /api/v1/me` answered 200 as the development identity) while the exact host, an upper-case host and a
   host with another port were refused. It needs a tunnel that forwards such a `Host` header verbatim, hence the
   conditional rating. With `SPARTA_TRUSTED_HOSTS=<tunnel>,localhost`, which [`DEPLOYMENT.md`](DEPLOYMENT.md) already said,
   the variants were refused with 400.
   *Fixed:* `canonical_host()` compares host **names** (lower case, no port, no trailing dot); a missing or malformed `Host`
   is treated like a listed one, so the guard fails closed; a configured entry that is not a host name stops the server
   instead of silently guarding nothing; `Settings.problems()` refuses `SPARTA_PROVIDER_ONLY_HOSTS` together with a wildcard
   `SPARTA_TRUSTED_HOSTS` (so every other `Host` is answered 400 by trusted hosts) and entries that are not bare host
   names; `sparta doctor` reports the combination as BLOCKED; [`TELEPHONY.md`](TELEPHONY.md),
   [`DEPLOYMENT.md`](DEPLOYMENT.md) and `.env.example` now say that both settings are required.
   *Tests:* `tests/api/test_api_provider_hosts.py` (`test_the_listed_host_is_matched_as_a_name_however_it_is_written`,
   `test_a_missing_or_malformed_host_is_treated_like_a_listed_one`,
   `test_a_configured_host_that_is_not_a_host_name_is_refused_instead_of_silently_guarding_nothing`,
   `test_the_real_app_hides_the_owner_api_on_the_tunnel_host_but_not_locally`,
   `test_the_server_refuses_to_start_when_provider_only_hosts_are_not_backed_by_explicit_trusted_hosts`),
   `test_config_logging.py::test_provider_only_hosts_need_explicit_trusted_hosts_and_bare_host_names`,
   `test_doctor.py::test_provider_only_hosts_without_explicit_trusted_hosts_are_blocked_because_the_server_would_not_start`.
2. **Media socket eviction (low).** `attach_media` cancelled and closed the live session *before* the newcomer had
   authenticated. With the upgrade signature check on (the default) a stranger is refused with 403 before the socket is
   accepted. With `SPARTA_TWILIO_VERIFY_MEDIA_SIGNATURE=false`, a client that knew only the call id (`call_` plus 48 random
   bits) closed Twilio's stream over a real uvicorn socket, and with it the call. It could not inject audio: it still
   fails the per-call token check.
   *Fixed:* a socket is only **pending** until its `start` message proves the token; it becomes the call's live stream
   inside that handler (a reconnect from Twilio still replaces the old one) and not one step earlier; a pending socket that
   sends no valid `start` within 10 s (`START_TIMEOUT_S`) is cancelled; one that authenticates after its call ended is
   dropped; `SPARTA_TWILIO_VERIFY_MEDIA_SIGNATURE=false` is refused when `SPARTA_ENV=production`.
   *Tests:* `test_twilio.py::test_a_socket_that_cannot_prove_the_token_never_displaces_the_live_stream`,
   `test_a_socket_that_never_sends_start_is_closed_and_displaces_nothing`,
   `test_a_socket_that_authenticates_after_the_call_ended_is_dropped_not_attached`,
   `test_config_logging.py::test_the_twilio_media_signature_check_cannot_be_switched_off_in_production`.
3. **Event Grid caller pin (low).** The pin cannot be bypassed when it is configured: 18 claim shapes (case, both claims,
   null, empty, list, dict, integer, whitespace, only `oid` or `sub`) were handled correctly, and when both `azp` and
   `appid` are present both must be allowed. But it is optional: with no application id configured the check is skipped,
   the Bicep default is empty, and an insider holding the Event Grid role (which the subscription-writer app also holds)
   could forge `IncomingCall` events.
   *Fixed:* with `SPARTA_ENV=production` and `TELEPHONY_PROVIDER=azure` the server refuses to start without
   `SPARTA_EVENT_GRID_ALLOWED_APP_IDS` (a list of application-id GUIDs, validated when the verifier is built); the doctor
   still only warns outside production.
   *Test:* `test_config_logging.py::test_production_azure_telephony_needs_the_event_grid_caller_pinned_but_development_does_not`.
4. **Caps (low, accepted).** The per-number throttle is keyed on the `From` number, so a caller who spoofs numbers rotates
   past it; the caps are checked once, when a call starts, so concurrent voice webhooks can each pass before any of them
   is counted; a `From` that is not E.164 (anonymous, a client identity) has no number to throttle. *Not changed*:
   Sparta cannot tell a spoofed caller id from a real one. The daily call-count and minute caps are per owner and still
   bound the spend, and the reviewer found no cross-owner path: every cap query is scoped by `user_id`, and real calls go
   only to the configured owner. Recorded in [`THREAT_MODEL.md`](THREAT_MODEL.md) row 31.

### Smaller items from the review's notes, also fixed

| Item | What was wrong | Resolution and test |
| --- | --- | --- |
| Non-ASCII credentials | `hmac.compare_digest` on `str` raises `TypeError` for non-ASCII input. A non-ASCII `X-Twilio-Signature` ended as a generic 500 (log noise, no bypass). A non-ASCII or lone-surrogate stream token in a `start` message raised inside the handler and was counted as a handler error instead of an authentication failure, so that socket was not closed. | Both comparisons use `_same_secret`: constant-time on UTF-8 bytes (`surrogatepass`). `test_twilio.py::test_verification_accepts_only_the_right_token_url_fields_and_header` and the non-ASCII tokens in `test_a_socket_that_cannot_prove_the_token_never_displaces_the_live_stream` |
| Formatted takeover number | The API accepts `+91 98123 45670` (spaces, dashes, parentheses) but the provider dials strict E.164, so the transfer failed *after* the call had entered the take-over state. | `services/numbers.py` `dial_number()`: separators dropped, `00` read as `+`, a number **without a country code is not usable** (never completed with a guessed country, because a call is bridged to it). It decides whether Take Over is offered, whether the tap is accepted (before anything changes) and what is dialled. `tests/unit/test_numbers.py`, `test_api_twilio.py::test_a_takeover_number_is_dialled_as_strict_e164_and_never_completed_with_a_guessed_country` |
| Doctor output from a remote host | `sparta doctor --online` printed the `/readyz` text of the target as it was. A hostile host could put terminal escape sequences or a very long text there. | The text is reduced to plain printable ASCII, 40 characters per field and 12 entries, and every check text has control characters replaced (`Check.safe()`). `test_doctor.py::test_what_a_remote_readyz_says_is_shown_as_short_plain_text_and_cannot_drive_the_terminal`, `test_no_check_text_can_carry_control_characters_into_a_terminal` |

### Secret scanning

`gitleaks` 8.30.1 over the 69 commits of this branch (`gitleaks git`, `.gitleaks.toml`) found two matches of its
`generic-api-key` rule, both in `services/api/tests/unit/test_doctor.py`: the fake Speech key and the fake Twilio token
that the leak tests assert are never printed. Neither is a credential. They are allowlisted by exact value in
`.gitleaks.toml`, as that file requires for any fixture that looks like a key; a second scan found no leak. A scan of the
working tree reports matches only inside git-ignored folders (`.venv`, `.next`).

## What is still open

- **`Host: localhost` through a tunnel.** After the fix every `Host` that is not listed in `SPARTA_TRUSTED_HOSTS` is
  refused, and a listed provider-only host serves nothing but provider routes. The same server still serves the owner API
  to `localhost` (that is the purpose), so a tunnel that routes by something other than the `Host` header and forwards a
  client-supplied `Host: localhost` unchanged would expose it. Which tunnels behave that way is **UNVERIFIED**; no tunnel
  was tested with this API. Keep a tunnel session short and supervised, never expose the development identity otherwise,
  and prefer a tunnel that routes by host name.
- **The media-upgrade signature URL form is UNVERIFIED** (every plausible form is accepted). If Twilio signs a form the
  adapter does not accept, genuine upgrades are refused with 403; the switch that disables the check exists only outside
  production, so reproduce it on a development tunnel and extend the accepted forms in code. With the check off the
  per-call token still authenticates the socket, a stranger can no longer displace the live stream, and an unauthenticated
  socket is closed after 10 s.
- **Replay of a valid signed Twilio request** is rejected by nothing but per-`CallSid` idempotency (Twilio's scheme has no
  timestamp), so a replay returns the same TwiML and creates no second call.
- **Cap evasion** (finding 4) and the fixed-window, per-owner nature of the caps.
- **What the Event Grid pin protects** is only as good as the application id the operator enters; whether live tokens carry
  `azp` or `appid`, and the exact ACS audience and algorithm name, are **UNVERIFIED** until a real token is inspected.
- **A refused transfer** leaves the call in the take-over state until the owner ends it or a limit does; Sparta never
  learns whether the owner's phone rang.
- **`sparta doctor --callback-url`** is operator input: the doctor makes its unauthenticated probes against whatever https
  host the operator names.
- **Not a human penetration test**: the reviewer did not review the web and Android apps, did not fuzz the Speech SDK
  path, and tried nothing against live providers.

## Areas reviewed with no finding

- **Twilio signatures:** HMAC-SHA1 over the configured https origin and path, never over `Host` or `X-Forwarded-*`;
  constant-time comparison; a 128-character cap on the header; accepted URL forms `{https, https:443}` for webhooks and
  `{wss, https} x {no port, :443}` for the upgrade; no signing oracle (`twilio_signature` is called only from the verify
  path). Forged requests (none, blank, junk, wrong token, wrong path, `http://` URL, tampered or extra field, invalid UTF-8)
  all got 400 or 401 and created nothing.
- **Media session:** 30,000 random sessions that never sent a valid `start`: none authenticated and none reached the sink.
  A `start` with the wrong call SID, a wrong, upper-cased, list-valued or space-padded token closes the socket. Messages are
  capped at 64 KiB and payloads at 16 KiB; base64 is strict; only the `inbound` track is accepted; mark names match
  `[A-Za-z0-9_-]{1,64}` and only set events registered for that call; DTMF is whitelisted and ignored; 500 invalid frames
  close the socket.
- **REST client:** basic authentication goes only to the hard-coded `https://api.twilio.com`; redirects are not followed;
  both SIDs are regular-expression checked; errors are static text.
- **TwiML:** hostile call ids, tokens, numbers and caller ids, parsed with ElementTree, stay text or attribute values and
  never add an element. The takeover destination and the caller id are checked against E.164 before TwiML is built.
- **State and replay:** idempotency is one shielded task per `CallSid` plus the `provider_events` table; `_incoming`,
  `_pending` and `_ended` are capped at 1024 and per-call dictionaries are popped in `finally`; the call SID comes from the
  server-side pending record.
- **Routes in `api/routers/webhooks.py`:** the signature is checked before anything is acted on (only the bounded form
  parse, 100 fields and about 1.1 MB, comes first); rejections are generic envelopes with the reason only in the log;
  unsigned requests create no call, spend no budget and cannot end or reach any call; the upgrade is refused with 403
  before `accept()`; an over-limit call gets `<Reject busy>`, which Twilio does not bill.
- **Provider-only hosts, the path side** (the claim of [`THREAT_MODEL.md`](THREAT_MODEL.md) row 33): raw ASGI scopes for
  `/api/v1/webhooks/../me`, `%2e%2e`, `//api/v1/me`, `;`, trailing slashes, upper-case paths and non-provider WebSocket
  paths all returned 404 or closed with 1008; the path is matched as the server delivers it and dot segments are not
  collapsed, so such a path passes the prefix check and then matches no route. This is now a regression test
  (`test_api_provider_hosts.py::test_a_path_that_only_looks_like_a_provider_path_never_reaches_an_owner_route`). Matching is
  on `Host` only; uvicorn does not rewrite it from `X-Forwarded-Host`.
- **`services/calls.py` and `db/repository.py`:** every query is scoped by `user_id`, counts real calls only and uses the
  server-set `started_at`; `duration_ms` is written on every finalise path; the provider-failure policy acts only on the
  failing call and resets on success; `_abandon_playback` re-checks the playback id under the call lock; `owner_action`
  uses the principal's own preferences.
- **Doctor:** Twilio credentials go only to `https://api.twilio.com`, as a per-request header, with no redirects; the SID
  is regular-expression checked; bodies are capped at 1 MB; no URL is built from remote data and the voice URL's host is
  compared but never echoed; every line goes through `redact_text`.
- **`providers/stt/azure_sdk.py`:** the key comes from settings only, the endpoint is `https_origin` or a region matching
  `[a-z0-9]{2,32}`, SDK error text is never forwarded, callbacks are marshalled with `call_soon_threadsafe` and blocking SDK
  calls run in `to_thread`.
- **Bicep and `deploy.yml`:** the `@secure()` Twilio token is stored as a Key Vault secret and read through a `secretRef`
  with a per-secret "Key Vault Secrets User" assignment; it appears in no output and in no plain environment value, and the
  web app has no identity; the workflow passes it as an environment variable to one step and never writes, echoes or traces
  it. The migration job receives the same secrets as the API, as for the existing ones. Nothing was deployed, so none of this
  is verified against Azure.
- **`config.py`:** a missing SID, token or base URL is a problem; an empty token becomes `None`, so nobody can sign with an
  empty key; the caps have `ge=0`; production forbids `*` trusted hosts and the development identity.

## Reproducing the checks

```
cd services/api
python -m pytest tests/api/test_api_provider_hosts.py tests/api/test_api_twilio.py tests/unit/telephony/test_twilio.py \
    tests/unit/telephony/test_webhooks.py tests/unit/test_config_logging.py tests/unit/test_doctor.py tests/unit/test_numbers.py
python -m bandit -c pyproject.toml -r src
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip      # needs network access
gitleaks git . --config .gitleaks.toml --redact                            # from the repository root
```
