"""Predefined voice catalog.

Voice names come from the verified Azure AI Speech documentation
(see ``docs/research/azure-speech-openai-verification.md``).
``verified`` is true only for names confirmed there. The simulator lists the same voices so the Assistant Studio behaves
identically in development, but it cannot actually synthesise them: audio only exists when Azure Speech is configured.
"""

from typing import Literal

from sparta.domain.models import VoiceOption

PROVIDER = "azure-speech"


def _v(
    voice: str, locale: str, name: str, gender: Literal["female", "male", "neutral"], note: str | None = None
) -> VoiceOption:
    return VoiceOption(
        id=voice,
        locale=locale,
        display_name=name,
        gender=gender,
        provider=PROVIDER,
        verified=True,
        note=note,
    )


VOICE_CATALOG: list[VoiceOption] = [
    _v("en-IN-NeerjaNeural", "en-IN", "Neerja", "female", "Warm and clear. Default for English."),
    _v("en-IN-AartiNeural", "en-IN", "Aarti", "female"),
    _v("en-IN-AnanyaNeural", "en-IN", "Ananya", "female"),
    _v("en-IN-PrabhatNeural", "en-IN", "Prabhat", "male"),
    _v("en-IN-KunalNeural", "en-IN", "Kunal", "male"),
    _v("en-IN-ArjunNeural", "en-IN", "Arjun", "male"),
    _v("hi-IN-SwaraNeural", "hi-IN", "Swara", "female", "Natural Hindi. Default for Hindi and Hinglish."),
    _v("hi-IN-AnanyaNeural", "hi-IN", "Ananya", "female"),
    _v("hi-IN-AartiNeural", "hi-IN", "Aarti", "female"),
    _v("hi-IN-MadhurNeural", "hi-IN", "Madhur", "male"),
    _v("hi-IN-AaravNeural", "hi-IN", "Aarav", "male"),
    _v("hi-IN-KunalNeural", "hi-IN", "Kunal", "male"),
    _v("kn-IN-SapnaNeural", "kn-IN", "Sapna", "female", "Default for Kannada and Kanglish."),
    _v("kn-IN-GaganNeural", "kn-IN", "Gagan", "male"),
]

DEFAULT_VOICES: dict[str, str] = {
    "en-IN": "en-IN-NeerjaNeural",
    "hi-IN": "hi-IN-SwaraNeural",
    "kn-IN": "kn-IN-SapnaNeural",
}


def voices_for(locale: str | None = None) -> list[VoiceOption]:
    return [v for v in VOICE_CATALOG if locale is None or v.locale == locale]


def is_known_voice(voice_id: str, locale: str) -> bool:
    return any(v.id == voice_id and v.locale == locale for v in VOICE_CATALOG)
