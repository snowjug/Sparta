import asyncio

import pytest

from sparta.language.text import canon_latin, compile_pattern, mask_digits, normalize, tokenize, trim_excerpt


def test_normalize_converts_indic_digits_and_strips_zero_width():
    assert normalize("ओटीपी १२३४५६") == "ओटीपी 123456"
    assert normalize("ಒಟಿಪಿ ೧೨೩೪") == "ಒಟಿಪಿ 1234"
    assert normalize("O\u200bT\u200cP") == "otp"


def test_normalize_does_not_collapse_digit_runs():
    assert "1000" in normalize("pay 1000 rupees")
    assert normalize("pleeeease") == "pleease"


def test_normalize_handles_curly_apostrophes_and_nukta():
    assert normalize("Don’t share") == "don't share"
    assert normalize("ज़रूर") == normalize("जरूर")


def test_normalize_can_keep_case_for_readable_excerpts():
    assert normalize("Hello SBI Bank", lowercase=False) == "Hello SBI Bank"


@pytest.mark.parametrize(
    ("variant", "canonical"),
    [("kyaa", "kya"), ("aapka", "apka"), ("hoon", "hun"), ("beeku", "biku"), ("wo", "vo")],
)
def test_canon_latin_collapses_romanization_variants(variant, canonical):
    assert canon_latin(variant) == canon_latin(canonical)


def test_tokenize_keeps_indic_combining_marks_and_apostrophes():
    tokens = [t for t, _, _ in tokenize("आपका don't ನಿಮ್ಮ account")]
    assert tokens == ["आपका", "don't", "ನಿಮ್ಮ", "account"]


@pytest.mark.parametrize(
    ("pattern", "text", "expected"),
    [
        (r"\bओटीपी\b", "आपका ओटीपी बताइए", True),
        (r"\bओटीपी\b", "आपकाओटीपीबताइए", False),
        (r"\bಒಟಿಪಿ\b", "ನಿಮ್ಮ ಒಟಿಪಿ ಹೇಳಿ", True),
        (r"\bot[a-z]*\b", "otp now", True),
        (r"\bpin\b", "pinned", False),
    ],
)
def test_compile_pattern_has_indic_aware_word_boundaries(pattern, text, expected):
    assert bool(compile_pattern(pattern).search(text)) is expected


def test_mask_digits_hides_codes_in_excerpts():
    assert "482913" not in mask_digits("my code is 482913 ok")
    assert "12" in mask_digits("12 apples")  # short numbers are not credentials
    assert "482913" not in trim_excerpt("the otp is 482913 please", 4, 7)


@pytest.mark.asyncio
async def test_virtual_clock_wakes_sleepers_in_deadline_order(clock):
    order: list[str] = []

    async def sleeper(name: str, seconds: float) -> None:
        await clock.sleep(seconds)
        order.append(name)

    tasks = [asyncio.create_task(sleeper("late", 10)), asyncio.create_task(sleeper("early", 3))]
    await asyncio.sleep(0)
    await clock.advance(5)
    assert order == ["early"]
    await clock.advance(5)
    assert order == ["early", "late"]
    assert clock.monotonic() == pytest.approx(10)
    await asyncio.gather(*tasks)
