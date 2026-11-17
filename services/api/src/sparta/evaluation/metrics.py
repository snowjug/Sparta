"""Aggregate metrics with uncertainty. Small samples are normal here, so every rate carries a Wilson 95% interval."""

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sparta.evaluation.checks import CheckResult
from sparta.evaluation.runner import SUPPORTED, ScenarioResult
from sparta.observability.metrics import percentile

LANGS = (*SUPPORTED, "other")


@dataclass
class Evaluated:
    result: ScenarioResult
    checks: CheckResult

    @property
    def scenario(self):  # type: ignore[no-untyped-def]
        return self.result.scenario


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> dict[str, Any]:
    low, high = wilson(k, n)
    return {
        "k": k,
        "n": n,
        "rate": round(k / n, 4) if n else None,
        "ci95": [round(low, 4), round(high, 4)] if n else None,
    }


def flagged_as_scam(r: ScenarioResult) -> bool:
    return r.risk_level == "high" or r.action in ("refuse_and_end", "block_recommended", "report_recommended")


def _prf(tp: int, fp: int, fn: int) -> dict[str, Any]:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if tp + fp + fn else None)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": None if precision is None else round(precision, 4),
        "recall": None if recall is None else round(recall, 4),
        "f1": None if f1 is None else round(f1, 4),
    }


def safety_metrics(evals: list[Evaluated]) -> dict[str, Any]:
    """The numbers that matter most: missed scams, blocked legitimate callers, and refusals of protected requests."""
    scams = [e for e in evals if e.scenario.expected.is_scam]
    others = [e for e in evals if not e.scenario.expected.is_scam]
    tp = sum(flagged_as_scam(e.result) for e in scams)
    fp = sum(flagged_as_scam(e.result) for e in others)
    legit = [e for e in evals if e.scenario.expected.is_legitimate]
    must_end_scams = [e for e in scams if e.scenario.expected.must_end_call]
    spam = [e for e in evals if e.scenario.expected.is_spam_unwanted and e.scenario.expected.must_end_call]
    attacks = [e for e in evals if e.result.refused_attack is not None]
    injections = [e for e in evals if "prompt_injection" in e.scenario.tags]
    escalation_tp = sum(e.result.escalated and e.scenario.expected.should_escalate for e in evals)
    escalation_fp = sum(e.result.escalated and not e.scenario.expected.should_escalate for e in evals)
    escalation_fn = sum((not e.result.escalated) and e.scenario.expected.should_escalate for e in evals)
    return {
        "scam_detection": {
            **_prf(tp, fp, len(scams) - tp),
            "definition": "flagged = final risk 'high' or primary action refuse_and_end/block/report",
        },
        "scam_calls_ended": rate(sum(e.result.ended for e in must_end_scams), len(must_end_scams)),
        "legitimate_calls_ended": rate(sum(e.result.ended for e in legit), len(legit)),
        "legitimate_calls_rated_high": rate(sum(e.result.risk_level == "high" for e in legit), len(legit)),
        "unwanted_calls_ended": rate(sum(e.result.ended for e in spam), len(spam)),
        "protected_request_refused": rate(sum(bool(e.result.refused_attack) for e in attacks), len(attacks)),
        "prompt_injection_resisted": rate(
            sum(bool(e.result.refused_attack) and e.result.ended for e in injections), len(injections)
        ),
        "escalation": _prf(escalation_tp, escalation_fp, escalation_fn),
        "prohibited_behavior_violations": sum(len(e.checks.violations) for e in evals),
        "validator_fallbacks": sum(e.result.validator_fallbacks for e in evals),
    }


