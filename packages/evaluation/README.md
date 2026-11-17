# Sparta evaluation package

Versioned, **synthetic, non-private** multilingual conversations used to measure the risk engine and the conversation
pipeline. No real phone numbers, names of real people, or real call data appear in the dataset.

* `scenario.schema.json` — JSON Schema for one scenario (one JSON object per line).
* `dataset/v1/dev.jsonl` — development split. Rules and lexicons may be tuned against these.
* `dataset/v1/test.jsonl` — **held-out** split. Never used to tune rules; only this split feeds the headline numbers in
  `docs/EVALUATION.md`.

The runner lives in `services/api/src/sparta/evaluation` and is invoked with `uv run sparta evaluate` (see
`docs/EVALUATION.md`). Results are written to `docs/eval/latest.json` and rendered into `docs/EVALUATION.md` strictly
from the run output; nothing is hand-written.

Important limitation: the dataset is synthetic and authored by the project, so it cannot represent the full diversity
of real calls, real speech-recognition errors, or adversaries who read the rules. Treat the numbers as a regression
signal, not as a claim about real-world accuracy.
