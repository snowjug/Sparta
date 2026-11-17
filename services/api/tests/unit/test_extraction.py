"""Who the caller *claims* to be: names, organisations and purposes in English, Hindi, Hinglish and Kanglish."""

import pytest

from sparta.risk.extraction import extract_claims


@pytest.mark.parametrize(
    ("text", "name", "org"),
    [
        ("Hello, this is Rajesh from State Bank", "Rajesh", "State Bank"),
        ("My name is Suresh from the society office", "Suresh", "Society Office"),
        ("Hi, I'm Rajesh, bank manager from SBI", "Rajesh", "SBI"),
        ("This is an important notice from the Telecom Regulatory Authority", None, "Telecom Regulatory Authority"),
        # An organisation described before the postposition is not a person's name.
        ("Hello, main State Bank ke KYC department se bol raha hoon", None, "State Bank ke KYC department"),
        ("Namaste, main Nova Bank ke card department se Rajesh bol raha hoon", None, "Nova Bank ke card department"),
        ("main Rajesh bol raha hoon", "Rajesh", None),
        ("मैं नोवा बैंक के कार्ड डिपार्टमेंट से राजेश बोल रहा हूँ", None, "नोवा बैंक के कार्ड डिपार्टमेंट"),
        (
            "Hello, nanu Sahyadri Bank customer care inda maatadthidini. Nimma name confirm maadkobahuda?",
            None,
            "Sahyadri Bank customer care",
        ),
        ("Hello, nanu Ramesh maatadthidini", "Ramesh", None),
    ],
)
def test_claimed_name_and_organisation(text, name, org):
    claims = extract_claims(text)
    assert (claims.name, claims.organization) == (name, org)


def test_the_purpose_is_what_the_caller_says_the_call_is_about():
    assert (
        extract_claims("I am calling regarding your parcel delivery today").purpose_phrase
        == "your parcel delivery today"
    )
    assert extract_claims("Hello, nothing to see here").purpose_phrase is None


def test_roles_are_recognised_and_nothing_is_invented_when_no_cue_matches():
    assert extract_claims("I am the branch manager").role == "branch manager"
    empty = extract_claims("ok then")
    assert (empty.name, empty.organization, empty.role, empty.purpose_phrase) == (None, None, None, None)
