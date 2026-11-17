"""``sparta evaluate``: run a split of the scenario dataset through the engine and write the report."""

import argparse
import json
import sys
from pathlib import Path

from sparta.evaluation.dataset import DatasetError, load_split
from sparta.evaluation.report import (
    build_report,
    evaluate_split,
    noise_runs,
    nondeterministic,
    render_markdown,
)
from sparta.orchestrator.engine import ConversationEngine


def _path_for(template: str | None, split: str, many: bool) -> Path | None:
    if not template:
        return None
    if "{split}" in template:
        return Path(template.format(split=split))
    path = Path(template)
    return path.with_name(f"{path.stem}-{split}{path.suffix}") if many else path


def run_evaluation(args: argparse.Namespace) -> int:
    splits = ["dev", "test"] if args.split == "all" else [args.split]
    dataset_dir = Path(args.dataset)
    engine = ConversationEngine()
    exit_code = 0
    for split in splits:
        try:
            scenarios, info = load_split(dataset_dir, split)
        except DatasetError as exc:
            print(f"dataset error: {exc}", file=sys.stderr)
            return 2
        evals = evaluate_split(engine, scenarios)
        mismatches = nondeterministic(engine, scenarios, evals)
        noise = noise_runs(engine, scenarios) if args.stt_noise else []
        report = build_report(
            split=split,
            infos=[info],
            evals=evals,
            nondeterministic_ids=mismatches,
            noise=noise,
            engine=engine,
            include_failure_details=(split == "dev") or args.details,
        )
        out = _path_for(args.out, split, len(splits) > 1)
        md = _path_for(args.markdown, split, len(splits) > 1)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        if md is not None:
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(render_markdown(report), encoding="utf-8", newline="\n")
        head, safety = report["headline"], report["safety"]
        print(
            f"[{split}] {head['scenarios']} scenarios | all checks {head['all_checks']['k']}/{head['all_checks']['n']} | "
            f"scam recall {head['scam_recall']} precision {head['scam_precision']} | "
            f"legit ended {safety['legitimate_calls_ended']['k']}/{safety['legitimate_calls_ended']['n']} | "
            f"protected refused {safety['protected_request_refused']['k']}/{safety['protected_request_refused']['n']} | "
            f"violations {safety['prohibited_behavior_violations']} | fallbacks {safety['validator_fallbacks']} | "
            f"nondeterministic {len(mismatches)}"
        )
        if safety["prohibited_behavior_violations"] or safety["validator_fallbacks"] or mismatches:
            print(f"[{split}] INVARIANT VIOLATED: see the report", file=sys.stderr)
            exit_code = 1
    return exit_code
