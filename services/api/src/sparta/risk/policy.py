"""Safety policy documents (versioned TOML) loaded into validated models."""

import tomllib
from functools import lru_cache
from importlib import resources
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sparta.domain.enums import CallCategory, ScreeningStrictness, SignalCode, SignalKind, SignalSeverity
from sparta.language.registry import PackRegistry, load_registry

POLICY_PACKAGE = "sparta.risk.policies"


class SignalDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SignalKind = SignalKind.RISK
    severity: SignalSeverity
    weight: float = Field(ge=0.0, le=1.0)
    protected: bool = False
    description: str
    category: CallCategory | None = None


class RuleDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal: SignalCode
    any: list[str] = Field(default_factory=list)
    near: list[list[str]] = Field(default_factory=list)
    window: int = Field(default=80, ge=1, le=400)
    unless: list[str] = Field(default_factory=list)
    unless_before: int = Field(default=30, ge=0)
    unless_after: int = Field(default=40, ge=0)
    severity: SignalSeverity | None = None
    weight: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _has_condition(self) -> Self:
        if not self.any and len(self.near) < 2:
            raise ValueError(f"rule for {self.signal} needs 'any' or at least two 'near' groups")
        return self


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high: float
    medium: float
    critical_floor: float
    legit_max_discount: float
    uncertain_confidence: float


class StrictnessProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    high: float
    medium: float


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_clarify_attempts: int = 2
    max_probe_deflections: int = 2
    excerpt_radius: int = 40


class ProtectedInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    signals: list[SignalCode] = Field(default_factory=list)


class PolicyHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    name: str
    description: str = ""


class SafetyPolicy(BaseModel):
    """Validated safety policy. ``version`` is stamped on every risk assessment for auditability."""

    model_config = ConfigDict(extra="forbid")

    policy: PolicyHeader
    thresholds: Thresholds
    strictness: dict[ScreeningStrictness, StrictnessProfile]
    limits: Limits = Field(default_factory=Limits)
    protected_information: list[ProtectedInfo]
    signals: dict[SignalCode, SignalDef]
    rules: list[RuleDef]

    @property
    def version(self) -> str:
        return self.policy.version

    def protected_signal_codes(self) -> frozenset[SignalCode]:
        return frozenset(code for code, d in self.signals.items() if d.protected)

    def validate_against(self, registry: PackRegistry) -> None:
        """Every vocabulary a rule names must exist in at least one language pack."""
        known = set(registry.terms) | set(registry.cues)
        missing: list[str] = []
        for rule in self.rules:
            names = [*rule.any, *rule.unless, *(n for group in rule.near for n in group)]
            missing.extend(f"{rule.signal}: {n}" for n in names if n not in known)
        if rule_codes := {r.signal for r in self.rules} - set(self.signals):
            missing.append(f"rules reference undefined signals: {sorted(rule_codes)}")
        if missing:
            raise ValueError("policy references unknown vocabulary: " + "; ".join(sorted(set(missing))))


def load_policy_text(text: str) -> SafetyPolicy:
    return SafetyPolicy.model_validate(tomllib.loads(text))


@lru_cache
def load_default_policy() -> SafetyPolicy:
    raw = resources.files(POLICY_PACKAGE).joinpath("default-v1.toml").read_text(encoding="utf-8")
    policy = load_policy_text(raw)
    policy.validate_against(load_registry())
    return policy
