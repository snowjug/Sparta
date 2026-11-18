# Privacy

What Sparta stores, what is encrypted, how long it is kept, how it is deleted, and which outside services can receive data.
This document describes the code in `services/api` at commit `5f980d1`
([IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) section 6). It is not legal advice and makes no legal claim:
privacy, call-recording, interception and data-transfer rules differ by country and by use, and Sparta has not had a
legal review. See [section 13](#13-legal-review).

Related: [SAFETY_MODEL.md](SAFETY_MODEL.md), [THREAT_MODEL.md](THREAT_MODEL.md), [ARCHITECTURE.md](ARCHITECTURE.md),
[TELEPHONY.md](TELEPHONY.md), [ANDROID_SETUP.md](ANDROID_SETUP.md) (what the Android app stores on the phone).

## 1. Defaults at a glance

| Setting | Default | Where |
| --- | --- | --- |
| Raw audio stored | never (not implemented; see section 8) | `services/audio_validation.py`, `api/main.py`, `config.py` |
| Transcripts stored | yes, for 7 days (allowed range 0 to 365) | `RetentionPolicy` in `domain/models.py` |
| Summaries and risk records kept | 90 days (allowed range 1 to 730) | `RetentionPolicy` |
| Full caller number stored | no; only a keyed fingerprint and a masked display | `RetentionPolicy.store_full_caller_number` |
| Personal voice | off; consent recorded only, no voice can be created (section 10) | `config.py`, `services/owner.py` |
| Language model (Azure OpenAI) | off; decisions and replies use rules and templates | `SPARTA_LLM_PROVIDER=rules` |
| Speech recognition and synthesis | simulator, which sends nothing anywhere | `SPARTA_STT_PROVIDER`, `SPARTA_TTS_PROVIDER` |
| Metrics endpoint | off | `SPARTA_EXPOSE_METRICS` |
| Telemetry export | none unless `SPARTA_OTLP_ENDPOINT` is set; traces only, no metrics or logs (section 9) | `observability/tracing.py`, `config.py` |

## 2. What is stored

All tables are in `services/api/src/sparta/db/models.py`. "Encrypted" means Fernet field encryption (section 3). Every
column that is not marked encrypted is stored in clear in the database.

| Data | Table and columns | Encrypted | Notes |
| --- | --- | --- | --- |
| Owner account | `users`: `id`, `display_name`, `created_at` | no | `id` is the OIDC subject (hashed to `u_<40 hex>` when it is not a short plain string) or the development id. `display_name` comes from the token's `name` or `preferred_username` claim |
| Preferences | `user_preferences.data` | yes | Languages, strictness, silence timeouts, maximum call duration, escalation rules, notification flags, retention settings and the optional `takeover_number` (the owner's phone number for take-over) |
| Assistant profile | `assistant_profiles.data` | **no** | The owner's display name used in greetings, response style, speaking rate and chosen voices |
| Voice consent record | `voice_profiles`: `status`, `consent_version`, `consent_recorded_at`, `provider_voice_id`, `detail`; `speaker_name` | `speaker_name` only | No audio is stored (section 10) |
| Blocked and trusted callers | `blocked_callers`, `trusted_callers`: `fingerprint`, `number_display`; `number_enc`, `label`, `reason` | `number_enc`, `label`, `reason` | `number_enc` is filled only when the owner turned on full-number storage |
| Call record (shell) | `call_sessions`: timestamps, `provider`, `status`, `state`, `language_mode`, `caller_display` (masked), `caller_fingerprint`, `caller_label`, `category`, `risk_level`, `risk_score`, `confidence`, `recommended_action`, `signal_codes`, `languages`, `language_profile`, `action_taken`, `owner_attention`, `blocked`, `trusted`, `has_content`, `config`, `trace_id`, `versions`, `metrics`, `external_id`, `scenario_id`, `network_profile`, `event_seq`, `client_event_id` | no | Enough to list, filter, cap and explain calls without decrypting anything. `config` is a snapshot of the engine settings for the call and includes the owner's display name. `caller_label` is a label typed for a simulated call. `external_id` is the provider's call id |
| Call content | `call_sessions`: `caller_number_enc`, `claim` (claimed name, organisation, role), `purpose`, `summary_text`, `context` | yes | `caller_number_enc` only with full-number storage on. `context` is the conversation state, including detected signals with short evidence excerpts |
| Turns | `call_turns`: `text`, `transliteration`, `translation`, `speech` | yes | The transcript of both speakers. Language, confidences, segment offsets, interruption data and latency are in clear |
| Risk assessments | `risk_assessments.data` | yes | Signals, reasons and evidence excerpts (at most 160 characters, runs of four or more digits masked) |
| Escalations | `escalations`: `reason`, `important_lines` | yes | Status and timestamps in clear |
| Owner actions | `owner_actions`: `action`, `created_at`, `simulated`, `result`, `detail` | no | Short labels only (for example "Simulated: no real call was bridged") |
| Summaries | `call_summaries`: `text` | yes | Category, risk level, action taken, whether the owner must act and the generator name are in clear |
| Feedback | `feedback`: `note` | yes | `kind` in clear. Feedback never changes production behaviour by itself |
| Live events | `live_events`: `data` | yes | The event log of a call (it carries transcript lines). `type`, `ts`, `seq` in clear |
| Provider events | `provider_events`: `provider`, `external_id`, `event_type`, `call_id`, `received_at`, `detail` | no | Event ids used to detect duplicates; `detail` is at most 200 characters of metadata such as "verification=...; direction=..." for Android screening events. `received_at` is when the server received the event; the daily cap on Android screening events counts rows by it, not by the time the client says the call happened |
| Audit trail | `audit_events`: `user_id`, `at`, `action`, `target_type`, `target_id`, `detail`, `request_id` | no | Identifiers and short labels only; keys containing words such as text, transcript, number, name, note or token are dropped and values are cut at 80 characters (`services/audit.py`) |
| Idempotency records | `idempotency_keys`: key, route, request hash, status, `call_id` (set when the response is a call that the request created), expiry; `response` | `response` only | A copy of the first response to a mutating request that carried an `Idempotency-Key`. Kept 24 hours, except for `/calls/{id}/turns`, `audio`, `silence` and `feedback` (they carry what the caller said or what the owner wrote; of these only `turns` and `feedback` accept an `Idempotency-Key` today): those are kept 15 minutes, and when the owner stores no transcripts only a 409 marker is kept (`api/deps.py`). A copy is deleted together with the call or its content when its route names the call or its `call_id` is the call (migration `0002`), and removing a blocked or trusted entry deletes the cached `POST` responses of that list. The request hash is an HMAC-SHA256 of the route and the request body, keyed with the pepper and scoped to the owner (`_request_fingerprint` in `api/deps.py`), stored in clear even when the owner stores no transcripts; it cannot be used to confirm a guessed number without the pepper |
| Custom simulator scenarios | `simulator_scenarios.data` | yes | Scenario text the owner typed (up to 50 per owner) |

Not stored in the database: the caller's raw phone number (unless the owner opts in), call audio, and any contact,
calendar or financial data. Short-lived state outside the database: WebSocket tickets (60 seconds), rate-limit counters,
call locks and webhook replay keys, held in the key-value store (in process memory, or Redis when `SPARTA_REDIS_URL` is
set). Speech buffers during a live call exist only in memory until the recogniser has them.

## 3. Encryption and keys

* **Field encryption.** `db/crypto.py` uses `cryptography`'s `MultiFernet`: the first key in `SPARTA_DATA_KEYS`
  (comma-separated) encrypts, every key can decrypt. Content-bearing columns are encrypted before they reach the
  database, so database backups and snapshots hold ciphertext for them regardless of the storage engine.
  `python -m sparta keygen` prints a new key, pepper and webhook secret.
* **Rotation.** Put the new key first and deploy. Rows are re-encrypted only when they are rewritten; no re-encryption
  command ships. Keep an old key in the list until every row it encrypted has been deleted by retention or rewritten.
  A value that no configured key can decrypt raises `DecryptionError`.
* **Development keys.** Outside production, if `SPARTA_DATA_KEYS` and `SPARTA_PEPPER` are unset, the first run creates
  `dev-data.key` and `dev-pepper.key` in `SPARTA_DATA_DIR` (default `./var`). `.gitignore` excludes `var/` and `*.key`.
  In `SPARTA_ENV=test` an ephemeral key is generated per process.
* **Production guards.** `Settings.problems()` refuses to start in production without `SPARTA_DATA_KEYS`,
  `SPARTA_PEPPER` and `SPARTA_WEBHOOK_SECRET`, with SQLite, without Redis, with development authentication, with
  wildcard or non-HTTPS CORS origins, or with the raw-audio flag on.
* **Not provided by the application.** The service speaks plain HTTP; TLS must be terminated in front of it (in
  production it adds an HSTS header). Encryption of the database volume, of Redis and of backups at the storage level is a
  deployment matter ([DEPLOYMENT.md](DEPLOYMENT.md)); nothing in the code can verify it.
* **Clear columns are not encrypted.** Section 2 lists them. In particular the owner's display name, `caller_label`
  and the classification fields are stored in clear.

## 4. Caller numbers

`services/numbers.py` and `db/crypto.py`:

* A number is normalised to E.164 (10-digit numbers get +91). The API never returns it.
* **Fingerprint:** `HMAC-SHA256(key, E.164)` as hex, where the per-owner key is derived from `SPARTA_PEPPER` and the owner
  id. It lets blocked and trusted lists match without storing numbers. The Android app receives the key as base64
  (`GET /screening/config`) and computes the same fingerprint on the phone. Changing `SPARTA_PEPPER` changes every
  fingerprint, so existing blocked and trusted entries stop matching.
* **Masked display:** `+91 98•••• ••21` (country code, first two and last two national digits; short numbers keep only
  the last digit). A call that also has a label shows `label · +91 98•••• ••21` (`services/calls.py`). Device-supplied
  display strings are re-masked if they look like a full number (`safe_display` in `services/owner.py`).
* **Provider delivery.** A telephony provider hands the raw number to the service in memory (`IncomingCall`); it is not
  logged and not returned. It is stored (encrypted) only when `store_full_caller_number` is on.

## 5. Retention: two clocks

`services/retention.py` runs inside the API process every `SPARTA_RETENTION_JOB_INTERVAL_S` (default 3600 seconds; the
first run is one interval after start) and purges each owner's backlog in batches of 500 calls, at most 20 batches (10,000
calls) per owner per run. Each owner's own settings apply.

1. **Transcript clock** (`transcript_retention_days`, default 7, measured from the call's end). `delete_transcript`
   removes the turns, the live-event log, the quotes in escalations and every evidence excerpt (in risk rows and in the
   call context), and sets `has_content = false`.
   **Kept:** the summary, the caller's claimed name and organisation, the purpose, and the structured risk explanation
   (signal codes, reasons, scores, category, level, action taken), none of which quote the caller.
2. **Record clock** (`summary_retention_days`, default 90, measured from the call's start). The whole call record and
   everything attached to it is deleted.

If the owner switches transcript storage off (`store_transcripts = false`), the transcript is deleted the moment the call
is finalised (the live conversation still needs it while the call is open).

Short-lived technical rows are purged in the same job: idempotency records once they have expired (15 minutes or 24 hours,
section 2) and provider event ids after 30 days. Active calls are never purged.

## 6. Deletion paths

| Action | What it deletes | What remains |
| --- | --- | --- |
| `DELETE /api/v1/calls/{id}/content` (owner "delete content"; refused while the call is active) | Turns, live events, risk assessments, escalations, the summary, feedback rows that have a note and the cached idempotent responses that belong to the call (requests made against it, and the response that created it); clears the claim, purpose, summary text, any stored full number, signal codes and language list; resets the context | A shell: timestamps, duration, provider, category, risk level and score, confidence, recommended action, action taken, language profile, masked display, number fingerprint, `caller_label`, owner-attention flag, metrics, versions, trace id, `has_content = false` |
| `DELETE /api/v1/calls/{id}` (refused while active) | The whole call and everything attached, including those cached responses | Audit entries about it, and provider event ids (purged after 30 days) |
| `DELETE /api/v1/calls` | Content of every call the owner has (as `DELETE .../content` for each) | The shells |
| Transcript retention (section 5) | Transcript content only | Summary, claim, purpose, structured risk explanation |
| Record retention (section 5) | The whole call | Audit entries |
| `DELETE /api/v1/voice` | The voice consent record, and switches off `use_personal_voice` | Audit entries, and the cached response to `POST /voice/enroll` until it expires (up to 24 hours) |
| `DELETE /api/v1/blocked-callers/{id}`, `DELETE /api/v1/trusted-callers/{id}` | The list entry, including any stored number, and the cached idempotent responses to the `POST` requests that added entries to that list | Audit entries |
| `GET /api/v1/calls/{id}/export` | Not a deletion. Downloads everything stored for the call, including the transcript while it is retained; the access is audited | |
| `GET /api/v1/calls/{id}/report` | Not a deletion. A diagnostic report with identifiers, states, timings and signal codes; no transcript text, names or numbers | |

Gaps in this release, stated plainly:

* There is **no account-deletion operation**. Nothing in the code deletes a `users` row; the owner can delete calls,
  lists and the voice record, and overwrite preferences and the assistant profile.
* **Audit events are never purged.** They carry identifiers and short labels, not content, but no job removes them.
* **Two kinds of cached response outlive their deletion.** A cached response that belongs to a call (its route names the
  call id, or the response is the call that the request created) is deleted with the call's content or the call
  (`delete_idempotent_for_call` in `db/repository.py`, migration `0002`;
  `tests/api/test_api_hardening.py::test_deleting_a_call_forgets_the_cached_response_that_created_it`), and removing a
  blocked or trusted entry deletes the cached `POST` responses of that list for the owner (`forget_cached_creations` in
  `api/deps.py`; `test_removing_a_list_entry_forgets_the_cached_response_that_added_it`). Verified on 2026-11-18 through
  the API: after `DELETE /blocked-callers/{id}` and after `DELETE /trusted-callers/{id}` no cached row was left, and
  repeating the creation request with the same `Idempotency-Key` created a new entry instead of replaying the removed
  one. Two routes still keep their encrypted response for up to 24 hours (plus up to the retention job interval):
  `POST /voice/enroll` (the consent status view; `DELETE /voice` does not delete it) and the creation of a simulator
  scenario (title, description and tags, not the scripted turns; no route deletes a scenario). Expiry of the transcript
  clock does not itself delete cached responses: the content routes' copies expire after 15 minutes and the hourly job
  removes expired rows.
* The owner's display name (assistant profile and each call's `config`), `caller_label` and the classification fields
  are in clear and are not removed by "delete content".

## 7. Transcripts

* A transcript consists of the caller's recognised or typed text, the assistant's lines (always from templates), a Latin
  transliteration for Hindi and Kannada lines and an English wording of assistant lines. Caller text is sanitised and cut at
  1000 characters before use.
* It is shown to the owner, exported on request and can be removed as described above. Escalation notifications carry
  only the latest important lines, and only when `include_transcript_lines` is on; digit runs of four or more characters
  are masked in those lines.
* Transcripts are part of the live event log, which is stored encrypted and deleted together with the turns.

## 8. Raw audio

* Raw audio is **not stored anywhere**. Uploaded clips (`POST /calls/{id}/audio`) are type-sniffed, size-checked (8 MB
  default) and, for WAV, duration-checked (120 s default), transcribed in memory and discarded. The multipart parser's
  spool threshold is raised above the upload limit, so a permitted upload is never written to a temporary file
  (`api/main.py`).
* Live provider audio is fed through the voice-activity detector and the recogniser from memory; `services/audio_pipeline.py`
  keeps a 300 ms pre-roll and the current utterance in memory only, and drops them after recognition.
* The retention setting `store_raw_audio` exists but the API refuses `true` ("Raw audio storage is not available in this
  release"), and `SPARTA_FEATURE_RAW_AUDIO_STORAGE` is only read by the production guard that refuses it. No code path
  writes audio.
* Audio is not stored by Sparta; when Azure Speech is configured the audio **is sent to Azure** for recognition (section
  11). What Azure does with it is governed by Microsoft's terms and your Azure configuration; Sparta has not verified it.

## 9. Logs, metrics and telemetry

* **Structured logs** (`logging_setup.py`) redact by field name (anything that looks like content, a credential, a
  number, an address or a ticket) and by value pattern (bearer tokens, JWTs, e-mail addresses, phone-like numbers and runs
  of four to eight digits). The HTTP access line has the method, path, status and duration and **no query string**,
  because WebSocket tickets are in query strings; uvicorn's own access log is turned off for the same reason (`cli.py`).
  Unexpected errors log the exception type and a redacted traceback.
* **Metrics** (`observability/metrics.py`) are counters and timings with short, sanitised label values
  (provider, stage, outcome). They are served as Prometheus text on `/metrics` only when `SPARTA_EXPOSE_METRICS=true`;
  restrict that route to a monitoring network.
* **Tracing.** Spans exist (`observability/tracing.py`): one server span per HTTP request (`api/middleware.py`; Sparta
  creates none for WebSocket connections), named `METHOD /route/template` with the attributes `http.request.method`,
  `http.route`, `http.response.status_code` and `sparta.request_id`; one `provider.call` span per call that goes through
  `ResilientCaller` (the Azure speech, Azure OpenAI and Azure telephony adapters and the call service's model call; the
  simulator providers make none) with `provider` and `stage`, plus `error.type` with the exception class when it fails
  (`providers/resilience.py`); and one `engine.on_caller_turn` span per caller turn (`call_id`, `source`,
  `sparta.final_state`, `sparta.risk_level`; `services/calls.py`). `tests/api/test_api_tracing.py` asserts that Sparta's
  spans hold no path call id, query string, number, label, caller text or exception message. Nothing leaves the process
  unless `SPARTA_OTLP_ENDPOINT` is set and the `otlp` extra is installed (the default Docker image installs it,
  `services/api/Dockerfile`); the traces then go to that endpoint over OTLP/HTTP. There is no metrics or log export. A call
  created while serving a request takes that request's trace id (`CallDetail.trace_id`, shown as a diagnostic id and
  present in logs and reports); with no active span the id is random. Sparta's request span is a root span: an incoming
  W3C `traceparent` header does not choose the trace id (`test_a_callers_traceparent_does_not_choose_the_trace_id`).
* **FastAPI's own telemetry is switched off.** FastAPI 0.16x instruments itself against the global tracer provider that
  `setup_tracing` installs, and its spans carry the raw `url.path` (which holds call ids), the whole `url.query` (a history
  search term is content), a trace id taken from a caller's `traceparent`, and three child spans per request. Sparta
  passes `telemetry` options set to `False` to `FastAPI(...)` whenever the installed version has that parameter
  (`_own_telemetry_only` in `api/main.py`; older versions have no such behaviour), so Sparta's spans are the only ones.
  Verified on 2026-11-18 against a running API with a local OTLP listener: every exported span came from Sparta's tracer
  (no `fastapi` scope), none carried `url.path` or `url.query`, a search term sent in `?q=` was not exported, and a call
  created with a forged `traceparent` got a different trace id. The tests configure a global tracer provider so that a
  span of FastAPI's own would show up (`test_only_sparta_spans_exist_and_none_carries_the_url`).
* **Cost estimates** use unit prices you configure; they are guardrail figures, not billing data.

## 10. Personal voice

* **Default and gating.** `SPARTA_FEATURE_PERSONAL_VOICE` is off. Sparta uses a predefined neural voice for each language
  (`providers/tts/catalog.py`). The AI disclosure does not depend on the voice: it is the assistant's opening line whatever
  voice is used.
* **Consent flow** (`services/owner.py`). `GET /voice/consent` returns a versioned statement (`CONSENT_VERSION`
  `2026-11-01`): the person enrolling says they are the speaker or hold the speaker's explicit permission, that a
  synthetic copy of the voice would speak on calls handled by the AI assistant, that the assistant always announces it is
  an AI, that they can withdraw consent and delete the voice at any time, that the voice provider must approve the use case
  first, and that Sparta stores no recording of their voice. `POST /voice/enroll` requires `consent: true`, the current
  consent version and a speaker name; it records consent, sets the status to `pending_provider_approval` and audits the
  action. Sparta cannot verify who is speaking or whether permission exists.
* **No voice can be created in this release.** The status never moves past `pending_provider_approval`: no code calls
  Azure Personal Voice, no code sets the status to `ready`, and `PUT /assistant-profile` with `use_personal_voice: true`
  is refused with 409 unless the feature is on and the status is `ready`. Azure's own Limited Access approval cannot be
  completed inside Sparta ([research/azure-speech-openai-verification.md](research/azure-speech-openai-verification.md)).
  The consent view lists `en-IN` and `hi-IN` only; Kannada personal voice is not listed in the documentation.
* **No automatic cloning, no training on calls.** Nothing stores caller audio, so there is nothing to train on, and no
  code creates a voice from a recording.
* **Deletion.** `DELETE /voice` removes the consent record and switches `use_personal_voice` off. There is no provider
  voice to delete. The cached response to `POST /voice/enroll` (the consent status view, no speaker name or audio) is not
  deleted with it and expires within 24 hours (section 6).

## 11. Outside services that can receive data

Only when configured; with the defaults (simulator providers, rules, no Azure settings) no call data leaves the process.
This list is from the code; Microsoft's own retention and processing terms were not checked.

| Service | Enabled by | What Sparta sends | Code |
| --- | --- | --- | --- |
| Azure AI Speech (speech-to-text) | `SPARTA_STT_PROVIDER=azure` | Caller audio (live utterances wrapped as WAV; uploaded clips as uploaded) and the candidate locales | `providers/stt/azure.py` |
| Azure AI Speech (text-to-speech) | `SPARTA_TTS_PROVIDER=azure` | Assistant reply text as SSML and the voice name; the replies can contain the owner's display name | `providers/tts/azure.py` |
| Azure OpenAI | `SPARTA_LLM_PROVIDER=azure_openai` | Per turn: the caller's text (at most 600 characters), up to six earlier turns of **both** speakers (at most 300 characters each), already-detected signal codes and the language. The owner's display name is replaced by "the owner" in the caller's text, the earlier turns and the summary inputs before they reach the provider (`redact_owner_name` in `risk/matchers.py`, called from `services/calls.py`; `tests/integration/test_model_provider_input.py`). Words are compared in the detectors' canonical form, so accented names, repeated letters, a nukta spelled either way and possessives are found, and a full name becomes one "the owner". Name words shorter than three letters are not replaced, and a name written in another script than the profile's is sent as written. For a summary (`SPARTA_FEATURE_LLM_SUMMARIES=true`): the rules summary, which can contain the caller's claimed name and organisation, and up to 12 turns. An LLM summary is rejected if it contains a number, link or e-mail address that is not in the source | `providers/llm/azure_openai.py`, `services/calls.py` |
| Azure Communication Services and Event Grid | `TELEPHONY_PROVIDER=azure` | Call signalling and media for the call; Event Grid delivers the caller number, display name and call identifiers to Sparta's webhook | `telephony/azure_acs.py` |
| Identity provider (OIDC) | `SPARTA_AUTH_MODE=oidc` | Sparta fetches the issuer's public signing keys over HTTPS; users' tokens are sent to Sparta, not by Sparta | `api/auth.py` |
| OpenTelemetry collector | `SPARTA_OTLP_ENDPOINT` and the `otlp` extra | Traces only. Sparta's spans carry route templates, status codes, timings, request ids, provider and stage names and call ids; FastAPI's own spans, which would carry the raw path and query string, are switched off (section 9) | `observability/tracing.py`, `api/main.py` |
| Push providers (FCM, APNs) | none | Not implemented: push notifications are not sent | `services/notifier.py` |

Region, data-processing agreements and cross-border transfer for these services are deployment and legal questions
([DEPLOYMENT.md](DEPLOYMENT.md)); none of the Azure integrations has been exercised with real credentials.

## 12. What Sparta does not do

* It does not record calls and does not store raw audio.
* It does not use caller audio or transcripts to train or fine-tune any model, and no code path does so. The optional
  research note in [experiments/unsloth/README.md](../experiments/unsloth/README.md) sets the conditions under which that
  could ever be considered; it ships no training code.
* It does not clone a voice, automatically or otherwise.
* It contains no code that sells or shares call data with anyone other than the services you configure (section 11). The
  backend has no analytics, advertising or error-reporting integration.
* It does not claim to verify who a caller is, and it never reveals whether the owner is home, where they are, or any
  contact, calendar, financial or identity data.
* It has no "this call may be recorded" announcement, because it does not record. Whether another notice is needed
  where you operate is a legal question.

## 13. Legal review

Do not handle real calls before a legal review. Topics to cover, from the product brief: AI disclosure, call-recording
consent, call-interception rules, telephone-number acquisition, spam-reporting rules, data retention, cross-border data
transfer, personalised voice, India-specific telecommunications and privacy obligations, and every additional launch
region. The deployment checklist is in [DEPLOYMENT.md](DEPLOYMENT.md).
