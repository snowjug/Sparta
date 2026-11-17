"""Caller-number handling: normalisation, keyed fingerprints and masked display.

Raw numbers are personal data. The API never returns them; lists and matching use a keyed fingerprint
(HMAC-SHA256 with a per-user key) and a masked rendering such as ``+91 98••• ••21``. The same scheme is implemented on
Android so a device can match numbers offline without ever holding the raw number of a caller it blocked on a server.
"""

import hashlib
import hmac
import re

_DIGITS = re.compile(r"\D")
KNOWN_CC = ("1", "7", "20", "27", "30", "31", "32", "33", "34", "39", "41", "44", "49", "52", "55", "60", "61", "62")
PRIVATE_DISPLAY = "Private number"
DEFAULT_COUNTRY_CODE = "91"


def normalize_number(raw: str | None, default_country_code: str = DEFAULT_COUNTRY_CODE) -> str | None:
    """Best-effort E.164 (``+`` and digits only). ``None`` when it does not look like a phone number."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith("tel:"):
        raw = raw[4:]
    has_plus = raw.startswith("+")
    digits = _DIGITS.sub("", raw)
    if digits.startswith("00") and not has_plus:
        digits, has_plus = digits[2:], True
    if not has_plus:
        if len(digits) == 10:
            digits = default_country_code + digits
        elif len(digits) == 11 and digits.startswith("0"):
            digits = default_country_code + digits[1:]
    if not 7 <= len(digits) <= 15:
        return None
    return "+" + digits


def fingerprint(salt: bytes, e164: str) -> str:
    return hmac.new(salt, e164.encode("utf-8"), hashlib.sha256).hexdigest()


def _split_country(digits: str) -> tuple[str, str]:
    if digits.startswith("91"):
        return "91", digits[2:]
    for cc in sorted(KNOWN_CC, key=len, reverse=True):
        if digits.startswith(cc):
            return cc, digits[len(cc) :]
    return digits[:2], digits[2:]


def mask_number(e164: str | None) -> str:
    """``+919876543221`` → ``+91 98••• ••21``. Short numbers keep only their last digit."""
    if not e164:
        return PRIVATE_DISPLAY
    digits = e164.lstrip("+")
    cc, national = _split_country(digits)
    if len(national) < 6:
        return f"+{cc} " + "•" * max(len(national) - 1, 1) + national[-1:]
    head, tail = national[:2], national[-2:]
    middle = "•" * (len(national) - 4)
    split = max(len(middle) - 2, 1)
    return f"+{cc} {head}{middle[:split]} {middle[split:]}{tail}"