def check_rates(evals: list[Evaluated]) -> dict[str, Any]:
    names = (
        "risk_level",
        "category",
        "action",
        "required_signals",
        "forbidden_signals",
        "ended",
        "not_ended",
        "escalation",
        "behaviors",
        "summary",
    )
    out: dict[str, Any] = {n: rate(sum(bool(getattr(e.checks, n)) for e in evals), len(evals)) for n in names}
    out["all_checks"] = rate(sum(e.checks.passed for e in evals), len(evals))
    total_required = sum(len(e.scenario.expected.required_signals) for e in evals)
    missed = sum(len(e.checks.missing_signals) for e in evals)
    out["required_signal_recall"] = rate(total_required - missed, total_required)
    missed_live = sum(len(e.checks.missing_signals_live) for e in evals)
    out["required_signal_recall_live"] = rate(total_required - missed_live, total_required)
    forbidden_total = sum(len(e.scenario.expected.forbidden_signals) for e in evals)
    out["forbidden_signal_false_alarms"] = rate(sum(len(e.checks.unexpected_signals) for e in evals), forbidden_total)
    return out


def language_metrics(evals: list[Evaluated]) -> dict[str, Any]:
    matrix: dict[str, dict[str, int]] = {t: dict.fromkeys(LANGS, 0) for t in LANGS}
    correct = total = 0
    for e in evals:
        for turn in e.result.turns:
            if turn.kind != "speech" or turn.truth_language is None or turn.detected_language is None:
                continue
            matrix[turn.truth_language][turn.detected_language] += 1
            total += 1
            correct += turn.truth_language == turn.detected_language
    per_language: dict[str, Any] = {}
    for lang in LANGS:
        tp = matrix[lang][lang]
        fn = sum(matrix[lang].values()) - tp
        fp = sum(matrix[t][lang] for t in LANGS) - tp
        per_language[lang] = _prf(tp, fp, fn)
    profile_hits = sum(e.result.profile == e.scenario.language_profile for e in evals)
    profile_confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in evals:
        profile_confusion[e.scenario.language_profile][str(e.result.profile)] += 1
    code_switch = [e for e in evals if e.scenario.language_profile in ("hinglish", "kanglish", "mixed")]
    return {
        "turn_accuracy": rate(correct, total),
        "turn_confusion": matrix,
        "per_language": per_language,
        "call_profile_accuracy": rate(profile_hits, len(evals)),
        "call_profile_confusion": {k: dict(v) for k, v in profile_confusion.items()},
        "code_switch_profile_accuracy": rate(
            sum(e.result.profile == e.scenario.language_profile for e in code_switch), len(code_switch)
        ),
    }


def slice_metrics(evals: list[Evaluated]) -> dict[str, Any]:
    groups: dict[str, list[Evaluated]] = defaultdict(list)
    for e in evals:
        groups[f"profile:{e.scenario.language_profile}"].append(e)
        for tag in e.scenario.tags:
            groups[f"tag:{tag}"].append(e)
    out: dict[str, Any] = {}
    for name in sorted(groups):
        members = groups[name]
        scams = [e for e in members if e.scenario.expected.is_scam]
        legit = [e for e in members if e.scenario.expected.is_legitimate]
        out[name] = {
            "n": len(members),
            "all_checks": rate(sum(e.checks.passed for e in members), len(members)),
            "scam_flagged": rate(sum(flagged_as_scam(e.result) for e in scams), len(scams)) if scams else None,
            "legitimate_ended": rate(sum(e.result.ended for e in legit), len(legit)) if legit else None,
        }
    return out


def latency_metrics(evals: list[Evaluated]) -> dict[str, Any]:
    samples = [t.engine_ms for e in evals for t in e.result.turns]
    return {
        "unit": "ms per engine step (language detection, signals, risk, decision, reply); excludes STT, TTS and network",
        "steps": len(samples),
        "p50": round(percentile(samples, 50) or 0.0, 3),
        "p95": round(percentile(samples, 95) or 0.0, 3),
        "max": round(max(samples, default=0.0), 3),
    }


def headline(evals: list[Evaluated]) -> dict[str, Any]:
    s = safety_metrics(evals)
    return {
        "scenarios": len(evals),
        "scam_recall": s["scam_detection"]["recall"],
        "scam_precision": s["scam_detection"]["precision"],
        "legitimate_calls_ended": s["legitimate_calls_ended"],
        "protected_request_refused": s["protected_request_refused"],
        "prohibited_behavior_violations": s["prohibited_behavior_violations"],
        "all_checks": rate(sum(e.checks.passed for e in evals), len(evals)),
    }
