"""Billable probes for ``sparta doctor --online --allow-billable``.

They use the same adapters a live call uses, so a pass proves the production request shape, not just a key. Each costs
fractions of a cent: a few synthesized characters and about two seconds of recognition per language, and one short model
turn. Nothing here sends caller data (there is none): the phrases are fixed test sentences.
"""

import httpx

from sparta.config import Settings
from sparta.doctor.checks import OPENAI, SPEECH
from sparta.doctor.model import Check, Status
from sparta.providers.base import ProviderError, SynthesisRequest, TurnEvaluationRequest
from sparta.providers.tts.catalog import DEFAULT_VOICES

# Fixed test sentences ("Hello, this is a test."). They only prove that a locale is recognised and synthesised.
PHRASES: dict[str, str] = {
    "en-IN": "Hello, this is a test of the Sparta call assistant.",
    "hi-IN": "नमस्ते, यह एक परीक्षण है।",
    "kn-IN": "ನಮಸ್ಕಾರ, ಇದು ಒಂದು ಪರೀಕ್ಷೆ.",
}
SAMPLE_RATE = 16000


async def _speech_roundtrip(settings: Settings, http: httpx.AsyncClient) -> list[Check]:
    from sparta.providers.stt.azure import AzureSpeechToText, pcm16_to_wav
    from sparta.providers.tts.azure import AzureTextToSpeech

    tts = AzureTextToSpeech(settings, http=http)
    stt = AzureSpeechToText(settings, http=http)
    out: list[Check] = []
    for locale, phrase in PHRASES.items():
        title = f"Speak and recognise {locale} (round trip)"
        try:
            pcm = b"".join(
                [
                    chunk.data
                    async for chunk in tts.synthesize_stream(
                        SynthesisRequest(
                            text=phrase,
                            locale=locale,
                            voice_id=DEFAULT_VOICES.get(locale),
                            output_format="pcm16_16k",
                            trace_id=f"doctor-{locale}",
                        )
                    )
                    if chunk.data
                ]
            )
            result = await stt.transcribe(
                pcm16_to_wav(pcm, SAMPLE_RATE),
                content_type="audio/wav",
                candidate_locales=[locale],
                locale_hint=locale,
                trace_id=f"doctor-{locale}",
            )
        except ProviderError as exc:
            out.append(
                Check(
                    f"speech.roundtrip.{locale}",
                    SPEECH,
                    title,
                    Status.BLOCKED,
                    f"{exc.stage}: {exc.message}.",
                    "Check the key, the region and that the region offers this locale.",
                )
            )
            continue
        words = len(result.text.split())
        seconds = len(pcm) / (SAMPLE_RATE * 2)
        if words:
            out.append(
                Check(
                    f"speech.roundtrip.{locale}",
                    SPEECH,
                    title,
                    Status.PASS,
                    f"{seconds:.1f} s of speech synthesised and {words} word(s) recognised"
                    + (f" (reported language {result.language})." if result.language else "."),
                )
            )
        else:
            out.append(
                Check(
                    f"speech.roundtrip.{locale}",
                    SPEECH,
                    title,
                    Status.WARNING,
                    f"{seconds:.1f} s of speech was synthesised but nothing was recognised.",
                    "Try another region, or check that recognition supports this locale there.",
                )
            )
    return out


async def _model_probe(settings: Settings, http: httpx.AsyncClient) -> Check:
    from sparta.providers.llm.azure_openai import AzureOpenAIConversationModel

    title = "Deployment answers with schema-valid structured output"
    model = AzureOpenAIConversationModel(settings, http=http)
    try:
        analysis = await model.evaluate_turn(
            TurnEvaluationRequest(
                call_id="doctor",
                caller_text="Hello, I am calling about a parcel for the owner.",
                language="en-IN",
                recent_turns=[],
                known_signals=[],
                trace_id="doctor",
            )
        )
    except ProviderError as exc:
        return Check(
            "openai.probe",
            OPENAI,
            title,
            Status.BLOCKED,
            f"{exc.stage}: {exc.message}.",
            "Check the deployment name, that the model supports structured outputs, and the API version. A reasoning "
            "model needs SPARTA_AZURE_OPENAI_OUTPUT_LIMIT_PARAM=max_completion_tokens.",
        )
    return Check(
        "openai.probe",
        OPENAI,
        title,
        Status.PASS,
        f"one turn evaluated ({analysis.usage.prompt_tokens} prompt and {analysis.usage.completion_tokens} "
        "completion tokens).",
    )


async def run_billable(settings: Settings, *, http: httpx.AsyncClient, timeout_s: float) -> list[Check]:
    del timeout_s  # the adapters apply SPARTA_PROVIDER_TIMEOUT_S themselves
    out: list[Check] = []
    if settings.azure_speech_key and (settings.azure_speech_region or settings.azure_speech_endpoint):
        out.extend(await _speech_roundtrip(settings, http))
    if (
        settings.llm_provider == "azure_openai"
        and settings.azure_openai_endpoint
        and settings.azure_openai_key
        and settings.azure_openai_deployment
    ):
        out.append(await _model_probe(settings, http))
    return out
