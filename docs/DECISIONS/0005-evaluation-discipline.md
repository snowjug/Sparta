# ADR 0005 — Evaluation discipline

* Status: accepted
* Date: 2026-11-18

## Context

Sparta's safety claims are only worth something if they are measured, and a rule set that is tuned on the same data it is
scored on will look better than it is. There is no corpus of real, consented call recordings in different languages, so
the only data available is a synthetic dataset written by the project. The product brief forbids invented numbers and
requires that results come from real runs.

## Decision

1. **A versioned dataset with two splits.** `packages/evaluation/dataset/v1/` holds 70 development and 70 held-out test
   scenarios (`dev.jsonl`, `test.jsonl`) and a manifest with checksums and provenance (`MANIFEST.md`); their schema is
   `packages/evaluation/scenario.schema.json`. The scenarios are synthetic, written by an AI assistant, not reviewed by
   native speakers, and labelled by one author.
2. **Tune only on the development split.** Rules, lexicons and thresholds may be changed using `dev.jsonl` only. The test
   split exists to produce the reported numbers; per-scenario failures on it must not be used to decide what to change.
   The project owner's record ([EVALUATION.md](../EVALUATION.md) section 4) is that the test split was run once to produce
   the published numbers, with the engine as of commit `b09c936`, and that it was not re-run after later commits that
   changed code the run exercises (the input hardening in `117752e` among them; see
   [SECURITY_REVIEW.md](../SECURITY_REVIEW.md)). If it is ever used for tuning it is spent and a new held-out split must be
   written.
3. **The harness enforces what it can.** `python -m sparta evaluate` (`services/api/src/sparta/evaluation/`) runs the real
   engine on scripted turns with no language hint. It withholds failing test scenarios unless `--details` is given. It
   exits non-zero if any prohibited assistant behaviour (including leaking planted owner facts), any output-validator
   fallback or any non-deterministic scenario is found, so a CI job can gate on those invariants whatever the accuracy
   numbers are.
4. **Measure the conversation and the coverage separately.** Outcomes (ended, escalated, final action) come from the live,
   interactive run. Whether the rules *recognise* a signal in scripted turns the assistant never heard because it had
   already hung up is measured separately, on a shadow pass that does not change the call.
5. **Report honestly.** Both splits are published side by side with 95% Wilson intervals; every report ends with the
   limitations; a synthetic-noise sweep is labelled as not being real recogniser error. Reports are generated into
   `docs/eval/` by the tool and quoted in documents by copying, never by retyping from memory.

## Consequences

* Positive: a defensible estimate of generalisation on this dataset, a regression signal for every change, reproducible
  numbers, and hard safety invariants that cannot be traded against accuracy.
* Negative: the samples are small (3 to 15 scenarios per language profile), so intervals are wide.
* Negative: the data is synthetic and its labels are one author's judgement. The test scenarios were written after reading the
  development scenarios, with the same taxonomy and label conventions, so the held-out split is held out but not
  independent and is optimistic as a proxy for unseen real traffic.
* Negative: speech recognition is not part of the measurement: transcripts are scripted, so real recogniser errors, Azure
  language identification and audio conditions are untested.
* Negative: the published test numbers are now visible to everyone working on the rules, which makes it harder to keep
  future tuning clean; the next substantial rule change should come with a new held-out split.
* The development and test results differ (for example scam calls ended 97.4% on dev and 82.0% on test), which is the
  expected cost of tuning on dev and is why both are published ([eval/latest-dev.md](../eval/latest-dev.md),
  [eval/latest-test.md](../eval/latest-test.md)).

## Alternatives considered

* **One split, or cross-validation over all 140 scenarios.** Rejected: tuning and scoring would share data, and the
  authors could not say how much of the result was tuning.
* **Report development numbers only.** Rejected: they overstate performance.
* **Use real recordings.** Not available, and collecting them has consent and privacy obligations that the project does not
  take on by default ([PRIVACY.md](../PRIVACY.md)).
* **Score only the live outcome.** Rejected: an early hang-up hides whether the later lines would have been recognised,
  which matters for judging the rules.
