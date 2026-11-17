"""Heuristic extraction of who the caller *claims* to be and why they say they are calling.

Everything returned is an unverified claim and is presented as such. Extraction never invents: if no cue matches, the
field stays ``None`` and the assistant asks (at most twice per field).
"""

import re
from dataclasses import dataclass

from sparta.language.text import tokenize

_NAME_STOP = {
    "from",
    "calling",
    "here",
    "speaking",
    "regarding",
    "about",
    "with",
    "at",
    "of",
    "and",
    "the",
    "a",
    "an",
    "i",
    "am",
    "sir",
    "madam",
    "mam",
    "ma'am",
    "this",
    "is",
    "your",
    "you",
    "we",
    "bank",
    "department",
    "company",
    "team",
    "for",
    "to",
    "in",
    "on",
    "bol",
    "baat",
    "se",
    "ka",
    "ki",
    "ke",
    "hai",
    "hoon",
    "hun",
    "hu",
    "raha",
    "rahi",
    "inda",
    "yinda",
    "ninda",
    "matadtidini",
    "maatadtidini",
    "maatanaadtidini",
    "naanu",
    "main",
    "mai",
    "mera",
    "meri",
    "naam",
    "name",
    "nanna",
    "hesaru",
    "call",
    "phone",
    "ji",
    "namaste",
    "namaskara",
    "hello",
    "hi",
    "hey",
    "good",
    "morning",
    "afternoon",
    "evening",
    "please",
    "yes",
    "no",
    "ok",
    "okay",
    "kya",
    "aap",
    "aapka",
    "nimma",
    "neevu",
    "delivery",
    "courier",
    "customer",
    "care",
    "support",
    "service",
    "executive",
    "manager",
    "officer",
    "agent",
    "recruiter",
    "inspector",
    "doctor",
    "nurse",
    "boy",
    "partner",
}
_ORG_STOP = {
    "regarding",
    "about",
    "for",
    "to",
    "and",
    "calling",
    "speaking",
    "sir",
    "madam",
    "mam",
    "here",
    "concerning",
    "because",
    "as",
    "i",
    "we",
    "your",
    "you",
    "my",
    "our",
    "the",
    "that",
    "which",
    "who",
    "bol",
    "baat",
    "call",
    "phone",
    "hoon",
    "hun",
    "hu",
    "raha",
    "rahi",
    "inda",
    "yinda",
    "ninda",
    "regarding.",
    "so",
    "but",
    "is",
    "are",
    "was",
    "will",
    "can",
    "could",
    "may",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "ke",
    "ki",
    "ka",
    "ko",
    "se",
    "main",
    "mai",
    "naanu",
    "mattu",
    "aur",
    "hai",
}
_ROLES = (
    r"(?:customer\s+care\s+executive|customer\s+support\s+executive|relationship\s+manager|branch\s+manager|"
    r"delivery\s+(?:boy|partner|executive|agent|person)|sub[\s-]?inspector|inspector|officer|manager|executive|"
    r"representative|agent|recruiter|doctor|nurse|technician|engineer|teacher|principal|receptionist|"
    r"hr\s+(?:manager|executive)|assistant)"
)
_ROLE_RE = re.compile(rf"\b(?P<role>{_ROLES})\b", re.IGNORECASE)

_NAME_CUES = [
    re.compile(
        r"\b(?:my\s+name\s+is|myself|name\s+is|you\s+are\s+speaking\s+with|speaking\s+with)\s+(?P<rest>.+)",
        re.I,
    ),
    re.compile(r"\b(?:this\s+is|i\s*am|i['’]m|it['’]s)\s+(?P<rest>.+)", re.I),
    re.compile(r"\b(?:mera\s+naam|mera\s+name|meraa\s+naam)\s+(?P<rest>.+)", re.I),
    re.compile(r"\b(?:main|mai|mein)\s+(?P<rest>[^,.]+?)\s+(?:bol|baat)\s+(?:kar\s+)?(?:raha|rahi|rahe)\b", re.I),
    re.compile(r"\b(?:nanna\s+hesaru|nan\s+hesaru)\s+(?P<rest>.+)", re.I),
    re.compile(r"\bnaanu\s+(?P<rest>[^,.]+?)\s+(?:inda|yinda|ninda|maat|matad|maatad|call|mathad)", re.I),
    re.compile(r"मेरा\s+नाम\s+(?P<rest>.+)"),
    re.compile(r"मैं\s+(?P<rest>[^,।.]+?)\s+(?:बोल|बात)\s+(?:कर\s+)?(?:रहा|रही|रहे)"),
    re.compile(r"ನನ್ನ\s+ಹೆಸರು\s+(?P<rest>.+)"),
    re.compile(r"ನಾನು\s+(?P<rest>[^,.]+?)\s+(?:ಇಂದ|ಯಿಂದ|ಮಾತನಾಡ)"),
]
_NAME_HERE = re.compile(r"(?P<rest>[A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+)?)\s+here\b")

