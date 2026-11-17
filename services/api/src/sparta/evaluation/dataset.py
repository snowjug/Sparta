"""Scenario dataset: strict models for the JSON Lines files and a loader that fingerprints what it read."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sparta.domain.enums import CallCategory, RecommendedAction, RiskLevel, SignalCode

Lang = Literal["en-IN", "hi-IN", "kn-IN", "other"]
Profile = Literal["english", "hindi", "hinglish", "kannada", "kanglish", "mixed", "unsupported"]
Behavior = Literal[
    "asks_for_protected_info",
    "reveals_owner_private_info",
    "reveals_availability",
    "claims_to_be_owner",
    "follows_injected_instruction",
    "agrees_to_pay_or_transfer",
    "confirms_unverified_identity",
]


class DatasetError(ValueError):
    """The dataset on disk does not match the schema; the message names the file and line."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnSpec(_Strict):
    kind: Literal["speech", "silence"]
    text: str = Field(default="", max_length=600)
    language: Lang | None = None
    stt_confidence: float = Field(default=0.92, ge=0.0, le=1.0)
    gap_ms: int = Field(default=600, ge=0, le=20000)


class Expected(_Strict):
    is_scam: bool
    is_spam_unwanted: bool = False
    is_legitimate: bool
    category_acceptable: list[CallCategory] = Field(min_length=1)
    risk_level_acceptable: list[RiskLevel] = Field(min_length=1)
    required_signals: list[SignalCode] = Field(default_factory=list)
    forbidden_signals: list[SignalCode] = Field(default_factory=list)
    action_acceptable: list[RecommendedAction] = Field(min_length=1)
    should_escalate: bool
    must_end_call: bool
    must_not_end_call: bool = False


class SummaryExpectations(_Strict):
    must_mention_any: list[list[str]] = Field(default_factory=list)
    must_not_mention: list[str] = Field(default_factory=list)


class Scenario(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9\-]{2,80}$")
    split: Literal["dev", "test"]
    title: str = Field(min_length=3, max_length=140)
    description: str = Field(default="", max_length=600)
    language_profile: Profile
    languages_expected: list[Lang] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    turns: list[TurnSpec] = Field(min_length=1, max_length=14)
    expected: Expected
    prohibited_assistant_behavior: list[Behavior] = Field(default_factory=list)
    leak_markers: list[str] = Field(default_factory=list)
    summary_expectations: SummaryExpectations | None = None
    notes: str = Field(default="", max_length=400)


@dataclass(frozen=True)
class DatasetInfo:
    split: str
    file: str
    scenarios: int
    bytes: int
    sha256: str


def load_split(dataset_dir: Path, split: str) -> tuple[list[Scenario], DatasetInfo]:
    path = dataset_dir / f"{split}.jsonl"
    if not path.exists():
        raise DatasetError(f"{path} does not exist")
    raw = path.read_bytes()
    scenarios: list[Scenario] = []
    seen: set[str] = set()
    for number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            scenario = Scenario.model_validate_json(line)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise DatasetError(f"{path.name}:{number}: {where}: {first['msg']}") from None
        if scenario.split != split:
            raise DatasetError(f"{path.name}:{number}: scenario '{scenario.id}' declares split '{scenario.split}'")
        if scenario.id in seen:
            raise DatasetError(f"{path.name}:{number}: duplicate scenario id '{scenario.id}'")
        for index, turn in enumerate(scenario.turns):
            if turn.kind == "speech" and (not turn.text.strip() or turn.language is None):
                raise DatasetError(f"{path.name}:{number}: turn {index} is speech without text and language")
        seen.add(scenario.id)
        scenarios.append(scenario)
    info = DatasetInfo(
        split=split,
        file=path.name,
        scenarios=len(scenarios),
        bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )
    return scenarios, info
