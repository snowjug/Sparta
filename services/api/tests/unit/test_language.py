import pytest

from sparta.language.detector import LanguageDetector, get_detector
from sparta.language.registry import PackError, PackRegistry, _load_pack, load_registry


def test_registry_lists_supported_and_planned_languages():
    reg = load_registry()
    assert reg.supported_codes() == ["en-IN", "hi-IN", "kn-IN"]
    planned = {s.code for s in reg.specs() if s.status == "planned"}
    assert {"mr-IN", "ta-IN", "te-IN", "ml-IN", "bn-IN"} <= planned


def test_supported_languages_have_a_voice_and_templates_for_every_reply_key():
    reg = load_registry()
    english_keys = set(reg.pack("en-IN").templates)
    for spec in reg.supported():
        pack = reg.pack(spec.code)
        assert spec.default_voice, spec.code
        assert english_keys <= set(pack.templates), f"{spec.code} lacks {english_keys - set(pack.templates)}"
        assert set(pack.owner_ref) == {"named", "generic"}


def test_adding_a_language_needs_only_a_pack_not_new_rule_code():
    raw = {
        "version": "1",
        "meta": {
            "code": "xx-IN",
            "iso": "xx",
            "name": "Test",
            "native_name": "Test",
            "scripts": ["Latn"],
            "status": "supported",
        },
        "terms": {"otp": [r"\bxyzzy otp\b"]},
        "cues": {"request": [r"\bgimme\b"]},
    }
    pack = _load_pack(raw, "inline")
    merged = PackRegistry([*load_registry().packs(), pack])
    assert r"\bxyzzy otp\b" in merged.terms["otp"]
    assert "xx-IN" in merged.supported_codes()


def test_bad_pattern_fails_at_load_time_not_mid_call():
    raw = {
        "meta": {
            "code": "xx-IN",
            "iso": "xx",
            "name": "T",
            "native_name": "T",
            "scripts": ["Latn"],
            "status": "supported",
        },
        "terms": {"otp": ["(unclosed"]},
    }
    with pytest.raises(PackError):
        _load_pack(raw, "inline")


@pytest.mark.parametrize(
    ("text", "language", "profile"),
    [
        ("Hello, this is Rahul from State Bank. Am I speaking with the owner?", "en-IN", "english"),
        ("आपका खाता बंद हो जाएगा, अभी ओटीपी बताइए", "hi-IN", "hindi"),
        ("Aapka account block ho jayega, abhi OTP bataiye", "hi-IN", "hinglish"),
        ("ನಿಮ್ಮ ಖಾತೆ ಬ್ಲಾಕ್ ಆಗಿದೆ, ಒಟಿಪಿ ಹೇಳಿ", "kn-IN", "kannada"),
        ("nimma account block aagide, OTP heli", "kn-IN", "kanglish"),
        ("நீங்கள் யார் பேசுகிறீர்கள்", "ta-IN", "unsupported"),
        ("आम्ही तुमचा खाते बंद करत आहोत, तुम्ही माहिती द्या", "mr-IN", "unsupported"),
    ],
)
def test_detects_language_and_profile(text, language, profile):
    det = get_detector().detect(text)
    assert det.language == language
    assert det.profile == profile
    assert det.supported is (profile != "unsupported")


def test_digits_only_text_is_unknown_not_guessed():
    det = get_detector().detect("12345")
    assert det.language == "und"
    assert det.uncertain


def test_code_switched_text_is_segmented_per_language():
    det = get_detector().detect("ನಮಸ್ಕಾರ sir, naanu delivery boy, gate hattira iddini")
    langs = [seg.language for seg in det.segments]
    assert "kn-IN" in langs and "en-IN" in langs
    assert any(seg.variant == "kanglish" for seg in det.segments)
    assert det.is_code_switched


def test_forced_language_wins_over_text_evidence():
    det = get_detector().detect("Hello how are you", forced="kn-IN")
    assert det.language == "kn-IN"
    assert det.confidence == 1.0


def test_provider_hint_fills_in_when_text_is_ambiguous_but_never_overrides_strong_evidence():
    detector = get_detector()
    weak = detector.detect("ok ok", hint="hi-IN", hint_confidence=0.9)
    assert weak.language == "hi-IN"
    strong = detector.detect("Please tell me what this call is regarding sir", hint="kn-IN", hint_confidence=0.9)
    assert strong.language == "en-IN"
    assert strong.hint_conflict


def test_detector_is_deterministic():
    detector = LanguageDetector()
    text = "Sir main delivery boy hoon, building nahi mil rahi"
    first = detector.detect(text)
    assert detector.detect(text) == first
