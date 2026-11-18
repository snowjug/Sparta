# Phase 2 provider verification notes

What the vendors' own documentation says about the things the real-call path depends on, with the page each statement
comes from. **Read on 2026-11-18** from the public documentation (Microsoft Learn, Twilio Docs, vendor sites). Nothing here
was tested against a live account: a statement is **VERIFIED** when the page says it, **UNCLEAR** when pages disagree or
are silent, **NOT SUPPORTED** when the page says so. Documentation changes; re-check before relying on any line.

This extends [acs-android-verification.md](acs-android-verification.md) (Phase 1) and
[azure-speech-openai-verification.md](azure-speech-openai-verification.md).

## 1. The blockers this research found

| # | Finding | Status | Source |
| --- | --- | --- | --- |
| B1 | ACS Number Management and Direct Routing retire on **2028-09-30**; customers without an ACS resource created before **2026-10-23** cannot acquire numbers for the retiring PSTN workloads (the same guide also makes a stricter, inconsistent statement about customers without existing numbers: confirm the subscription's eligibility with Microsoft) | VERIFIED, with an inconsistency | https://learn.microsoft.com/en-us/azure/communication-services/acs-retirement-and-breaking-changes-guide |
| B2 | **No India (+91) number offer** in ACS; the India country page returns 404 and Indian billing addresses are not listed for the US or UK voice-number offers | VERIFIED | https://learn.microsoft.com/en-us/azure/communication-services/concepts/numbers/sub-eligibility-number-capability |
| B3 | Buying a number needs an eligible **paid** subscription: free and credit-based subscriptions cannot. Whether a Visual Studio Enterprise subscription counts is not stated | UNCLEAR | same page |
| B4 | ACS **trial numbers** are US toll-free only: 30 days, 60 inbound minutes, calls of at most five minutes, verified `+1` destinations | VERIFIED | https://learn.microsoft.com/en-us/azure/communication-services/concepts/telephony/trial-phone-numbers-faq |
| B5 | A **Twilio trial account** has `<Stream>` and `<Dial><Number>` removed from its TwiML (replaced by a spoken "verb is not available on trial accounts"), 75 minutes in total, 10 minutes per call, five concurrent calls, calls only to and from verified numbers | VERIFIED | https://www.twilio.com/docs/usage/trials/try-out-voice (page dated 2026-09-25) |

Consequence: a real call needs a **paid** provider account and a number the owner chooses; the smallest first test is a
US number on an upgraded Twilio account. Neither was available, so no real call was placed.

## 2. Azure Communication Services

* **Bidirectional media streaming is GA.** Audio is PCM16 mono at 16 kHz or 24 kHz in 20 ms frames; there is no 8 kHz
  format. **VERIFIED.** https://learn.microsoft.com/en-us/azure/communication-services/concepts/call-automation/audio-streaming-concept
* **Incoming call.** Event Grid event `Microsoft.Communication.IncomingCall` carries `incomingCallContext`, `from`, `to`,
  `serverCallId`, `correlationId`. An incoming call rings for 30 seconds; Microsoft recommends always-on capacity.
  **VERIFIED.** https://learn.microsoft.com/en-us/azure/event-grid/communication-services-voice-video-events
* **Delivery schema.** Event Grid supports its own schema and CloudEvents 1.0 with different validation handshakes; Sparta
  implements the Event Grid schema only. **VERIFIED.** https://learn.microsoft.com/en-us/azure/event-grid/cloud-event-schema
* **Subscription validation handshake** (Event Grid schema): answer HTTP 200 within 30 seconds with
  `{"validationResponse": "<validationCode>"}`. The handshake is not delivery authentication. **VERIFIED.**
  https://learn.microsoft.com/en-us/azure/event-grid/end-point-validation-event-grid-events-schema
* **Entra-protected delivery.** Validate the bearer token's signature against the tenant's keys, and `iss`, `aud`, `tid`,
  `exp`, `nbf`; authorise the caller by `appid` (v1 tokens) or `azp` (v2). The documented setup assigns the role
  `AzureEventGridSecureWebhookSubscriber` to **both** the `Microsoft.EventGrid` service principal **and** the
  subscription-writer app, so the role alone does not show that Event Grid is the caller. The current docs tell you to look
  the application id up in your tenant ("different for different clouds"). **VERIFIED.**
  https://learn.microsoft.com/en-us/azure/event-grid/secure-webhook-delivery ,
  https://learn.microsoft.com/en-us/azure/event-grid/scripts/powershell-webhook-secure-delivery-microsoft-entra-app.
  Sparta pins `appid`/`azp` with `SPARTA_EVENT_GRID_ALLOWED_APP_IDS`.
* **Call Automation callbacks and media WebSocket.** Bearer JWT, issuer `https://acscallautomation.communication.azure.com`,
  keys at `https://acscallautomation.communication.azure.com/calling/keys`; callback tokens last **5 minutes**, WebSocket
  tokens **24 hours**. **VERIFIED.**
  https://learn.microsoft.com/en-us/azure/communication-services/how-tos/call-automation/secure-webhook-endpoint
  * *Audience:* Microsoft's sample (`Azure-Samples/art-voice-agent-accelerator`, `apps/artagent/backend/src/utils/auth.py`)
    uses the **immutable ACS resource id** (a GUID, not the ARM path). **UNCLEAR** until a signature-verified live token is
    inspected.
  * *Algorithm:* the sample validates `RS256`; the published OpenID document advertises `RSA256`. **UNCLEAR.** Sparta
    accepts `RS256` only.
* **Transfer.** `transfer_call_to_participant(..., source_caller_id_number=None)` is optional in SDK 1.6.1; whether a PSTN
  route needs it is **UNCLEAR**, and the call-control guide says a custom caller id on transfer is unsupported. Events:
  `CallTransferAccepted`, `CallTransferFailed`. Adding the owner as a participant requires `source_caller_id_number`.
  https://learn.microsoft.com/en-us/azure/communication-services/how-tos/call-automation/actions-for-call-control
* **Limits.** No documented limit on concurrent inbound PSTN calls; 350 participants; the Calling SDK documents a 30-hour
  maximum call. A Call Automation-specific duration limit was not found. ACS has a data-location **geography** (India is
  one), not a selectable Azure region; no media-streaming availability matrix for Central or South India was found.
  **UNCLEAR.** https://learn.microsoft.com/en-us/azure/communication-services/concepts/service-limits ,
  https://learn.microsoft.com/en-us/azure/communication-services/concepts/privacy
* **Pricing** (indicative, US): local number about USD 1 per month; inbound about USD 0.0085 per minute.
  https://learn.microsoft.com/en-us/azure/communication-services/concepts/pricing . Sparta reads no price from here; the
  owner enters their own in `SPARTA_ESTIMATED_*`.

## 3. Azure Speech

* **Regions.** `centralindia` supports standalone real-time speech-to-text and neural text-to-speech; **`southindia` does
  not**. **VERIFIED.** https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions
* **Locales.** `en-IN`, `hi-IN` and `kn-IN` are listed for real-time speech-to-text. **VERIFIED.**
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=stt
* **Voices.** English: `en-IN-NeerjaNeural`, `en-IN-PrabhatNeural`, `en-IN-AartiNeural`, `en-IN-ArjunNeural` and others;
  Hindi: `hi-IN-SwaraNeural`, `hi-IN-MadhurNeural` and others; Kannada: `kn-IN-SapnaNeural`, `kn-IN-GaganNeural`.
  `en-US-AvaMultilingualNeural` and `en-US-AndrewMultilingualNeural` list English India, Hindi and Kannada among their
  languages; pronunciation of a given mixed utterance is **UNCLEAR**. **VERIFIED** (names).
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts
* **Language identification.** At most 4 candidate languages at start and 10 for continuous identification, one locale
  per base language. Continuous identification needs continuous recognition and the property
  `SpeechServiceConnection_LanguageIdMode = "Continuous"`, **and the v2 endpoint**
  `wss://{region}.stt.speech.microsoft.com/speech/universal/v2` ("currently ... you must create a SpeechConfig from the
  ... endpoint string"). It does **not** detect a language change inside one sentence. **VERIFIED.**
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-identification . Sparta uses the v2 endpoint
  for a multi-locale utterance on a region-configured resource; a custom-domain endpoint is passed through unchanged
  (**UNVERIFIED**).
* **Multilingual post-stream refinement** (a separate GA path for code-switching): Speech SDK 1.50 or later, `centralindia`,
  open-range detection instead of a candidate list, property `SpeechServiceResponse_PostProcessingOption = "PostRefinement"`;
  short utterances may not improve. **VERIFIED**, **not implemented** in Sparta.
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech#multilingual-post-stream-refinement
* **Hinglish.** `MAI-Transcribe-2` Fast Transcription documents mid-utterance Hinglish code-switching for English, Hindi and
  Kannada (a file or utterance API available in `centralindia`); `MAI-Transcribe-2-Streaming` is **public preview**,
  recommended against for production, SDK 1.52+, served from regions that do not include India. **VERIFIED**, not used.
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe ,
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe-2-streaming
* **Streaming recognition.** `PushAudioInputStream` takes headerless signed 16-bit little-endian mono PCM at **8 or 16 kHz**
  (so Twilio's 8 kHz works directly and ACS's 16 kHz works; 24 kHz needs resampling). `recognizing` events are revisable
  partials, `recognized` events are finals. `OutputFormat.Detailed` adds `NBest[].Confidence`. Segmentation silence
  timeout is property 9002 (100 to 5000 ms), initial silence timeout 3200. **VERIFIED.**
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-use-audio-input-streams ,
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-speech-recognition-results
* **Quotas.** Free tier: one concurrent real-time request and 5 audio hours a month; standard tier: 100 concurrent
  requests by default (adjustable). Text-to-speech: free tier 20 transactions per 60 s and 0.5 million neural characters a
  month; standard 30 transactions per second (adjustable). A maximum connection duration for ordinary continuous
  recognition was not found. **VERIFIED / UNCLEAR.**
  https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits
* **Text-to-speech output.** The SDK has `Raw8Khz16BitMonoPcm`, `Raw16Khz16BitMonoPcm`, `Raw24Khz16BitMonoPcm`, and the
  8 kHz mu-law and A-law formats (used for Twilio). No first-byte latency guarantee is published; measure
  `SpeechServiceResponse_SynthesisFirstByteLatencyMs`. **VERIFIED / UNCLEAR.**
  https://learn.microsoft.com/en-us/python/api/azure-cognitiveservices-speech/azure.cognitiveservices.speech.speechsynthesisoutputformat
* **Linux runtime.** The Speech SDK 1.53.1 wheel imports and builds a streaming recogniser (continuous language
  identification, 8 kHz push stream) inside the project's `python:3.12-slim` runtime image without extra system packages
  (checked by building the image and running it on 2026-11-18). That is a statement about loading the library, not about
  recognising speech.

## 4. Azure OpenAI

* Chat Completions structured outputs (`response_format` of type `json_schema`, `strict: true`) need API version
  `2024-08-01-preview` or later (GA `v1` also supports it) and a supported model (for example `gpt-4o-mini` 2024-07-18,
  `gpt-4o` 2024-08-06, `gpt-4.1-mini` 2025-04-14). Every object property must be required and `additionalProperties` false;
  the subset allows 100 object properties and 5 levels of nesting. **VERIFIED.**
  https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs
* Reasoning models use `max_completion_tokens` (which includes reasoning tokens) instead of `max_tokens` and may reject
  `temperature`. Sparta's adapter adapts on a structured 400 and remembers (`SPARTA_AZURE_OPENAI_OUTPUT_LIMIT_PARAM`,
  `SPARTA_AZURE_OPENAI_SEND_TEMPERATURE`). Whether the default API version `2024-10-21` accepts `max_completion_tokens` for
  the deployed model is **UNCLEAR** until a live call. **VERIFIED** (reasoning-model behaviour).
  https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning
* `gpt-4.1-mini` is listed for South India (regional or global standard); global deployments can process elsewhere.
  Microsoft Entra authentication is supported. Default content filters can answer 400 or end output with
  `finish_reason="content_filter"`; Hindi and Kannada are not in the classifiers' listed test languages, so evaluate
  safety behaviour explicitly. **VERIFIED.**
  https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability ,
  https://learn.microsoft.com/en-us/azure/foundry/guardrails/default-safety-policies

## 5. Twilio

* **Media Streams.** `<Connect><Stream url="wss://...">` opens a bidirectional WebSocket. Messages from Twilio: `connected`,
  `start` (`streamSid`, `accountSid`, `callSid`, `tracks`, `customParameters`, `mediaFormat` = `audio/x-mulaw`, 8000, 1),
  `media` (`track`, `chunk`, `timestamp`, base64 `payload`), `dtmf`, `mark`, `stop`. To Twilio: `media` (mu-law 8 kHz,
  base64, played in order), `mark` (echoed when the preceding audio has played, or when `clear` discards it), `clear`.
  The `url` cannot carry a query string (use `<Parameter name= value=>`); one bidirectional stream per call; the stream
  ends when the call ends or the server closes the socket. **VERIFIED.**
  https://www.twilio.com/docs/voice/media-streams/websocket-messages ,
  https://www.twilio.com/docs/voice/twiml/stream
* **Request signature.** `X-Twilio-Signature` is the base64 HMAC-SHA1, keyed with the auth token, of the full URL followed
  by the POST parameters sorted by name (each name then value). Documented as also sent with the media WebSocket upgrade;
  which URL form (`wss` or `https`, with or without the port) Twilio signs for it is **UNCLEAR** (Sparta accepts every
  form). Sparta's implementation reproduces the twilio-python test vector (`RSOYDt4T1cUTdK1PDd93/VVr8B8=`).
  https://www.twilio.com/docs/usage/security
* **Call control.** `POST /2010-04-01/Accounts/{AccountSid}/Calls/{CallSid}.json` with `Status=completed` hangs up and with
  `Twiml=<Response>...</Response>` replaces the call's instructions (used for `<Dial>`); HTTP Basic with account SID and
  auth token. **VERIFIED.** https://www.twilio.com/docs/voice/api/call-resource
* **India.** Twilio lists `+91800` toll-free numbers for individuals and businesses with a regulatory bundle and an
  address outside India; inventory and a given applicant's eligibility are **UNCLEAR**, and an ordinary Indian mobile or
  local number was not established. https://www.twilio.com/en-us/guidelines/in/regulatory ,
  https://www.twilio.com/en-us/guidelines/in/voice

## 6. Alternatives considered (not integrated)

| Provider | Indian number | Bidirectional audio | Notes | Source |
| --- | --- | --- | --- | --- |
| Plivo | `+91` landlines for **India-registered businesses** (GST, incorporation or Udyam documents); personal-only eligibility UNCLEAR | `<Stream bidirectional="true">`, base64 `audio/x-mulaw;rate=8000` or L16 at 8 or 16 kHz; `clearAudio`; signature `X-Plivo-Signature-V3` (HMAC-SHA256) | India routing has local media-anchoring requirements | https://www.plivo.com/docs/numbers/rent-india-numbers , https://www.plivo.com/docs/voice-agents/audio-streaming/concepts/audio-streaming-guide |
| Exotel | Indian local, toll-free and mobile numbers with business KYC (identity, registered address, signatory); sole proprietorships documented | Base64 raw PCM16 mono at 8, 16 or 24 kHz; `clear`; WSS auth is Basic or IP allow-list, a webhook signature scheme was not found | Trial: 7 days, whitelisted outbound numbers | https://developer.exotel.com/docs/getting-started/kyc-verification , https://developer.exotel.com/docs/agentstream/websocket-protocol |
| Vonage | `+91` landlines are **inbound-only**, on request, one to two weeks; KYC UNCLEAR | **Binary** PCM16 mono at 8, 16 or 24 kHz; `{"action":"clear"}`; signed JWT webhooks | Trial calls only to the registered number | https://developer.vonage.com/en/voice/voice-api/concepts/websockets |

Twilio was chosen because its Media Streams protocol, request signature and call-control API are fully documented in
English, a US number can be bought on an ordinary paid account to prove the path, and the adapter sits behind the same
`TelephonyProvider` port as every other provider, so an Indian provider can replace it without touching the call
service.

## 7. Dev tunnels

Microsoft dev tunnels provide public HTTPS and WSS endpoints; the tunnel host authenticates unless `--allow-anonymous` is
used, which a webhook from Azure or Twilio needs. The application must still verify provider tokens and signatures.
Microsoft's own ACS sample derives a `wss://` media URL from a dev-tunnel URL. ngrok exposes HTTPS and WebSockets on one
endpoint. **No call through either was tested.** Sparta's `SPARTA_PROVIDER_ONLY_HOSTS` (with an explicit
`SPARTA_TRUSTED_HOSTS`) makes a tunnel host serve only
`/healthz`, `/readyz`, `/api/v1/webhooks/*` and `/api/v1/media/*`.
https://learn.microsoft.com/en-us/azure/developer/dev-tunnels/security , https://ngrok.com/docs/using-ngrok-with/websockets
