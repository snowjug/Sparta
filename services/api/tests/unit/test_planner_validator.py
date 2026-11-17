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
# Real owners have full names, initials and non-Latin names; the first-name-only fixture hid a bug here once.
FULL_NAMES = ["Atharv Shukla", "Atharv K. Shukla", "Meera Krishnamurthy Rao", "अथर्व शुक्ला", "ಅಥರ್ವ ಶುಕ್ಲ"]
FULL_NAME_CONFIGS = [PlannerConfig(owner_name=name) for name in FULL_NAMES]


@pytest.mark.parametrize("language", LANGS)
@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize(
    "cfg",
    [NAMED, GENERIC, *FULL_NAME_CONFIGS],
    ids=["named-owner", "generic-owner", *[f"full-name-{i}" for i in range(len(FULL_NAMES))]],
)
def test_every_template_in_every_language_passes_the_output_validator(language, key, cfg):
    """The closed template set is safe by construction. This proves it, rather than assuming it."""
    plan = PLANNER.render(key, language, cfg)
    verdict = OutputValidator().validate(plan, owner_name=cfg.owner_name, require_ai_disclosure=key == "disclosure")
    assert verdict.ok, f"{language}/{key}: {verdict.violations} :: {plan.text}"
    assert "{" not in plan.text and "}" not in plan.text, "unfilled placeholder"


@pytest.mark.parametrize("language", LANGS)
@pytest.mark.parametrize("style", list(ResponseStyle))
@pytest.mark.parametrize("owner", ["Atharv", *FULL_NAMES])
def test_disclosure_always_says_it_is_an_ai_assistant_and_never_the_owner(language, style, owner):
    plan = PLANNER.render("disclosure", language, PlannerConfig(owner_name=owner, response_style=style))
    assert "AI" in plan.text
    assert owner in plan.text  # named as the owner being assisted
    validator = OutputValidator()
    assert not validator._claims_to_be_owner(plan.text, owner)
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


@pytest.mark.parametrize(
    ("owner", "text"),
    [
        ("Atharv Shukla", "Hi, I'm Atharv Shukla's AI call assistant."),
        ("Atharv Shukla", "Good day. I am Atharv Shukla’s AI call assistant."),
        ("Atharv K. Shukla", "This is Atharv K. Shukla's AI call assistant."),
        ("Meera Krishnamurthy Rao", "Hi, I'm Meera Krishnamurthy Rao's AI call assistant."),
    ],
)
def test_validator_allows_the_possessive_ai_form_with_a_full_name(owner, text):
    verdict = OutputValidator().validate(plan(text), owner_name=owner, require_ai_disclosure=True)
    assert verdict.ok, verdict.violations


@pytest.mark.parametrize(
    ("owner", "text"),
    [
        ("Atharv Shukla", "Hello, this is Atharv Shukla speaking"),
        ("Atharv Shukla", "I'm Atharv Shukla."),
        ("Atharv Shukla", "My name is Atharv Shukla, how can I help?"),
        ("Atharv Shukla", "I am Atharv. Who is calling?"),
        ("Atharv Shukla", "This is Shukla here"),
        ("Atharv K. Shukla", "I'm Atharv K. Shukla and I can help."),
        # The AI form does not excuse a second, real claim in the same sentence.
        ("Atharv Shukla", "I'm Atharv Shukla's AI call assistant, and this is Atharv speaking"),
    ],
)
def test_validator_still_rejects_a_claim_to_be_the_owner_by_full_name(owner, text):
    verdict = OutputValidator().validate(plan(text), owner_name=owner)
    assert "claims_to_be_owner" in verdict.violations


def test_the_claim_check_stays_fast_on_hostile_names_and_long_text():
    """A name with initials such as 'Anil A. A.' once made the full-name loop backtrack exponentially."""
    import time

    check = OutputValidator._claims_to_be_owner
    for owner, text in (
        ("Anil A. A. A.", "Anil " + "a. " * 25),
        ("Anil a. a", "Anil " + "a. " * 100),
        ("Atharv Shukla", "Atharv Shukla " * 200),
        ("Aaa Aaa", "aaa " * 500),
    ):
        started = time.perf_counter()
        check(text, owner)
        assert time.perf_counter() - started < 0.25, (owner, time.perf_counter() - started)


def test_validator_demands_ai_disclosure_when_required():
    verdict = OutputValidator().validate(plan("Hello there."), owner_name="Atharv", require_ai_disclosure=True)
    assert "missing_ai_disclosure" in verdict.violations


# --------------------------------------------------------------------------------------------------- SSML
def test_ssml_escapes_markup_and_clamps_rate():
    ssml = build_ssml('a <b> & "c"', "en-IN", "en-IN-NeerjaNeural", rate=5.0)
    assert "&lt;b&gt;" in ssml and "&amp;" in ssml
    assert 'rate="+30%"' in ssml
    assert '<voice name="en-IN-NeerjaNeural">' in ssml and 'xml:lang="en-IN"' in ssml


def test_ssml_attribute_values_cannot_break_out_of_their_quotes():
    from xml.etree import ElementTree

    locale, voice_name, style = 'en-IN"><evil/>', 'v"><evil/>', "s'\"><evil/>"
    root = ElementTree.fromstring(build_ssml("hello", locale, voice_name, style=style))
    assert all("evil" not in element.tag for element in root.iter())
    assert root.attrib["{http://www.w3.org/XML/1998/namespace}lang"] == locale
    voice = root.find("{http://www.w3.org/2001/10/synthesis}voice")
    assert voice is not None and voice.attrib["name"] == voice_name


def test_duration_estimate_is_bounded_and_scales_with_rate():
    assert estimate_duration_ms("hi", "en-IN") == 600
    assert estimate_duration_ms("x" * 10000, "kn-IN") == 20000
    assert estimate_duration_ms("x" * 200, "en-IN", 1.3) < estimate_duration_ms("x" * 200, "en-IN", 0.7)
