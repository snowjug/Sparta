"""Builds the evaluation report (JSON and Markdown) strictly from run output. Nothing in it is hand-written."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sparta import __version__
from sparta.evaluation import metrics as mx
from sparta.evaluation.checks import evaluate
from sparta.evaluation.dataset import DatasetInfo, Scenario
from sparta.evaluation.noise import NoiseModel
from sparta.evaluation.runner import run_scenario
from sparta.orchestrator.engine import ConversationEngine

REPORT_VERSION = 1
MIN_TAG_SLICE = 5  # smaller tag slices are noise in the Markdown view; the JSON report keeps every slice
NOISE_LEVELS = (0.1, 0.2, 0.3)
LIMITATIONS = [
    "The dataset is synthetic and written by the project (LLM-authored, not reviewed by native speakers); it "
    "cannot represent the diversity of real calls or adversaries who read the rules.",
    "Transcripts are scripted text. Real speech-recognition errors differ from the synthetic noise used here.",
    "Labels are one author's judgement; no inter-annotator agreement was measured.",
    "Small samples: individual language profiles have 3-15 scenarios, so intervals are wide.",
    "Latency covers the decision logic only; it excludes speech recognition, synthesis and network.",
    "The language detector is a script and lexicon heuristic, not a trained model.",
]


def evaluate_split(
    engine: ConversationEngine, scenarios: Sequence[Scenario], *, noise: NoiseModel | None = None
) -> list[mx.Evaluated]:
    return [mx.Evaluated(r, evaluate(r)) for r in (run_scenario(engine, s, noise=noise) for s in scenarios)]


def nondeterministic(
    engine: ConversationEngine, scenarios: Sequence[Scenario], evals: Sequence[mx.Evaluated]
) -> list[str]:
    """Scenario ids whose outcome differs between two runs of the same input (there should be none)."""
    return [
        e.scenario.id
        for e, s in zip(evals, scenarios, strict=True)
        if run_scenario(engine, s).signature() != e.result.signature()
    ]


def noise_runs(engine: ConversationEngine, scenarios: Sequence[Scenario]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for level in NOISE_LEVELS:
        evals = evaluate_split(engine, scenarios, noise=NoiseModel(level))
        safety = mx.safety_metrics(evals)
        runs.append(
            {
                "noise_level": level,
                "scam_recall": safety["scam_detection"]["recall"],
                "scam_precision": safety["scam_detection"]["precision"],
                "legitimate_calls_ended": safety["legitimate_calls_ended"],
                "protected_request_refused": safety["protected_request_refused"],
                "prohibited_behavior_violations": safety["prohibited_behavior_violations"],
                "all_checks": mx.rate(sum(e.checks.passed for e in evals), len(evals)),
            }
        )
    return runs


def _failure(e: mx.Evaluated) -> dict[str, Any]:
    exp, res = e.scenario.expected, e.result
    return {
        "id": e.scenario.id,
        "profile": e.scenario.language_profile,
        "failed_checks": e.checks.failed,
        "expected": {
            "risk_level": [r.value for r in exp.risk_level_acceptable],
            "category": [c.value for c in exp.category_acceptable],
            "action": [a.value for a in exp.action_acceptable],
            "should_escalate": exp.should_escalate,
            "must_end_call": exp.must_end_call,
            "must_not_end_call": exp.must_not_end_call,
        },
        "got": {
            "risk_level": res.risk_level,
            "category": res.category,
            "action": res.action,
            "escalated": res.escalated,
            "ended": res.ended,
            "language_profile": res.profile,
        },
        "missing_signals": e.checks.missing_signals,
        "missing_signals_live": e.checks.missing_signals_live,
        "unexpected_signals": e.checks.unexpected_signals,
        "summary_problems": e.checks.summary_problems,
        "violations": list(e.checks.violations),
    }


def build_report(
    *,
    split: str,
    infos: Sequence[DatasetInfo],
    evals: Sequence[mx.Evaluated],
    nondeterministic_ids: Sequence[str],
    noise: Sequence[dict[str, Any]],
    engine: ConversationEngine,
    include_failure_details: bool,
) -> dict[str, Any]:
    items = list(evals)
    failing = [e for e in items if not e.checks.passed]
    return {
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sparta_version": __version__,
        "policy_version": engine.policy.version,
        "language_pack_version": engine.planner.registry.version(),
        "dataset": {
            "version": "v1",
            "files": [{"file": i.file, "scenarios": i.scenarios, "bytes": i.bytes, "sha256": i.sha256} for i in infos],
        },
        "split": split,
        "headline": mx.headline(items),
        "safety": mx.safety_metrics(items),
        "checks": mx.check_rates(items),
        "language": mx.language_metrics(items),
        "slices": mx.slice_metrics(items),
        "latency_ms": mx.latency_metrics(items),
        "determinism": {"scenarios_checked": len(items), "mismatches": list(nondeterministic_ids)},
        "noise_robustness": list(noise),
        "failures": (
            {"count": len(failing), "details": [_failure(e) for e in failing]}
            if include_failure_details
            else {
                "count": len(failing),
                "details": "withheld: this split is held out and must not be used to tune the rules",
            }
        ),
        "limitations": LIMITATIONS,
    }


# ------------------------------------------------------------------------------------------------ markdown
def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _rate_row(label: str, r: dict[str, Any] | None) -> str:
    if r is None or r["n"] == 0:
        return f"| {label} | n/a | 0 |"
    low, high = r["ci95"]
    return f"| {label} | {_pct(r['rate'])} ({r['k']}/{r['n']}) | {_pct(low)} to {_pct(high)} |"


def render_markdown(report: dict[str, Any]) -> str:
    s, c, lang = report["safety"], report["checks"], report["language"]
    lines = [
        f"### Results on the `{report['split']}` split ({report['headline']['scenarios']} scenarios)",
        "",
        f"Generated {report['generated_at']} by `sparta evaluate` (Sparta {report['sparta_version']}, policy "
        f"{report['policy_version']}, language packs {report['language_pack_version']}). Dataset files and checksums: "
        + ", ".join(f"`{f['file']}` sha256 `{f['sha256'][:12]}...`" for f in report["dataset"]["files"])
        + ".",
        "",
        "#### Safety",
        "",
        "| Measure | Result | 95% interval |",
        "| --- | --- | --- |",
        _rate_row("Scam calls ended by the assistant", s["scam_calls_ended"]),
        _rate_row("Legitimate calls wrongly ended (false blocks, lower is better)", s["legitimate_calls_ended"]),
        _rate_row("Legitimate calls rated high risk (lower is better)", s["legitimate_calls_rated_high"]),
        _rate_row("Protected-information requests refused", s["protected_request_refused"]),
        _rate_row("Prompt-injection attempts resisted (refused and call ended)", s["prompt_injection_resisted"]),
        _rate_row("Unwanted calls ended politely", s["unwanted_calls_ended"]),
        "",
        f"Scam flagged (risk high or refuse/block/report): precision {_pct(s['scam_detection']['precision'])}, "
        f"recall {_pct(s['scam_detection']['recall'])}, F1 {_pct(s['scam_detection']['f1'])} "
        f"(TP {s['scam_detection']['tp']}, FP {s['scam_detection']['fp']}, FN {s['scam_detection']['fn']}). "
        f"Escalation to the owner: precision {_pct(s['escalation']['precision'])}, "
        f"recall {_pct(s['escalation']['recall'])}. "
        f"Prohibited assistant behaviours found: **{s['prohibited_behavior_violations']}**; "
        f"output-validator fallbacks: **{s['validator_fallbacks']}**.",
        "",
        "#### Expectation checks",
        "",
        "| Check | Result | 95% interval |",
        "| --- | --- | --- |",
        _rate_row("All checks pass for a scenario", c["all_checks"]),
        _rate_row("Risk level acceptable", c["risk_level"]),
        _rate_row("Category acceptable", c["category"]),
        _rate_row("Final action acceptable", c["action"]),
        _rate_row("Required signals recognised in the scripted call (per signal)", c["required_signal_recall"]),
        _rate_row(
            "Required signals raised before the assistant hung up (per signal)", c["required_signal_recall_live"]
        ),
        _rate_row("Forbidden signals raised (false alarms, lower is better)", c["forbidden_signal_false_alarms"]),
        _rate_row("Escalation as expected", c["escalation"]),
        _rate_row("Summary mentions the key facts", c["summary"]),
        "",
        "#### Language",
        "",
        "| Measure | Result | 95% interval |",
        "| --- | --- | --- |",
        _rate_row("Per-turn language detected correctly (en/hi/kn/other)", lang["turn_accuracy"]),
        _rate_row("Call language profile exact match", lang["call_profile_accuracy"]),
        _rate_row(
            "Code-switched calls (Hinglish, Kanglish, mixed): profile match", lang["code_switch_profile_accuracy"]
        ),
        "",
        "| Language | Precision | Recall | F1 |",
        "| --- | --- | --- | --- |",
    ]
    for code, m in lang["per_language"].items():
        lines.append(f"| {code} | {_pct(m['precision'])} | {_pct(m['recall'])} | {_pct(m['f1'])} |")
    lines += [
        "",
        "#### Slices",
        "",
        f"Tag slices with fewer than {MIN_TAG_SLICE} scenarios are left out here (the JSON report has them all); "
        "intervals on the rest are wide.",
        "",
        "| Slice | n | All checks | Scam flagged | Legitimate ended |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, m in report["slices"].items():
        if name.startswith("tag:") and m["n"] < MIN_TAG_SLICE:
            continue
        scam = (
            "-"
            if m["scam_flagged"] is None
            else f"{_pct(m['scam_flagged']['rate'])} ({m['scam_flagged']['k']}/{m['scam_flagged']['n']})"
        )
        legit = (
            "-"
            if m["legitimate_ended"] is None
            else f"{_pct(m['legitimate_ended']['rate'])} ({m['legitimate_ended']['k']}/{m['legitimate_ended']['n']})"
        )
        passed = m["all_checks"]
        lines.append(f"| {name} | {m['n']} | {_pct(passed['rate'])} ({passed['k']}/{passed['n']}) | {scam} | {legit} |")
    if report["noise_robustness"]:
        lines += [
            "",
            "#### Robustness to synthetic recognition noise",
            "",
            "Words are dropped or have two letters swapped at the given rate (deterministic, seeded). This is not real ASR error.",
            "",
            "| Noise | Scam recall | Legit calls ended | Protected requests refused | All checks |",
            "| --- | --- | --- | --- | --- |",
        ]
        base = report["safety"]
        lines.append(
            f"| none | {_pct(base['scam_detection']['recall'])} | {_pct(base['legitimate_calls_ended']['rate'])} | "
            f"{_pct(base['protected_request_refused']['rate'])} | {_pct(report['checks']['all_checks']['rate'])} |"
        )
        for run in report["noise_robustness"]:
            lines.append(
                f"| {int(run['noise_level'] * 100)}% | {_pct(run['scam_recall'])} | "
                f"{_pct(run['legitimate_calls_ended']['rate'])} | {_pct(run['protected_request_refused']['rate'])} | "
                f"{_pct(run['all_checks']['rate'])} |"
            )
    lat = report["latency_ms"]
    det = report["determinism"]
    lines += [
        "",
        f"Decision latency: p50 {lat['p50']} ms, p95 {lat['p95']} ms, max {lat['max']} ms over {lat['steps']} engine "
        f"steps (decision logic only). Determinism: {len(det['mismatches'])} of {det['scenarios_checked']} scenarios "
        "differed between two runs.",
        "",
    ]
    failures = report["failures"]
    lines.append(f"#### Failing scenarios: {failures['count']}")
    if isinstance(failures["details"], str):
        lines += ["", failures["details"], ""]
    else:
        lines += [
            "",
            "| Scenario | Failed checks | Expected (level / action) | Got (level / action) |",
            "| --- | --- | --- | --- |",
        ]
        for f in failures["details"]:
            lines.append(
                f"| `{f['id']}` | {', '.join(f['failed_checks'])} | {'/'.join(f['expected']['risk_level'])} / "
                f"{'/'.join(f['expected']['action'])} | {f['got']['risk_level']} / {f['got']['action']} |"
            )
        lines.append("")
    lines += ["#### Limitations", ""] + [f"- {item}" for item in report["limitations"]] + [""]
    return "\n".join(lines)
