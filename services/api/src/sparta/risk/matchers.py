"""Rule matching: turns a policy + language-pack vocabularies into compiled matchers and detects signals in text.

All languages' vocabularies are merged by name, so a single rule such as *OTP term near a request cue* matches
"tell me your OTP", "OTP bataiye" and "OTP heli" alike, and keeps working inside code-switched sentences.

Denials ("no OTP is needed", "never share your PIN") are handled per mention, not per sentence: the text is copied with
every sensitive-term occurrence replaced by one placeholder character, the language packs' `negation` cues (written
over that placeholder) mark which occurrences sit inside a denial, and rules that opt in via ``negated_by`` ignore
exactly those occurrences. A denial can therefore never hide a different request in the same sentence
("do not share your OTP with anyone, tell me the OTP now").
"""

import re
import unicodedata
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from sparta.domain.enums import SignalKind
from sparta.domain.models import RiskSignal
from sparta.language.registry import (
    BREAK_PLACEHOLDER,
    CLAUSE_CHAR,
    LIST_PLACEHOLDER,
    MASK_CHAR,
    OWNER_PLACEHOLDER,
    TERM_PLACEHOLDER,
    PackRegistry,
    load_registry,
)
from sparta.language.text import clause_breaks, compile_pattern, normalize, tokenize, trim_excerpt
from sparta.risk.policy import RuleDef, SafetyPolicy, load_default_policy

NEVER_MATCH = "(?!x)x"
GENERIC_OWNER_NAMES = {"the owner", "owner", "the", ""}
CARVE_OUT_LOOKAHEAD = 80  # characters after a denial that are checked for "...except me"
MAX_DETECT_CHARS = 2048  # one turn plus the previous one (each at most 1000 characters after sanitising)
MAX_DENIAL_MENTIONS = 32  # denial matching is quadratic in the mentions; the rest are treated as not denied

Span = tuple[int, int]


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


def redact_owner_name(text: str, owner_name: str | None, replacement: str = "the owner") -> str:
    """``text`` with the owner's name replaced: for anything that leaves the process, such as a model provider."""
    pattern = owner_name_pattern(owner_name)
    if pattern == NEVER_MATCH:
        return text
    return compile_pattern(rf"\b{pattern}\b").sub(replacement, text)


@lru_cache(maxsize=4096)
def _compiled(source: str) -> re.Pattern[str]:
    # Shared across rule sets: only vocabularies that mention {OWNER} differ between owners.
    return compile_pattern(source)


def _vocab_pattern(fragments: list[str], substitutions: dict[str, str]) -> re.Pattern[str]:
    def fill(fragment: str) -> str:
        for placeholder, value in substitutions.items():
            fragment = fragment.replace(placeholder, value)
        return fragment

    joined = "|".join(f"(?:{fill(f)})" for f in fragments)
    return _compiled(f"(?:{joined})")


def _overlaps(span: Span, spans: Sequence[Span]) -> bool:
    start, end = span
    return any(start < d_end and d_start < end for d_start, d_end in spans)


def find_near(text: str, groups: list[re.Pattern[str]], window: int, exclude: Sequence[Span] = ()) -> Hit | None:
    """First place where every group matches within ``window`` characters of an anchor match.

    Matches of the first group (the sensitive term) that overlap an ``exclude`` span are ignored.
    """
    spans = [[m.span() for m in g.finditer(text)] for g in groups]
    if exclude:
        spans[0] = [s for s in spans[0] if not _overlaps(s, exclude)]
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


def _first_match(pattern: re.Pattern[str], text: str, exclude: Sequence[Span]) -> re.Match[str] | None:
    if not exclude:
        return pattern.search(text)
    return next((m for m in pattern.finditer(text) if not _overlaps(m.span(), exclude)), None)


