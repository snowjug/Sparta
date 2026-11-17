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

# Characters that render as nothing. Text matching deletes them (never turns them into spaces) so that an invisible
# character inside a keyword cannot split it: soft hyphen, bidi marks and controls, invisible operators, variation
# selectors, interlinear annotation marks, language tags. Private-use characters are removed separately.
_INVISIBLE = dict.fromkeys(
    [
        *_ZERO_WIDTH,
        *map(ord, "\u00ad\u200e\u200f\u061c\u180e\u180f"),
        *range(0x202A, 0x202F),
        *range(0x2061, 0x2065),
        *range(0x2066, 0x206A),
        *range(0x180B, 0x180E),
        *range(0xFE00, 0xFE10),
        *range(0xFFF9, 0xFFFC),
        *range(0xE0000, 0xE0080),
        *range(0xE0100, 0xE01F0),
    ]
)
_PRIVATE_USE = re.compile("[\ue000-\uf8ff\U000f0000-\U000ffffd\U00100000-\U0010fffd]")

# Cyrillic and Greek letters that look like Latin ones ("оtp", "ОТР"). Words made only of Latin letters, digits,
# punctuation and these look-alikes are folded to Latin for matching; other words (real Russian or Greek) stay as they
# are.
_LOOKALIKES = {
    **dict(zip("авекмнорстухіјѕһԁԛԝѵӏ", "abekmhopctyxijshdqwvl", strict=True)),
    **dict(zip("АВЕКМНОРСТХУІЈЅԀԚԜӀ", "ABEKMHOPCTXYIJSDQWI", strict=True)),
    **dict(zip("αεικνορτυχγϲϳ", "aeikvoptuxycj", strict=True)),
    **dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧϹ", "ABEZHIKMNOPTYXC", strict=True)),
    **dict(zip("ıɑɡ", "iag", strict=True)),
}
_LOOKALIKE_TABLE = str.maketrans(_LOOKALIKES)
_LOOKALIKE_CHARS = "".join(_LOOKALIKES)
_HAS_LOOKALIKE = re.compile(f"[{_LOOKALIKE_CHARS}]")
_FOLDABLE_WORD = re.compile(f"[A-Za-z0-9'’.,;:!?()\\-{_LOOKALIKE_CHARS}]+")
_WORD_RUN = re.compile(r"\S+")
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


INDIC_JOINERS = "\u200c\u200d"  # zero-width non-joiner / joiner: they shape Indic conjuncts and are never visible
_INVISIBLE_EXCEPT_JOINERS = {k: v for k, v in _INVISIBLE.items() if chr(k) not in INDIC_JOINERS}
_JOINER_RUN = re.compile(f"[{INDIC_JOINERS}]+")


def strip_invisible(text: str, keep_joiners: bool = False) -> str:
    """Delete characters that render as nothing (see ``_INVISIBLE``) and private-use characters.

    ``keep_joiners`` leaves the zero-width (non-)joiners for ``settle_joiners``.
    """
    text = text.translate(_INVISIBLE_EXCEPT_JOINERS if keep_joiners else _INVISIBLE)
    return _PRIVATE_USE.sub("", text)


def settle_joiners(text: str) -> str:
    """Resolve zero-width (non-)joiners: a space next to an Indic letter, nothing anywhere else.

    Kannada and Hindi writers put a ZWNJ between a word and the suffix attached to it (mobile + ge); treating it as a
    word break is the tokenisation the lexicons and the published evaluation were built on. Between Latin letters or
    digits it is invisible and must not split a keyword, so it is deleted.
    """

    def settle(match: re.Match[str]) -> str:
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        indic = "\u0900" <= before <= "\u0dff" or "\u0900" <= after <= "\u0dff"
        return " " if indic and before and after else ""

    return _JOINER_RUN.sub(settle, text)


def fold_confusables(text: str) -> str:
    """Fold Cyrillic/Greek look-alike letters to Latin inside words that contain nothing else but Latin text."""
    if not _HAS_LOOKALIKE.search(text):
        return text

    def fold(match: re.Match[str]) -> str:
        word = match.group()
        return word.translate(_LOOKALIKE_TABLE) if _FOLDABLE_WORD.fullmatch(word) else word

    return _WORD_RUN.sub(fold, text)


def normalize(text: str, lowercase: bool = True) -> str:
    """Canonical form for matching: NFC, no invisible chars, ASCII digits, no nukta, tidy punctuation.

    ``lowercase=False`` keeps Latin case for readable evidence excerpts; patterns are case-insensitive anyway.
    """
    text = fold_confusables(strip_invisible(unicodedata.normalize("NFC", text)))
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


_CLAUSE_PUNCT = re.compile(r"[,;!?।॥]+")


def clause_breaks(text: str, norm: str, lowercase: bool = True) -> list[int] | None:
    """Offsets in ``norm`` (= ``normalize(text, lowercase)``) that were clause punctuation in ``text``.

    ``normalize`` turns commas, semicolons, question/exclamation marks and the danda into plain spaces, which is what
    most patterns want. Denial detection needs the clause boundaries back ("don't tell anyone, your PIN is needed"
    must not read as one denial), so they are recovered by normalizing the clauses separately. Returns ``None`` when the
    pieces do not recompose to ``norm`` (unusual Unicode), in which case callers must not rely on boundaries.
    """
    clauses = _CLAUSE_PUNCT.split(unicodedata.normalize("NFKD", text))  # NFKD: full-width "，" is a comma too
    pieces = [p for p in (normalize(c, lowercase) for c in clauses) if p]
    if " ".join(pieces) != norm:
        return None
    breaks: list[int] = []
    position = 0
    for piece in pieces[:-1]:
        position += len(piece)
        breaks.append(position)  # the single space that joins this clause to the next
        position += 1
    return breaks


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
