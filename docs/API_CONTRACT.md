# Sparta API contract (v1)

Source of truth for clients while the backend is built. The machine-readable contract is generated from the FastAPI app
into `packages/contracts/openapi.json` (CI fails on drift). Where this document and `openapi.json` disagree, **openapi.json
wins**; please report the mismatch. DTO field names equal the Python attribute names in
`services/api/src/sparta/domain/models.py`; enum values equal the string values in `services/api/src/sparta/domain/enums.py`.

## Conventions

| Topic | Rule |
| --- | --- |
| Base path | `/api/v1` (health probes live at `/healthz` and `/readyz`) |
| Format | JSON, UTF-8, timestamps ISO-8601 UTC (`2026-11-17T10:00:00Z`) |
| Auth (dev) | No credentials. `GET /system/status` returns `dev_banner: true`; every UI **must** show a "Development identity" banner. Optional header `X-Sparta-Dev-User: <id>` selects another dev identity (isolation testing) |
| Auth (prod) | `Authorization: Bearer <OIDC access token>` (Microsoft Entra External ID or any OIDC issuer). Dev auth is impossible when `SPARTA_ENV=production` |
| Errors | `{"error": {"code": str, "message": str, "trace_id": str, "details": [{"field": str, "message": str}] \| null}}` |
| Error codes | `validation_error` 422 · `unauthorized` 401 · `forbidden` 403 · `not_found` 404 · `conflict` 409 · `unsupported_by_provider` 409 · `payload_too_large` 413 · `unsupported_media_type` 415 · `rate_limited` 429 (+`Retry-After`) · `stt_unavailable` 422 · `provider_unavailable` 503 · `internal_error` 500 |
| Correlation | Every response carries `X-Request-ID` (echoed if the client sends one) |
| Idempotency | Optional `Idempotency-Key` header (≤ 64 chars) on mutating calls. Same key + same user + same route replays the first response with `Idempotent-Replayed: true` (24 h) |
| Pagination | `limit` 1–100 (default 25) + opaque `cursor`; responses `{items: [...], next_cursor: string \| null}` |
| Rate limits | Per user; headers `X-RateLimit-Limit`, `X-RateLimit-Remaining` |
| Unknown request fields | Rejected with 422 (`extra = forbid`) |
| Honesty | Responses never imply a capability the provider lacks. Unsupported actions return 409 `unsupported_by_provider` and `CallDetail.capabilities` explains why |

Number privacy: raw phone numbers are **never returned**. `caller_display` is a masked rendering such as `+91 98•••• ••21`
(country code, first two and last two national digits; short numbers keep only their last digit).
Raw numbers are only stored (encrypted) if `retention.store_full_caller_number` is true.

## System

| Method & path | Request | Response |
| --- | --- | --- |
| `GET /system/status` | – | `SystemStatus` |
| `GET /me` | – | `{id, display_name, auth_mode}` |
| `GET /home` | – | `HomeSummary` |

```text
SystemStatus = {
  version, env, auth_mode: "dev"|"oidc", dev_banner: bool,
  telephony: { provider: "simulator"|"azure"|"asterisk"|"other", simulated: bool, live_calls_supported: bool,
               forwarding_number: string|null, note: string,
               connection: "simulated"|"local_sip"|"pstn",              // how calls reach Sparta
               pstn: "not_applicable"|"not_configured"|"provider",      // can an ordinary phone number reach it?
               takeover: "none"|"simulated"|"phone_number"|"sip_extension" },
  stt_provider, tts_provider, llm_provider, llm_model: string|null,
  features: { simulator: bool, personal_voice: bool, llm_summaries: bool, translation: bool, raw_audio_storage: false },
  policy_version, language_pack_version,
  languages: [{ code, name, native_name, status: "supported"|"planned" }],
  limits: { max_call_duration_s, max_audio_bytes, max_audio_seconds, daily_call_cap }
}
HomeSummary = {
  protection: { status: "active"|"attention"|"degraded"|"setup_needed", headline, detail, provider, simulated, live_calls_supported,
                connection: "simulated"|"local_sip"|"pstn", pstn: "not_applicable"|"not_configured"|"provider" },
  today: { handled, high_risk, escalations, ended_spam, minutes_handled },
  next_action: { kind: "finish_onboarding"|"review_escalation"|"review_call"|"run_simulator"|"none", label, route },
  attention: CallListItem[],   // calls that need the owner
  recent: CallListItem[]       // last 5 calls
}
```

## Calls

