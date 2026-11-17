"""Rule matching: turns a policy + language-pack vocabularies into compiled matchers and detects signals in text.

All languages' vocabularies are merged by name, so a single rule such as *OTP term near a request cue* matches
"tell me your OTP", "OTP bataiye" and "OTP heli" alike, and keeps working inside code-switched sentences.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from sparta.domain.enums import SignalKind
from sparta.domain.models import RiskSignal
from sparta.language.registry import OWNER_PLACEHOLDER, PackRegistry, load_registry
from sparta.language.text import compile_pattern, normalize, tokenize, trim_excerpt
from sparta.risk.policy import RuleDef, SafetyPolicy, load_default_policy

NEVER_MATCH = "(?!x)x"
GENERIC_OWNER_NAMES = {"the owner", "owner", "the", ""}


@dataclass(frozen=True)
class Hit:
    start: int
    end: int


def owner_name_pattern(owner_name: str | None) -> str:
    """Regex alternation of the owner's name tokens, or a never-matching pattern when no real name is set."""
    if not owner_name:
        return NEVER_MATCH
    tokens = {normalize(t, lowercase=True) for t, _, _ in tokenize(owner_name) if len(t) >= 3}
    tokens -= GENERIC_OWNER_NAMES
    if not tokens:
        return NEVER_MATCH
    return "(?:" + "|".join(re.escape(t) for t in sorted(tokens, key=len, reverse=True)) + ")"


def _vocab_pattern(fragments: list[str], owner_pattern: str) -> re.Pattern[str]:
    joined = "|".join(f"(?:{f.replace(OWNER_PLACEHOLDER, owner_pattern)})" for f in fragments)
    return compile_pattern(f"(?:{joined})")


def find_near(text: str, groups: list[re.Pattern[str]], window: int) -> Hit | None:
    """First place where every group matches within ``window`` characters of an anchor match."""
    spans = [[m.span() for m in g.finditer(text)] for g in groups]
    if any(not s for s in spans):
        return None
    anchor = min(range(len(groups)), key=lambda i: len(spans[i]))
    for a_start, a_end in spans[anchor]:
        chosen = [(a_start, a_end)]
        for j, candidates in enumerate(spans):
            if j == anchor:
                continue
            best: tuple[int, int, int] | None = None
            for s, e in candidates:
                gap = max(0, s - a_end, a_start - e)
                if gap <= window and (best is None or gap < best[0]):
                    best = (gap, s, e)
            if best is None:
                break
            chosen.append((best[1], best[2]))
        else:
            return Hit(min(s for s, _ in chosen), max(e for _, e in chosen))
    return None


class CompiledRule:
    def __init__(self, rule: RuleDef, union: "Union") -> None:
        self.rule = rule
        self._any = [union(name) for name in rule.any]
        self._near = [union(*group) for group in rule.near]
        self._unless = [union(name) for name in rule.unless]

    def match(self, text: str) -> Hit | None:
        hit: Hit | None = None
        for pattern in self._any:
            m = pattern.search(text)
            if m and (hit is None or m.start() < hit.start):
                hit = Hit(m.start(), m.end())
        if hit is None and self._near:
            hit = find_near(text, self._near, self.rule.window)
        if hit is None:
            return None
        if self._unless and self._suppressed(text, hit):
            return None
        return hit

    def _suppressed(self, text: str, hit: Hit) -> bool:
        lo = max(0, hit.start - self.rule.unless_before)
        hi = min(len(text), hit.end + self.rule.unless_after)
        return any(p.search(text, lo, hi) for p in self._unless)


class Union:
    """Builds (and caches) one compiled pattern per set of vocabulary names."""

    def __init__(self, fragments: dict[str, list[str]], owner_pattern: str) -> None:
        self._fragments = fragments
        self._owner_pattern = owner_pattern
        self._cache: dict[tuple[str, ...], re.Pattern[str]] = {}

    def __call__(self, *names: str) -> re.Pattern[str]:
        key = tuple(sorted(names))
        if key not in self._cache:
            frags = [f for name in key for f in self._fragments[name]]
            self._cache[key] = _vocab_pattern(frags, self._owner_pattern)
        return self._cache[key]


class RuleSet:
    def __init__(self, policy: SafetyPolicy, registry: PackRegistry, owner_pattern: str) -> None:
        union = Union({**registry.terms, **registry.cues}, owner_pattern)
        self.rules = [CompiledRule(rule, union) for rule in policy.rules]


@lru_cache(maxsize=64)
def _ruleset(policy_version: str, owner_pattern: str) -> RuleSet:
    # policy_version participates in the cache key; the policy object itself is the process-wide default.
    return RuleSet(load_default_policy(), load_registry(), owner_pattern)


class SignalDetector:
    """Detects signals in one caller (or assistant) utterance."""

    def __init__(
        self,
        policy: SafetyPolicy | None = None,
        registry: PackRegistry | None = None,
        owner_name: str | None = None,
    ) -> None:
        self.policy = policy or load_default_policy()
        self.registry = registry or load_registry()
        owner_pattern = owner_name_pattern(owner_name)
        if policy is None and registry is None:
            self._rules = _ruleset(self.policy.version, owner_pattern)
        else:
            self._rules = RuleSet(self.policy, self.registry, owner_pattern)

    def detect(self, text: str, turn_id: str) -> list[RiskSignal]:
        norm = normalize(text, lowercase=False)
        best: dict[str, tuple[float, RiskSignal]] = {}
        for compiled in self._rules.rules:
            hit = compiled.match(norm)
            if hit is None:
                continue
            rule = compiled.rule
            definition = self.policy.signals[rule.signal]
            weight = rule.weight if rule.weight is not None else definition.weight
            severity = rule.severity or definition.severity
            signal = RiskSignal(
                code=rule.signal,
                kind=definition.kind,
                severity=severity,
                weight=weight,
                evidence_turn_ids=[turn_id],
                evidence_excerpt=trim_excerpt(norm, hit.start, hit.end, self.policy.limits.excerpt_radius),
                description=definition.description,
            )
            current = best.get(rule.signal.value)
            if current is None or weight > current[0]:
                best[rule.signal.value] = (weight, signal)
        return [s for _, s in best.values()]

    def has_protected_request(self, text: str) -> list[RiskSignal]:
        """Signals in ``text`` that are protected-information requests (used to police the assistant's own output)."""
        protected = self.policy.protected_signal_codes()
        return [s for s in self.detect(text, "assistant") if s.code in protected and s.kind is SignalKind.RISK]


def merge_signals(existing: list[RiskSignal], new: list[RiskSignal], max_turns: int = 8) -> list[RiskSignal]:
    """Cumulative per-call signals: one entry per code, evidence turns accumulated, strongest weight kept."""
    by_code = {s.code: s.model_copy(deep=True) for s in existing}
    for s in new:
        cur = by_code.get(s.code)
        if cur is None:
            by_code[s.code] = s.model_copy(deep=True)
            continue
        turns = list(dict.fromkeys([*cur.evidence_turn_ids, *s.evidence_turn_ids]))[:max_turns]
        if s.weight > cur.weight:
            cur.weight, cur.severity = s.weight, s.severity
            cur.evidence_excerpt = s.evidence_excerpt or cur.evidence_excerpt
        cur.evidence_turn_ids = turns
    return list(by_code.values())
