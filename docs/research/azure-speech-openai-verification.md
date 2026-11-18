# Provider verification notes: Azure AI Speech and Azure OpenAI

Verified **2026-11-17** against official Microsoft Learn documentation, PyPI and the Azure REST API specs by a research
pass. Items the documentation does not settle are marked **UNVERIFIED**. No live SDK call was made (no credentials), so
nothing here is claimed as tested against a live service. Sparta code that depends on a fact below cites this file.

## Locale support (en-IN, hi-IN, kn-IN)

| Locale | Real-time STT | Fast Transcription | TTS |
| --- | --- | --- | --- |
| `en-IN` | yes | yes | yes |
| `hi-IN` | yes | yes | yes |
| `kn-IN` | yes | yes | yes |

Source: <https://learn.microsoft.com/azure/ai-services/speech-service/language-support>

## Predefined neural voices used by Sparta

| Locale | Female | Male |
| --- | --- | --- |
| `en-IN` | `en-IN-NeerjaNeural` (styles: cheerful, empathetic, newscast), `en-IN-AartiNeural`, `en-IN-AnanyaNeural` | `en-IN-PrabhatNeural`, `en-IN-KunalNeural`, `en-IN-ArjunNeural` |
| `hi-IN` | `hi-IN-SwaraNeural` (styles: cheerful, empathetic, newscast), `hi-IN-AnanyaNeural`, `hi-IN-AartiNeural` | `hi-IN-MadhurNeural`, `hi-IN-AaravNeural`, `hi-IN-KunalNeural` |
| `kn-IN` | `kn-IN-SapnaNeural` | `kn-IN-GaganNeural` |

* `kn-IN` voices do not support phonemes, custom lexicons or visemes.
* Multilingual voices (`en-US-AvaMultilingualNeural`, `en-US-EmmaMultilingualNeural`, `en-US-AndrewMultilingualNeural`,
  `en-US-BrianMultilingualNeural`) list `en-IN`, `hi-IN` and `kn-IN` among their SSML locales and support
  `<lang xml:lang="…">` switching inside one utterance; non-multilingual voices do not.
* Preview/HD families (Dragon HD, MAI Voice 2/2.1) exist but are preview and are not used by default.

## Language identification and code-switching

* SDK at-start LID: ≤ 4 candidate locales. Continuous LID: ≤ 10, requires continuous recognition. All three locales are
  supported.
* Continuous LID **does not detect language changes inside one sentence**; documented intra-sentence Hinglish/Kanglish
  accuracy is **UNVERIFIED**. This is why Sparta's own text-level detector does per-token segmentation and why safety
  rules run on every language regardless of the detected one.
* `MAI-Transcribe-2` documents mid-utterance Hinglish (`en`, `hi`, `kn`); Kannada/English mid-utterance quality is
  **UNVERIFIED**. Preview in Voice Live.

## REST specifics

* **Fast Transcription** (used for uploaded audio): `POST https://{resource}.cognitiveservices.azure.com/speechtotext/transcriptions:transcribe?api-version=2025-10-15`;
  multipart `audio` + JSON `definition` (`locales`, `diarization`, `channels`, `profanityFilterMode`, …); response
  `combinedPhrases[].text`, `phrases[].{locale,confidence,offsetMilliseconds,durationMilliseconds,text}`. Auth:
  `Ocp-Apim-Subscription-Key` or Entra bearer. Size/duration limit documented inconsistently (500 MB/5 h vs 250 MB/2 h):
  Sparta enforces far lower limits itself (8 MB, 120 s).
* **Short audio STT**: `POST https://{resource}.cognitiveservices.azure.com/stt/speech/recognition/conversation/cognitiveservices/v1?language=hi-IN&format=detailed`,
  `Content-Type: audio/wav; codecs=audio/pcm; samplerate=16000`, ≤ 60 s. `RecognitionStatus`, `DisplayText`, `NBest[]`
  (`Confidence`, `Lexical`, `ITN`, `Display`); offsets in 100-ns units. No language identification on this endpoint.
* **TTS**: `POST https://{region}.tts.speech.microsoft.com/cognitiveservices/v1`; headers `Ocp-Apim-Subscription-Key`,
  `Content-Type: application/ssml+xml`, `X-Microsoft-OutputFormat`, `User-Agent`. Telephony-suitable outputs:
  `raw-8khz-16bit-mono-pcm`, `raw-16khz-16bit-mono-pcm`, `raw-8khz-8bit-mono-mulaw`, `raw-8khz-8bit-mono-alaw`.
  Chunked transfer streaming is **UNVERIFIED**.

## Speech SDK for Python

`azure-cognitiveservices-speech` 1.53.1, `py3-none` platform wheels (Windows/Linux/macOS, x64/ARM64). Python 3.14/3.15
compatibility **UNVERIFIED**. Sparta's Azure speech adapters use REST through `httpx`, so the SDK is not required.

## Personal Voice

* Limited Access: registration and Microsoft approval required; explicit consent plus a recorded verbal consent
  statement from the same speaker; clean 5–90 s sample; synthetic-voice disclosure required.
* Locales: `en-IN` and `hi-IN` listed; **`kn-IN` not listed (UNVERIFIED/unsupported)**.
* Regions: eastasia, eastus, eastus2, southeastasia, swedencentral, westeurope, westus2; **not listed for centralindia**.
* REST `api-version=2026-01-01`: `PUT /customvoice/projects/{id}` (`kind: PersonalVoice`), `/customvoice/consents/{id}`,
  `/customvoice/personalvoices/{id}`; SSML uses the returned `speakerProfileId`.

## Azure OpenAI

* Structured outputs: `response_format: {"type": "json_schema", "json_schema": {…, "strict": true}}` with all fields
  required and `additionalProperties: false`. Supported since `2024-08-01-preview`; GA `2024-10-21` and `v1`.
* Dated endpoint: `POST https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21`.
  v1: `POST https://{resource}.openai.azure.com/openai/v1/chat/completions` (deployment in body `model`). Auth: `api-key`
  header or Entra `Authorization: Bearer`.
* Prompt Shields (user-prompt attack/jailbreak detection) is on by default; results in
  `prompt_filter_results[].content_filter_results.jailbreak`; blocked prompts may return HTTP 400 `content_filter`.
  Mostly trained/evaluated on English: effectiveness on Hindi/Kannada must be evaluated, so Sparta never relies on it.
* Usage fields: `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`.
* Model lifecycle: check the retirement schedule before choosing a deployment (several o-series versions retire
  2026-11-19).

## Consequences for Sparta

1. Default predefined voices: `en-IN-NeerjaNeural`, `hi-IN-SwaraNeural`, `kn-IN-SapnaNeural` (all verified in docs).
2. Hindi/Kannada replies are sent as native-script SSML to the matching locale voice. Code-mixed English words inside
   them are left to the voice; per-word `<lang>` switching needs a multilingual voice and is not enabled by default.
3. Personal Voice: `en-IN`/`hi-IN` only, approval required, region-limited → Sparta ships the consent/enrollment flow with a
   predefined-voice fallback and treats Kannada personal voice as unsupported.
4. Deterministic text-level detector for per-segment language; provider language ID is only used as a hint.