| Method & path | Request | Response |
| --- | --- | --- |
| `POST /calls` | `CreateCallRequest` | `CallDetail` (201). Creates a call through the **configured** telephony provider. Real providers create calls from provider webhooks, so this returns 409 `unsupported_by_provider` unless the provider is the simulator |
| `GET /calls` | query: `q`, `risk_level`, `category`, `language` (BCP-47), `status` (`active`\|`ended`\|`failed`), `attention` (bool), `provider`, `from`, `to` (ISO), `limit`, `cursor` | `{items: CallListItem[], next_cursor}` |
| `GET /calls/{id}` | – | `CallDetail` |
| `POST /calls/{id}/turns` | `{text, source?: "typed"\|"browser_stt"\|"scripted", language_hint?, stt_confidence?, client_turn_id?}` | `TurnResult` |
| `POST /calls/{id}/partial` | `{text, language_hint?}` | 204. Emits `transcript.partial` only (no pipeline run) |
| `POST /calls/{id}/audio` | multipart: `file` (`audio/wav`, `audio/ogg`, `audio/webm`, ≤ `max_audio_bytes`, ≤ `max_audio_seconds`), `language_hint?`, `transcript_hint?` | `TurnResult`, or 422 `stt_unavailable` when STT is the simulator and no `transcript_hint` was given (the simulator cannot transcribe audio; configure Azure Speech) |
| `POST /calls/{id}/interrupt` | `{turn_id?, spoken_fraction?: 0..1}` | `{interrupted: bool, turn_id, interruption_ms}`. Caller barge-in: stops assistant playback, preserves state |
| `POST /calls/{id}/silence` | `{}` | `TurnResult`. Fires one silence timeout (what the timer does in a real call) |
| `POST /calls/{id}/takeover` · `/continue` · `/end` | `{}` | `OwnerActionResult` (409 `unsupported_by_provider` when the provider cannot do it) |
| `POST /calls/{id}/block` | `{reason?}` | `BlockedCaller` |
| `POST /calls/{id}/trust` | `{label?}` | `TrustedCaller` |
| `POST /calls/{id}/feedback` | `{kind: FeedbackKind, note?}` | `FeedbackRecord` (idempotent per call+kind) |
| `GET /calls/{id}/events` | query `after_seq` | `LiveEvent[]` (event log) |
| `GET /calls/{id}/report` | – | Sanitized diagnostic report (no transcript text, no numbers); `Content-Disposition: attachment` |
| `GET /calls/{id}/export` | – | Full JSON export of that call (owner only) |
| `DELETE /calls/{id}/content` | – | 204. Removes transcript, translations, claims and summary text; keeps timestamps, risk level, category |
| `DELETE /calls/{id}` | – | 204. Removes the call entirely |
| `DELETE /calls` | – | 204. Removes **all** of the owner's call content |

```text
CreateCallRequest = { caller_number?: string, caller_label?: string, language_mode?: "auto"|<BCP-47 supported code>,
                      network_profile?: "ideal"|"mobile_4g"|"congested", scenario_id?: string, autoplay?: bool }
TurnResult = { caller_turn: CallTurn, assistant_turn: CallTurn|null, call: CallListItem, risk: RiskAssessment,
               state: CallState, ended: bool, escalation: Escalation|null }
OwnerActionResult = { action: OwnerAction, call: CallListItem, capabilities: CallCapabilities }
CallListItem / CallDetail / CallTurn / RiskAssessment / CallCapabilities / Escalation / OwnerAction /
CallSummary / FeedbackRecord / BlockedCaller / TrustedCaller / LatencyBreakdown: see domain/models.py
```

