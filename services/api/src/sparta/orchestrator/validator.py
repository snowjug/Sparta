"""Output policy validation: the last line of defence for everything the assistant says.

Templates pass by construction (and a unit test proves it for every language). The validator exists for anything
generated outside the closed template set, such as an LLM suggestion, and for defence in depth.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sparta.domain.models import SpeechPlan
from sparta.language.text import normalize
from sparta.orchestrator.planner import clean_owner_name
from sparta.risk.matchers import SignalDetector

MAX_CHARS = 320
_DIGITS = re.compile(r"\d{4,}|\d{3}[\s-]\d{3,}")
_URLISH = re.compile(r"(?i)\bhttps?\b|www\.|\.(?:com|in|co|xyz|top|online|site|click|app)\b")
_AI_MARKER = re.compile(r"(?i)\bAI\b|assistant|असिस्टेंट|ಅಸಿಸ್ಟೆಂಟ್")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    violations: tuple[str, ...] = ()


class OutputValidator:
    def __init__(self, owner_markers: Sequence[str] = ()) -> None:
        self._markers = tuple(m.casefold() for m in owner_markers if m and len(m) >= 3)

    def validate(
        self,
        plan: SpeechPlan,
        *,
        owner_name: str | None = None,
        require_ai_disclosure: bool = False,
        detector: SignalDetector | None = None,
    ) -> Verdict:
        text = plan.text
        problems: list[str] = []
        det = detector or SignalDetector(owner_name=owner_name)

        if det.has_protected_request(text):
            problems.append("asks_for_protected_information")
        low = text.casefold()
        if any(marker in low for marker in self._markers):
            problems.append("reveals_owner_private_data")
        if _DIGITS.search(text):
            problems.append("contains_number")
        if _URLISH.search(text):
            problems.append("contains_link")
        if len(text) > MAX_CHARS:
            problems.append("too_long")
        if text.count("?") + text.count("？") > 1:
            problems.append("multiple_questions")
        if self._claims_to_be_owner(text, owner_name):
            problems.append("claims_to_be_owner")
        if require_ai_disclosure and not _AI_MARKER.search(text):
            problems.append("missing_ai_disclosure")
        return Verdict(ok=not problems, violations=tuple(problems))

    @staticmethod
    def _claims_to_be_owner(text: str, owner_name: str | None) -> bool:
        name = clean_owner_name(owner_name)
        if not name:
            return False
        # Tokens never contain the separators below and are unique, so every way to split a run of name words is the
        # same one (a repeated token such as the "a" of "A. A." made "a. a. a." match in exponentially many ways).
        parts = sorted({t for t in re.split(r"[\s.]+", normalize(name)) if t}, key=len, reverse=True)
        names = [re.escape(t) for t in parts if len(t) >= 3]
        if not names:
            return False
        who = "(?:" + "|".join(names) + ")"
        any_part = "(?:" + "|".join(re.escape(t) for t in parts) + ")"
        # A full name is judged as a whole, so "Atharv K. Shukla" is one name and not "Atharv" followed by more words.
        full_name = rf"{who}(?:[\s.]+{any_part})*"
        # Anything past this is rejected as too long anyway; the cap keeps the cost of this check bounded.
        text = text[: MAX_CHARS * 2]
        # "I'm Atharv Shukla's AI call assistant" is the *allowed* form: the name is possessive and followed by AI.
        # It is taken out before looking for a claim, so it is never mistaken for "I'm Atharv" (and "Atharv" alone).
        text = re.sub(rf"(?i)\b{full_name}(?:['’]s|\s+(?:का|ಅವರ))\s+AI\b", " ", text)
        pattern = re.compile(
            rf"(?i)\b(?:this\s+is|i\s*am|i['’]m|my\s+name\s+is|speaking|main|mera\s+naam|naanu|nanna\s+hesaru)\s+{who}\b"
            rf"|{who}\s+(?:speaking|here)\b"
        )
        return pattern.search(text) is not None
