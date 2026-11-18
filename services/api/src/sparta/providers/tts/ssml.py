"""Speech synthesis markup helpers (pure functions, no provider calls)."""

from html import escape

_CHARS_PER_SECOND = {"en": 15.0, "hi": 13.0, "kn": 11.5}


def _attr(value: str) -> str:
    """Escape for a double-quoted XML attribute (``&``, ``<``, ``>``, ``"`` and ``'``)."""
    return escape(value, quote=True)


def build_ssml(text: str, locale: str, voice: str | None, rate: float = 1.0, style: str | None = None) -> str:
    """SSML for Azure-style TTS. ``rate`` 1.0 = normal; clamped to the 0.7-1.3 range the profile allows."""
    pct = round((min(max(rate, 0.7), 1.3) - 1.0) * 100)
    body = escape(text, quote=False)
    prosody = f'<prosody rate="{pct:+d}%">{body}</prosody>' if pct else body
    if style and voice:
        prosody = f'<mstts:express-as style="{_attr(style)}">{prosody}</mstts:express-as>'
    inner = f'<voice name="{_attr(voice)}">{prosody}</voice>' if voice else prosody
    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        f'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="{_attr(locale)}">{inner}</speak>'
    )


def estimate_duration_ms(text: str, locale: str, rate: float = 1.0) -> int:
    """Rough speaking time so the simulator and UI can model playback; real providers report the true value."""
    cps = _CHARS_PER_SECOND.get(locale.split("-", maxsplit=1)[0], 13.0) * min(max(rate, 0.7), 1.3)
    return int(min(max(len(text) / cps * 1000, 600), 20000))