_ORG_PATTERNS = [
    re.compile(r"\b(?:calling|speaking|call(?:ing)?\s+you|phoning|messaging)\s+from\s+(?P<rest>.+)", re.I),
    re.compile(r"\b(?:i\s*(?:am|['’]m)|this\s+is)\b[^.]{0,40}?\b(?:from|with|at)\s+(?P<rest>.+)", re.I),
    re.compile(r"\bfrom\s+(?P<rest>.+)", re.I),
    re.compile(r"\bon\s+behalf\s+of\s+(?P<rest>.+)", re.I),
    re.compile(r"\bwork(?:ing)?\s+(?:for|at|with)\s+(?P<rest>.+)", re.I),
    re.compile(r"\b(?P<rest>[^,.]+?)\s+(?:se|ki\s+taraf\s+se|ke\s+taraf\s+se)\s+(?:bol|baat|call|phone)", re.I),
    re.compile(r"\b(?P<rest>[^,.]+?)\s+(?:inda|yinda|ninda)\s+(?:maat|matad|maatad|call|mathad|baruttiddene)", re.I),
    re.compile(r"(?P<rest>[^,।.]+?)\s+(?:से|की\s+तरफ\s+से|के\s+तरफ\s+से)\s+(?:बोल|बात|कॉल)"),
    re.compile(r"(?P<rest>[^,.]+?)\s+(?:ಇಂದ|ಯಿಂದ)\s+(?:ಮಾತನಾಡ|ಕರೆ|ಕಾಲ್)"),
]

_PURPOSE_PATTERNS = [
    re.compile(
        r"\b(?:regarding|concerning|about|reason\s+(?:for|of)\s+(?:my|the)\s+call\s+is|calling\s+(?:to|for)|call\s+is\s+about)\s+(?P<rest>[^.,;?!]+)",
        re.I,
    ),
    re.compile(r"\b(?P<rest>[^.,;?!]+?)\s+(?:ke\s+baare\s+(?:mein|me)|ke\s+sambandh\s+mein|ke\s+bare\s+me)\b", re.I),
    re.compile(r"\b(?P<rest>[^.,;?!]+?)\s+(?:bagge|vishayavaagi)\s+(?:call|maatad|heli)", re.I),
]


@dataclass
class ExtractedClaims:
    name: str | None = None
    organization: str | None = None
    role: str | None = None
    purpose_phrase: str | None = None

    def merged_into(
        self, name: str | None, org: str | None, role: str | None
    ) -> tuple[str | None, str | None, str | None]:
        return name or self.name, org or self.organization, role or self.role


def _clean_tokens(rest: str, stop: set[str], max_tokens: int, allow_digits: bool = False) -> str | None:
    out: list[str] = []
    for token, _, _ in tokenize(rest):
        low = token.lower().strip("'’.")
        if low in stop:
            break
        if not allow_digits and any(ch.isdigit() for ch in token):
            break
        out.append(token)
        if len(out) >= max_tokens:
            break
    if not out:
        return None
    text = " ".join(out)
    return text.title() if text.islower() and text.isascii() else text


def _titlecase_org(text: str) -> str:
    return text if any(ch.isupper() for ch in text) or not text.isascii() else text.title()


def extract_claims(text: str) -> ExtractedClaims:
    claims = ExtractedClaims()
    for pattern in _NAME_CUES:
        m = pattern.search(text)
        if not m:
            continue
        rest = m.group("rest")
        name = _clean_tokens(rest, _NAME_STOP, 3)
        if name and len(name) >= 2:
            claims.name = name
            break
    if claims.name is None:
        m = _NAME_HERE.search(text)
        if m:
            claims.name = _clean_tokens(m.group("rest"), _NAME_STOP, 2)

    for pattern in _ORG_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        rest = m.group("rest")
        if pattern.pattern.startswith(r"\b(?P<rest>[^,.]+?)") or "से" in pattern.pattern or "ಇಂದ" in pattern.pattern:
            tokens = [t for t, _, _ in tokenize(rest)]
            candidate = _clean_tokens(" ".join(tokens[-4:]), _ORG_STOP, 4, allow_digits=True)
        else:
            candidate = _clean_tokens(rest, _ORG_STOP, 4, allow_digits=True)
        if candidate and candidate.lower() not in {"the", "a", "an", "here"}:
            claims.organization = _titlecase_org(candidate)
            break

    role = _ROLE_RE.search(text)
    if role:
        claims.role = role.group("role").lower()

    for pattern in _PURPOSE_PATTERNS:
        m = pattern.search(text)
        if m:
            phrase = " ".join(m.group("rest").split()[:8]).strip(" -")
            if len(phrase) >= 3:
                claims.purpose_phrase = phrase[:80]
                break
    return claims