`CallDetail.capabilities` is authoritative for which owner controls are enabled. UIs must disable unsupported controls
and show `takeover_note` / `audio_note`. For the simulator: `simulated: true`, `two_way_audio: false`, takeover is a
labelled simulation. For Azure Communication Services: `two_way_audio: true` only if media streaming is connected.
For local SIP through Asterisk (`TELEPHONY_PROVIDER=asterisk`): `two_way_audio: true` only while that call's media socket
is attached, and `takeover_via: "sip_extension"` (Take Over rings the configured owner SIP extension on the local server,
never a phone number, and only while the call's audio is connected). `takeover_via` is `"phone_number"` for the
phone-network providers, `"simulated"` for the simulator and `"none"` for a provider that cannot transfer.
`SystemStatus.telephony.connection = "local_sip"` with `pstn = "not_configured"` says that ordinary phone numbers cannot
reach Sparta through this provider: that needs a carrier, a number and a trunk, which Sparta does not provide.

`CallDetail.assistant_speaking` / `speaking_turn_id` say whether the assistant is mid-utterance *right now* (so a client
that joins or reconnects during speech can show it; the turn's `speech.est_duration_ms` gives the length). Whenever a
caller turn follows speech whose estimated duration has already elapsed, `assistant.finished` is emitted for that
speech before the caller's `transcript.final`; a caller turn that arrives while the speech is still playing is a
barge-in (`assistant.interrupted`).

## Live events (WebSocket)

1. `POST /live/ticket` with `{call_id?: string}` → `{ticket, expires_in, ws_url}`. Tickets are single-use, ≈ 60 s, bound to
   the user (and call when given). (Browsers cannot attach `Authorization` to WebSocket upgrades.)
2. Connect `wss://host/api/v1/live?ticket=…` (all of the user's calls) or `/api/v1/live/{call_id}?ticket=…`.
   Browser origins must be in `SPARTA_CORS_ORIGINS`/`SPARTA_ALLOWED_WS_ORIGINS`; native apps (no `Origin` header) rely on
   the ticket. Close codes: `4401` bad/expired ticket · `4403` origin not allowed · `4404` call not found · `4429` too many connections.
3. Each text frame is a `LiveEvent` envelope `{type, call_id, seq, ts, simulated, data}`. `seq` is monotonic per call.
   Call-specific sockets start with `call.snapshot` (`data = {call: CallDetail}`), so late joiners are in sync; reconnect
   and resume with `GET /calls/{id}/events?after_seq=` if you need gaps filled. The server sends `{"type":"ping"}` every
   20 s; clients need not answer.

| `type` | `data` |
| --- | --- |
| `call.snapshot` | `{call: CallDetail}` |
| `call.created` | `{call: CallListItem}` |
| `call.connected` | `{state}` |
| `call.listening` | `{}` |
| `state.changed` | `{from, to}` |
| `transcript.partial` | `{speaker, text, language?}` |
| `transcript.final` | `{turn: CallTurn}` |
| `language.changed` | `{from, to, profile, confidence}` |
| `risk.updated` | `{risk: RiskAssessment}` |
| `assistant.speaking` | `{turn_id, text, locale, voice_id, est_duration_ms}` |
| `assistant.finished` | `{turn_id}` |
| `assistant.interrupted` | `{turn_id, spoken_fraction, interruption_ms}` |
| `escalation.requested` | `{escalation: Escalation, risk: RiskAssessment}` |
| `owner.takeover` | `{action: OwnerAction, simulated}` |
| `owner.action` | `{action: OwnerAction}` |
| `call.ended` | `{reason, state, duration_ms}` |
| `summary.created` | `{summary: CallSummary}` |
| `provider.error` | `{provider, stage, message, degraded}` (sanitized) |

## Preferences, assistant and voice

| Method & path | Request | Response |
| --- | --- | --- |
| `GET`/`PUT /preferences` | `UserPreferences` (PUT replaces, validated) | `UserPreferences` |
| `GET`/`PUT /assistant-profile` | `AssistantProfile` | `AssistantProfile`. `use_personal_voice=true` is rejected (409) unless the voice is `ready` and the feature is on |
| `POST /assistant-profile/preview` | `{language?: "auto"\|BCP-47, sample_text?: string}` | `{disclosure: SpeechPlan, reply: SpeechPlan\|null, risk: RiskAssessment\|null, detected_language: string\|null}`. Runs the **real** pipeline on `sample_text` without creating a call |
| `GET /voices` | – | `VoiceOption[]` |
| `GET /voice/status` | – | `VoiceProfileView` |
| `GET /voice/consent` | – | `{version, text, requires_provider_approval, supported_locales}` |
| `POST /voice/enroll` | `{consent: true, consent_version, speaker_name}` | `VoiceProfileView`. Status becomes `pending_provider_approval` (provider approval cannot be completed in-app) |
| `DELETE /voice` | – | 204 |

AI disclosure is always on. `AssistantProfile` cannot disable it.

## Safety Center

| Method & path | Response |
| --- | --- |
| `GET /safety/policies` | `{version, name, protected_information: [{code, label}], signals: [{code, kind, severity, description, protected}], strictness, limits, prompt_injection: {summary, examples: string[]}}` |
| `GET /safety/events?limit=` | `[{call_id, at, risk_level, category, action, signal_codes: string[]}]` (never transcript text) |
| `GET /blocked-callers` · `POST /blocked-callers {number, reason?}` · `DELETE /blocked-callers/{id}` | `BlockedCaller[]` · `BlockedCaller` · 204 |
| `GET /trusted-callers` · `POST /trusted-callers {number, label?}` · `DELETE /trusted-callers/{id}` | `TrustedCaller[]` · `TrustedCaller` · 204 |
| `GET /audit?limit=` | `[{at, action, target_type, target_id, detail}]` (sensitive actions; no content) |

## Simulator Lab

| Method & path | Request | Response |
| --- | --- | --- |
| `GET /simulator/providers` | – | `[{id, kind: "telephony"\|"stt"\|"tts"\|"llm", active: bool, available: bool, simulated: bool, label, reason}]` |
| `GET /simulator/scenarios` | – | `ScenarioSummary[]` (curated + the owner's own) |
| `POST /simulator/scenarios` | `{title, language_profile, turns: [{text, language?, delay_ms?}]}` | `ScenarioSummary` (validated, ≤ 14 turns) |
| `POST /simulator/calls` | `CreateCallRequest` (always the simulator adapter) | `CallDetail`. With `scenario_id` + `autoplay`, scripted caller turns are played server-side with their gaps and streamed over the live socket |
| `POST /simulator/replay` | `{scenario_id, language_mode?, network_profile?}` | `{call: CallDetail, events: LiveEvent[], checksum}`. Deterministic: virtual clock, no randomness; the same input yields the same `checksum` |

`ScenarioSummary = {id, title, description, language_profile, languages: string[], tags: string[], turn_count, expected_action, custom: bool}`.
`network_profile` adds **simulated** stage latencies; affected stages are listed in `LatencyBreakdown.simulated_stages`.

## Android screening (native CallScreeningService)

| Method & path | Request | Response |
| --- | --- | --- |
| `GET /screening/config` | – | `{fingerprint_salt (base64), unknown_caller_behavior, trusted_contact_behavior, strictness, forwarding_number, provider, live_calls_supported}` |
| `GET /screening/lists` | – | `{blocked: [{id, fingerprint, number_display}], trusted: [{id, fingerprint, number_display, label}]}` |
| `POST /screening/events` | `{client_event_id (uuid), number_fingerprint, number_display, decision: "allow"\|"silence"\|"reject", reason, verification_status?, direction?, occurred_at}` | `CallListItem`. Idempotent on `client_event_id`. Creates a `screening_only` call with provider `android_screening` |

Fingerprint = hex `HMAC-SHA256(key = base64-decode(fingerprint_salt), message = E.164 number)`. The device never sends raw numbers.
A `screening_only` call has no transcript and `capabilities.two_way_audio = false`: native screening cannot answer a call or
access call audio.

## Provider callbacks (not for UI clients)

| Path | Purpose |
| --- | --- |
| `POST /webhooks/acs/events` | Azure Event Grid delivery: subscription-validation handshake + `IncomingCall`; Event Grid bearer-token validated |
| `POST /webhooks/acs/callbacks/{call_id}` | Call Automation callbacks; ACS callback JWT (RS256, JWKS) validated |
| `WS /media/acs/{call_id}` | ACS bidirectional audio stream (PCM 16 kHz mono JSON frames) |
| `POST /webhooks/twilio/voice` | Twilio voice webhook for a call to the number: `X-Twilio-Signature` validated (HMAC-SHA1 of the configured public URL plus the sorted form fields); creates the call and answers with TwiML that streams its audio here (a per-call stream token travels as a `<Parameter>`), or `<Reject>` when a cost limit is reached; idempotent per `CallSid` |
| `POST /webhooks/twilio/status` | Twilio call-status callback (optional): signature validated; a terminal status ends the call if the media stream did not already |
| `WS /media/twilio/{call_id}` | Twilio Media Streams (G.711 mu-law 8 kHz, base64 JSON messages `connected`, `start`, `media`, `mark`, `stop`); the upgrade must carry Twilio's signature and the `start` message the per-call token |
| `POST /webhooks/asterisk/incoming` | Asterisk dialplan `CURL()` callback for a call to the Sparta extension (form fields `channel`, `exten`, `caller`): HTTP Basic with the shared secret (constant-time compare), the peer must be Asterisk's allow-listed address, and a request carrying `X-Forwarded-For`, `Forwarded` or `X-Real-IP` is refused. Answers one plain-text line: `ACCEPT <single-use media id>` (the dialplan then opens the AudioSocket media connection) or `REJECT busy\|declined\|unavailable` (a call limit; another extension or a blocked caller; a provider or policy refusal); idempotent per channel |
| `POST /webhooks/asterisk/next` | After the media socket ends: `DIAL <owner extension>` (a takeover) or `HANGUP`; same authentication |
| `POST /webhooks/asterisk/ended` | The dialplan reports that the call is over (idempotent, Sparta may already know); same authentication |
| AudioSocket TCP (port 8090, not HTTP) | The call's audio: signed 16-bit little-endian PCM, mono, 8 kHz, 20 ms frames, in Asterisk's AudioSocket framing; the connection must open with the single-use media id from `ACCEPT` and come from the allow-listed peer. It is listened on inside the Compose network only and is not an OpenAPI route (see `docs/TELEPHONY.md` §4.5) |
| `POST /webhooks/generic` | HMAC-SHA256 signed (`X-Sparta-Signature`) events for other providers; replay-protected with timestamp + nonce |

All webhook handlers are idempotent on the provider event id and never trust unsigned input. See `docs/TELEPHONY.md`.
