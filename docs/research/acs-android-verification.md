# Provider verification notes: Azure Communication Services and Android call screening

Verified **2026-11-17** against official Microsoft Learn, developer.android.com, AOSP, PyPI and GitHub sources by a research
pass. **UNVERIFIED** marks things the documentation does not settle. No live call was made and no ACS resource exists in
this environment, so nothing here is claimed as tested against a live service.

## Critical constraints

1. **ACS standalone telephony is scheduled to retire on 2028-09-30.** Customers without an ACS resource created before
   2026-10-23 cannot acquire numbers for the retiring PSTN workloads. Call Automation and streaming continue for the
   documented Teams-aligned scenarios.
   Source: <https://learn.microsoft.com/azure/communication-services/acs-retirement-and-breaking-changes-guide>
2. **India (+91) numbers cannot be acquired directly from ACS** (not in the direct-number country catalogue; Microsoft
   staff confirm). Alternatives are Teams Phone Extensibility with Teams Direct Routing/SBC or an approved Operator Connect
   carrier; Operator Connect India has operator licensing/location restrictions. Whether a bot/transfer combination works
   for India is **UNVERIFIED**, and official guidance for conditional forwarding of a user's mobile calls to an
   ACS-hosted number is **UNVERIFIED**.
3. **Android call screening is not an audio bot.** The screening role can allow, silence or reject a call and cannot
   answer it or access/inject call audio.

Sparta consequence: the ACS adapter is implemented and tested against mocked boundaries, but for an Indian owner the
realistic production paths are (a) Teams Phone Extensibility / Operator Connect via a licensed carrier, or (b) an Indian
programmable-voice provider speaking a WebSocket media-stream protocol (Sparta ships a provider-neutral media-stream
interface for this). Both require legal review (see `docs/DEPLOYMENT.md`).

## ACS Call Automation (Python)

* Package `azure-communication-callautomation` **1.6.1** (`py3-none-any`; Python ≥ 3.9, 3.12/3.13 fine). 1.6.0 is
  deprecated (recording-URL security issue).
* **Bidirectional streaming is GA** (added in 1.4.0); default REST API `2026-03-12`.
* `answer_call(incoming_call_context, callback_url, *, cognitive_services_endpoint=None, operation_context=None,
  media_streaming=None, transcription=None)` → `CallConnectionProperties`.
* `MediaStreamingOptions(transport_url, transport_type=StreamingTransportType.WEBSOCKET,
  content_type=MediaStreamingContentType.AUDIO, audio_channel_type=MIXED|UNMIXED, start_media_streaming=True,
  enable_bidirectional=True, enable_dtmf_tones=True, audio_format=PCM16_K_MONO|PCM24_K_MONO)`.
* WebSocket, ACS → server: `{"kind":"AudioMetadata","audioMetadata":{subscriptionId,encoding,sampleRate,channels,length}}`
  then `{"kind":"AudioData","audioData":{timestamp,participantRawID,data(base64),silent}}`; optional
  `{"kind":"DtmfData","dtmfData":{"data":"3"}}`. 20 ms PCM frames = 640 B @ 16 kHz, 960 B @ 24 kHz.
* Server → ACS (documented Python casing): `{"Kind":"AudioData","AudioData":{"Data":"<base64>"},"StopAudio":null}`; to clear
  queued outbound audio for **barge-in**: `{"Kind":"StopAudio","AudioData":null,"StopAudio":{}}` (this is not
  `stop_media_streaming()`). The JS serializer emits lowercase keys: wire casing must be confirmed in an integration test.
* `IncomingCall` arrives via Event Grid (`Microsoft.Communication.IncomingCall`): `incomingCallContext`, `from`, `to`,
  `callerDisplayName`, `serverCallId`, `correlationId`. Answer within the ~30 s ring window; deliveries can be duplicated.
