# Sparta evaluation package

Versioned, **synthetic, non-private** multilingual conversations used to measure the risk engine and the conversation
pipeline. No real phone numbers, names of real people, or real call data appear in the dataset.

* `scenario.schema.json` — JSON Schema for one scenario (one JSON object per line).
* `dataset/v1/dev.jsonl` — development split. Rules and lexicons may be tuned against these.
* `dataset/v1/test.jsonl` — **held-out** split. Never used to tune rules; only this split feeds the headline numbers in
  `docs/EVALUATION.md`.
* `dataset/v1/MANIFEST.md` — counts, checksums, provenance and limitations, generated from the two files.

The runner lives in `services/api/src/sparta/evaluation` and is invoked with `python -m sparta evaluate` from
`services/api` (or `uv run sparta evaluate`; see `docs/EVALUATION.md` for the exact commands). Reports are written with
`--out` and `--markdown` (for example `docs/eval/latest-dev.json|md` and `docs/eval/latest-test.json|md`) strictly from
the run output; nothing in them is hand-written.

Important limitation: the dataset is synthetic and authored by the project, so it cannot represent the full diversity
of real calls, real speech-recognition errors, or adversaries who read the rules. Treat the numbers as a regression
signal, not as a claim about real-world accuracy.
