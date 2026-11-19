import pytest

from sparta.services.numbers import dial_number


@pytest.mark.parametrize(
    ("raw", "dialled"),
    [
        ("+919812345670", "+919812345670"),
        ("+91 98123 45670", "+919812345670"),
        ("+91 (98123) 45-670", "+919812345670"),
        ("+91.98123.45670", "+919812345670"),
        ("  +1 415 555 0100 ", "+14155550100"),
        ("0091 98123 45670", "+919812345670"),  # 00 is the international prefix
        ("00 1 415 555 0100", "+14155550100"),
    ],
)
def test_a_number_with_its_country_code_is_dialled_in_strict_e164(raw, dialled):
    assert dial_number(raw) == dialled


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "98123 45670",  # no country code: never completed with a guess
        "098123 45670",
        "+0 98123 45670",  # a country code never starts with 0
        "+91 981",  # too short
        "+91 98123 45670 12345 6789",  # too long
        "+91 98123 456x0",
        "tel:+919812345670",
        "+91;ext=5",
    ],
)
def test_anything_that_is_not_an_international_number_is_not_dialled(raw):
    assert dial_number(raw) is None
