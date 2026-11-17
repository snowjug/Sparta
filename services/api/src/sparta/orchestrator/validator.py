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
        tokens = [re.escape(t) for t in normalize(name).split() if len(t) >= 3]
        if not tokens:
            return False
        who = "(?:" + "|".join(tokens) + ")"
        pattern = re.compile(
            rf"(?i)\b(?:this\s+is|i\s*am|i['’]m|my\s+name\s+is|speaking|main|mera\s+naam|naanu|nanna\s+hesaru)\s+{who}\b"
            rf"|{who}\s+(?:speaking|here)\b"
        )
        match = pattern.search(text)
        if not match:
            return False
        # "I'm Atharv's AI call assistant" is the *allowed* form: the name is possessive and followed by AI/assistant.
        tail = text[match.end() : match.end() + 12]
        return not re.match(r"(?i)['’]s\s+AI|\s+(?:का|ಅವರ)\s+AI", tail)