class CompiledRule:
    def __init__(self, rule: RuleDef, union: "Union") -> None:
        self.rule = rule
        self.negation_key = tuple(rule.negated_by)
        self._any = [union(name) for name in rule.any]
        self._near = [union(*group) for group in rule.near]
        self._unless = [union(name) for name in rule.unless]

    def match(self, text: str, denied: Sequence[Span] = ()) -> Hit | None:
        """``denied`` are the term mentions inside denial phrases (only consulted when the rule has ``negated_by``)."""
        hit: Hit | None = None
        for pattern in self._any:
            m = _first_match(pattern, text, denied)
            if m and (hit is None or m.start() < hit.start):
                hit = Hit(m.start(), m.end())
        if hit is None and self._near:
            hit = find_near(text, self._near, self.rule.window, denied)
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

    def __init__(self, fragments: dict[str, list[str]], owner_pattern: str, joiner: list[str] | None = None) -> None:
        self._fragments = fragments
        # `{LIST}`: mentions separated by whitespace, a clause break or "/", optionally with joiner words in between
        # ("OTP or PIN", "OTP, PIN", "transfer any money").
        words = "|".join(f"(?:{w})" for w in joiner or [])
        gap = rf"(?:\s+|{CLAUSE_CHAR}\s*|\s*[/&]\s*)"
        between = f"{gap}(?:(?:{words}){gap})*" if words else gap
        self._substitutions = {
            OWNER_PLACEHOLDER: owner_pattern,
            LIST_PLACEHOLDER: f"{MASK_CHAR}(?:{between}{MASK_CHAR})*",
            TERM_PLACEHOLDER: MASK_CHAR,
            BREAK_PLACEHOLDER: CLAUSE_CHAR,
        }
        self._cache: dict[tuple[str, ...], re.Pattern[str]] = {}

    def __call__(self, *names: str) -> re.Pattern[str]:
        key = tuple(sorted(names))
        if key not in self._cache:
            frags = [f for name in key for f in self._fragments[name]]
            self._cache[key] = _vocab_pattern(frags, self._substitutions)
        return self._cache[key]


class RuleSet:
    def __init__(self, policy: SafetyPolicy, registry: PackRegistry, owner_pattern: str) -> None:
        negation = policy.negation
        union = Union({**registry.terms, **registry.cues}, owner_pattern, registry.cues.get(negation.joiner))
        self.rules = [CompiledRule(rule, union) for rule in policy.rules]
        keys = {rule.negation_key for rule in self.rules if rule.negation_key}
        self._terms = union(*negation.terms) if keys and negation.terms else None
        self._denials = {key: union(*key) for key in keys}
        self._exception = union(negation.exception) if keys and negation.exception in registry.cues else None

    def denied_mentions(self, text: str, breaks: Sequence[int] | None, key: tuple[str, ...]) -> list[Span]:
        """Spans of sensitive-term mentions in ``text`` that sit inside a denial phrase of the ``key`` cue set.

        ``breaks`` are the clause boundaries of ``text`` (see ``clause_breaks``); without them nothing is denied.
        """
        denial = self._denials.get(key)
        if denial is None or self._terms is None or breaks is None:
            return []
        chars = list(text.replace(MASK_CHAR, " ").replace(CLAUSE_CHAR, " "))  # callers cannot forge the markers
        for position in breaks:
            chars[position] = CLAUSE_CHAR
        marked = "".join(chars)
        mentions: list[Span] = []
        for m in self._terms.finditer(marked):
            start, end = m.span()
            while start < end and marked[start].isspace():  # some fragments swallow a neighbouring space
                start += 1
            while end > start and marked[end - 1].isspace():
                end -= 1
            if end > start:
                mentions.append((start, end))
            if len(mentions) >= MAX_DENIAL_MENTIONS:
                break  # a flood of mentions: later ones are simply not denied, so their signals still fire
        if not mentions:
            return []
        pieces: list[str] = []
        positions: list[int] = []  # index of each mention's placeholder in the masked text
        cursor = length = 0
        for start, end in mentions:
            pieces += [marked[cursor:start], MASK_CHAR]
            length += start - cursor
            positions.append(length)
            length += 1
            cursor = end
        pieces.append(marked[cursor:])
        masked = "".join(pieces)
        denied: list[Span] = []
        for m in denial.finditer(masked):
            if self._exception is not None and self._exception.match(masked, m.end(), m.end() + CARVE_OUT_LOOKAHEAD):
                continue  # "do not share your OTP with anyone except me" is still a request
            denied.extend(mentions[bisect_left(positions, m.start()) : bisect_left(positions, m.end())])
        return denied


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
        # Compatibility forms can expand a lot (U+FDFA -> 18 characters): expand first, then cap, so the cost is bounded.
        text = unicodedata.normalize("NFKC", text[: MAX_DETECT_CHARS * 4])[:MAX_DETECT_CHARS]
        norm = normalize(text, lowercase=False)
        best: dict[str, tuple[float, RiskSignal]] = {}
        denied_by_key: dict[tuple[str, ...], list[Span]] = {}
        breaks: list[int] | None = None
        breaks_known = False
        for compiled in self._rules.rules:
            denied: list[Span] = []
            key = compiled.negation_key
            if key:
                if key not in denied_by_key:
                    if not breaks_known:
                        breaks, breaks_known = clause_breaks(text, norm, lowercase=False), True
                    denied_by_key[key] = self._rules.denied_mentions(norm, breaks, key)
                denied = denied_by_key[key]
            hit = compiled.match(norm, denied)
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
