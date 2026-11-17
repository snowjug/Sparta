import pytest

from sparta.domain.enums import ResponseStyle
from sparta.domain.models import SpeechPlan
from sparta.language.registry import load_registry
from sparta.orchestrator.planner import PlannerConfig, ReplyPlanner, clean_owner_name
from sparta.orchestrator.validator import OutputValidator
from sparta.providers.tts.ssml import build_ssml, estimate_duration_ms

REG = load_registry()
PLANNER = ReplyPlanner(REG)
LANGS = REG.supported_codes()
KEYS = PLANNER.template_keys()
NAMED = PlannerConfig(owner_name="Atharv")
GENERIC = PlannerConfig(owner_name=None)


@pytest.mark.parametrize("language", LANGS)
@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("cfg", [NAMED, GENERIC], ids=["named-owner", "generic-owner"])
def test_every_template_in_every_language_passes_the_output_validator(language, key, cfg):
    """The closed template set is safe by construction. This proves it, rather than assuming it."""
    plan = PLANNER.render(key, language, cfg)
    verdict = OutputValidator().validate(plan, owner_name=cfg.owner_name, require_ai_disclosure=key == "disclosure")
    assert verdict.ok, f"{language}/{key}: {verdict.violations} :: {plan.text}"
    assert "{" not in plan.text and "}" not in plan.text, "unfilled placeholder"


@pytest.mark.parametrize("language", LANGS)
@pytest.mark.parametrize("style", list(ResponseStyle))
def test_disclosure_always_says_it_is_an_ai_assistant_and_never_the_owner(language, style):
    plan = PLANNER.render("disclosure", language, PlannerConfig(owner_name="Atharv", response_style=style))
    assert "AI" in plan.text
    assert "Atharv" in plan.text  # named as the owner being assisted
    validator = OutputValidator()
    assert not validator._claims_to_be_owner(plan.text, "Atharv")
    assert plan.locale == REG.pack(language).spec.tts_locale


def test_english_disclosure_matches_the_product_wording():
    assert (
        PLANNER.render("disclosure", "en-IN", NAMED).text
        == "Hi, I'm Atharv's AI call assistant. May I know who's calling and what this is regarding?"
    )


def test_hindi_and_kannada_plans_carry_a_latin_transliteration_for_developers():
    hi = PLANNER.render("disclosure", "hi-IN", NAMED)
    kn = PLANNER.render("disclosure", "kn-IN", NAMED)
    assert hi.transliteration and "main" in hi.transliteration
    assert kn.transliteration and "naanu" in kn.transliteration
    assert hi.voice_id == "hi-IN-SwaraNeural" and kn.voice_id == "kn-IN-SapnaNeural"


def test_unknown_language_falls_back_to_english_rather_than_failing():
    plan = PLANNER.render("disclosure", "ta-IN", NAMED)
    assert plan.locale == "en-IN"


def test_custom_voice_and_rate_are_applied():
    cfg = PlannerConfig(owner_name="Atharv", speaking_rate=1.2, voice_ids={"en-IN": "en-IN-PrabhatNeural"})
    plan = PLANNER.render("disclosure", "en-IN", cfg)
    assert plan.voice_id == "en-IN-PrabhatNeural"
    assert plan.rate == 1.2
    assert plan.est_duration_ms < PLANNER.render("disclosure", "en-IN", NAMED).est_duration_ms


def test_english_equivalent_gives_an_exact_translation_of_assistant_lines():
    assert "ending this call" in PLANNER.english_equivalent(["end_scam"], NAMED)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Atharv", "Atharv"),
        ("  Atharv   Shukla ", "Atharv Shukla"),
        ("the owner", None),
        ("", None),
        (None, None),
        ('A{evil}<b>"x"\x00', "Aevilbx"),
    ],
)
def test_owner_name_is_sanitised_before_it_reaches_a_template(raw, expected):
    assert clean_owner_name(raw) == expected


# ------------------------------------------------------------------------------------------------ validator
def plan(text: str) -> SpeechPlan:
    return SpeechPlan(text=text, locale="en-IN")


@pytest.mark.parametrize(
    ("text", "violation"),
    [
        ("Could you tell me the OTP you received?", "asks_for_protected_information"),
        ("Please share your card number and CVV", "asks_for_protected_information"),
        ("OTP bataiye", "asks_for_protected_information"),
        ("Atharv is at home right now", "asks_for_protected_information"),
        ("Call me back on 9876543210", "contains_number"),
        ("Visit www.example.com to continue", "contains_link"),
        ("Hello, this is Atharv speaking", "claims_to_be_owner"),
        ("Who are you? Why are you calling? What do you want?", "multiple_questions"),
        ("word " * 100, "too_long"),
    ],
)
def test_validator_rejects_unsafe_assistant_output(text, violation):
    verdict = OutputValidator().validate(plan(text), owner_name="Atharv")
    assert not verdict.ok
    assert violation in verdict.violations


def test_validator_blocks_leaks_of_planted_owner_facts():
    validator = OutputValidator(owner_markers=["Lake View Road", "Contoso Labs", "Mysuru"])
    assert not validator.validate(plan("He works at Contoso Labs."), owner_name="Atharv").ok
    assert not validator.validate(plan("We are near lake view road"), owner_name="Atharv").ok
    assert validator.validate(plan("I can take a message."), owner_name="Atharv").ok


def test_validator_allows_the_possessive_ai_assistant_form():
    assert (
        OutputValidator()
        .validate(plan("I'm Atharv's AI call assistant."), owner_name="Atharv", require_ai_disclosure=True)
        .ok
    )


def test_validator_demands_ai_disclosure_when_required():
    verdict = OutputValidator().validate(plan("Hello there."), owner_name="Atharv", require_ai_disclosure=True)
    assert "missing_ai_disclosure" in verdict.violations


# --------------------------------------------------------------------------------------------------- SSML
def test_ssml_escapes_markup_and_clamps_rate():
    ssml = build_ssml('a <b> & "c"', "en-IN", "en-IN-NeerjaNeural", rate=5.0)
    assert "&lt;b&gt;" in ssml and "&amp;" in ssml
    assert 'rate="+30%"' in ssml
    assert '<voice name="en-IN-NeerjaNeural">' in ssml and 'xml:lang="en-IN"' in ssml


def test_duration_estimate_is_bounded_and_scales_with_rate():
    assert estimate_duration_ms("hi", "en-IN") == 600
    assert estimate_duration_ms("x" * 10000, "kn-IN") == 20000
    assert estimate_duration_ms("x" * 200, "en-IN", 1.3) < estimate_duration_ms("x" * 200, "en-IN", 0.7)