* Event Grid schema subscription validation: handle `Microsoft.EventGrid.SubscriptionValidationEvent` and return 200 with
  `{"validationResponse": "<validationCode>"}`. The handshake does **not** authenticate later events: use Entra-secured
  webhook delivery (app role `AzureEventGridSecureWebhookSubscriber`) and validate the bearer token.
* **Call Automation callbacks are authenticated by JWT**: `Authorization: Bearer`, RS256, issuer
  `https://acscallautomation.communication.azure.com`, JWKS `https://acscallautomation.communication.azure.com/calling/keys`,
  audience = the ACS resource id (exact representation **UNVERIFIED**), 5-minute lifetime. WebSocket connection JWTs last 24 h.
  The discovery document advertises `RSA256` while the sample says `RS256`: confirm in an integration test.
* Operations: `play_media` (`TextSource`/`SsmlSource`/`FileSource`; TTS needs an attached Cognitive Services resource),
  `start_recognizing_media` (DTMF), `transfer_call_to_participant`, `hang_up(is_for_everyone)`,
  `start_media_streaming`/`stop_media_streaming`. Events: `CallConnected`, `AnswerFailed`, `PlayCompleted`, `PlayFailed`,
  `PlayCanceled`, `RecognizeCompleted/Failed/Canceled`, `CallTransferAccepted/Failed`, `CallDisconnected`,
  `MediaStreamingStarted/Stopped/Failed`.

## Android call screening

* `CallScreeningService` since API 24; from API 29 request `RoleManager.ROLE_CALL_SCREENING` via
  `createRequestRoleIntent()`; the app need not be the default dialer. Manifest: service with
  `android:permission="android.permission.BIND_SCREENING_SERVICE"`, intent action `android.telecom.CallScreeningService`,
  `android:exported="true"`. **Respond within 5 seconds** with `respondToCall()`.
* `CallResponse.Builder`: `setDisallowCall`, `setRejectCall`, `setSkipCallLog`, `setSkipNotification` (API 24);
  `setSilenceCall` (API 29). Rejection/skip flags require a disallowed call. `setSkipCallLog` is ignored for ordinary
  third-party screeners (blocked calls are logged).
* `Call.Details` exposes handle, direction (API 29), STIR/SHAKEN verification status (API 30), creation/connection time.
  Only `tel:` calls; restricted/unknown presentations are excluded; contact lookups need `READ_CONTACTS`.
* No call audio access or injection for the screening role (`CAPTURE_AUDIO_OUTPUT` / `CALL_AUDIO_INTERCEPTION` are
  privileged).
* Behavior: Android 13+ `POST_NOTIFICATIONS` runtime permission; 14+ foreground-service types and full-screen-intent
  limits (`canUseFullScreenIntent()`); `phoneCall` foreground service needs `FOREGROUND_SERVICE_PHONE_CALL` plus
  `MANAGE_OWN_CALLS`/`ROLE_DIALER` (screening alone does not qualify). Screening on API 29+ needs no `READ_CALL_LOG`.
  Play restricts call-log permissions.

## Toolchain (latest stable at verification time)

AGP 9.5.1, Gradle 9.9.1, Kotlin 2.4.21, KSP 2.3.14, Hilt 2.60.1, Room 2.8.5, Navigation Compose 2.10.2, Compose BOM
2026.09.00, Material3 1.4.0. Kotlin 2.4.21's documented fully-supported maxima are AGP 9.3.1 / Gradle 9.7.0, so the
**conservative tuple is AGP 9.3.1 + Gradle 9.5.0 + Kotlin 2.4.21**, confirmed by an actual build. Stable Android is 17
(API 37); Google Play requires new apps/updates to target ≥ API 36. AGP 9.5 needs JDK 17 and Gradle ≥ 9.6.0.
Windows command-line tools: `https://dl.google.com/android/repository/commandlinetools-win-16111833_latest.zip`;
SDK ids `platforms;android-37.0`, `build-tools;37.0.0` (AGP default build tools 36.0.0). `sdkmanager` is flagged
deprecated in favor of `android sdk`.
