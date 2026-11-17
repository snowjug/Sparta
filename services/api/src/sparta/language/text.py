"""Unicode text utilities shared by language detection and the risk engine.

Python's ``\\w`` / ``\\b`` do not treat Indic combining marks (vowel signs, viramas) as word characters, which silently
breaks matching on Hindi and Kannada. ``compile_pattern`` rewrites ``\\w``, ``\\W`` and ``\\b`` so authors can write
ordinary regular expressions that behave correctly for every supported script.
"""

import re
import unicodedata
from functools import lru_cache

# Word characters: ASCII/Unicode alphanumerics plus the Indic blocks (letters *and* combining marks).
_INDIC_RANGE = "\u0900-\u0dff"
_WORD_CLASS_BODY = rf"\w{_INDIC_RANGE}"

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
_INDIC_DIGITS: dict[int, int] = {}
for _base in (
    0x0966,
    0x09E6,
    0x0A66,
    0x0AE6,
    0x0B66,
    0x0BE6,
    0x0C66,
    0x0CE6,
    0x0D66,
):  # Devanagari … Malayalam
    for _i in range(10):
        _INDIC_DIGITS[_base + _i] = ord("0") + _i

_PUNCT_TO_SPACE = re.compile(r"[,;!?\"“”()\[\]{}|<>«»*_=~^`\\।॥…]+")
_MULTISPACE = re.compile(r"\s+")
_REPEAT = re.compile(r"(?!\d)(.)\1{2,}")  # never collapse digits: "1000" must stay "1000"


def normalize(text: str, lowercase: bool = True) -> str:
    """Canonical form for matching: NFC, no zero-width chars, ASCII digits, no nukta, tidy punctuation.

    ``lowercase=False`` keeps Latin case for readable evidence excerpts; patterns are case-insensitive anyway.
    """
    text = unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH)
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = text.translate(_INDIC_DIGITS)
    text = text.replace("\u093c", "")  # Devanagari nukta: ज़/फ़ match ज/फ
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not (unicodedata.category(ch) == "Mn" and ord(ch) < 0x0300 + 0x70))
    text = unicodedata.normalize("NFC", text)
    if lowercase:
        text = text.lower()
    text = _REPEAT.sub(r"\1\1", text)
    text = _PUNCT_TO_SPACE.sub(" ", text)
    return _MULTISPACE.sub(" ", text).strip()


def canon_latin(token: str) -> str:
    """Collapse common romanization variants: kyaa→kya, beeku→beku, hoon→hun, aapka→apka."""
    token = token.lower()
    for a, b in (
        ("aa", "a"),
        ("ee", "i"),
        ("ii", "i"),
        ("oo", "u"),
        ("uu", "u"),
        ("ph", "f"),
        ("kh", "k"),
        ("gh", "g"),
        ("w", "v"),
        ("z", "j"),
    ):
        token = token.replace(a, b)
    return _REPEAT.sub(r"\1\1", token)


def _is_word_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in "LMN"


def tokenize(text: str) -> list[tuple[str, int, int]]:
    """Return ``(token, start, end)`` for words in ``text``. Apostrophes inside words are kept (don't, can't)."""
    out: list[tuple[str, int, int]] = []
    i, n = 0, len(text)
    while i < n:
        if _is_word_char(text[i]):
            j = i + 1
            while j < n and (_is_word_char(text[j]) or (text[j] in "'’" and j + 1 < n and _is_word_char(text[j + 1]))):
                j += 1
            out.append((text[i:j], i, j))
            i = j
        else:
            i += 1
    return out


def script_of(ch: str) -> str:
    """Coarse script of one character: Latn, Deva, Knda, Taml, Telu, Mlym, Beng, Other, or '' for non-letters."""
    cp = ord(ch)
    if 0x0900 <= cp <= 0x097F:
        return "Deva"
    if 0x0C80 <= cp <= 0x0CFF:
        return "Knda"
    if 0x0B80 <= cp <= 0x0BFF:
        return "Taml"
    if 0x0C00 <= cp <= 0x0C7F:
        return "Telu"
    if 0x0D00 <= cp <= 0x0D7F:
        return "Mlym"
    if 0x0980 <= cp <= 0x09FF:
        return "Beng"
    if unicodedata.category(ch)[0] == "L":
        name = unicodedata.name(ch, "")
        if name.startswith(("LATIN", "FULLWIDTH LATIN")):
            return "Latn"
        return "Other"
    if unicodedata.category(ch)[0] == "M":
        return "Other"  # combining marks inherit the script of the surrounding letters; callers handle this
    return ""


def token_script(token: str) -> str:
    """Dominant script of a token (letters only; combining marks follow their base letter)."""
    counts: dict[str, int] = {}
    for ch in token:
        s = script_of(ch)
        if s and unicodedata.category(ch)[0] != "M":
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def mask_digits(text: str) -> str:
    """Replace runs of 4+ digits (possible OTP/PIN/card/phone fragments) so excerpts never carry them."""
    return re.sub(r"\d{4,}", lambda m: "•" * len(m.group(0)), text)


def trim_excerpt(text: str, start: int, end: int, radius: int = 40, limit: int = 140) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    snippet = text[lo:hi].strip()
    if lo > 0:
        snippet = "…" + snippet
    if hi < len(text):
        snippet = snippet + "…"
    return mask_digits(snippet)[:limit]


@lru_cache(maxsize=4096)
def compile_pattern(pattern: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    """Compile an author-written regex with Indic-aware ``\\w``, ``\\W`` and ``\\b``."""
    pattern = unicodedata.normalize("NFC", pattern).translate(_ZERO_WIDTH).replace("\u093c", "")
    # Text is normalized without zero-width joiners, so patterns must not require them.
    pattern = re.sub(r"\\u200[cd]\??", "", pattern)
    out: list[str] = []
    in_class = False
    i, n = 0, len(pattern)
    word_body = _WORD_CLASS_BODY
    while i < n:
        ch = pattern[i]
        if ch == "\\" and i + 1 < n:
            nxt = pattern[i + 1]
            if nxt == "w":
                out.append(word_body if in_class else f"[{word_body}]")
            elif nxt == "W":
                out.append(f"[^{word_body}]" if not in_class else "\\W")
            elif nxt == "b" and not in_class:
                out.append(f"(?:(?<=[{word_body}])(?![{word_body}])|(?<![{word_body}])(?=[{word_body}]))")
            else:
                out.append(ch + nxt)
            i += 2
            continue
        if ch == "[" and not in_class:
            in_class = True
        elif ch == "]" and in_class:
            in_class = False
        out.append(ch)
        i += 1
    return re.compile("".join(out), flags)
