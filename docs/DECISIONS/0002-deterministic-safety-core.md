# ADR 0002 — Deterministic safety core with advisory models

* Status: accepted
* Date: 2026-11-18

## Context

Sparta answers calls from strangers, some of whom are trying to extract one-time passwords, PINs, payments or the owner's
whereabouts. Language models can be talked out of their instructions, can invent a request that was never made or miss one
that was, are slow and cost money per call, and cannot be audited line by line. The product brief asks that safety is
deterministic where possible, that classifications show their evidence, that the assistant never obeys a spoken
instruction to bypass policy, and that the product works without paid credentials. Callers also switch between English,
Hindi, Kannada and romanised mixtures within one call, so a rule that depends on first deciding the language would turn
safety off whenever that decision is wrong.

## Decision

1. **Decisions come from a pure engine and a versioned policy.** `ConversationEngine`
   (`services/api/src/sparta/orchestrator/engine.py`) has no I/O, no randomness and an injectable clock. For each caller
   turn it runs: language detection, signal detection, claim extraction, risk assessment, a decision table, a templated
   reply and output validation. The policy is data (`risk/policies/default-v1.toml`: signals, weights, thresholds, rules)
   and is stamped on every assessment by version. Scoring is a noisy-OR of signal weights, a floor for critical signals and
   a bounded legitimacy discount that never applies to a protected request.
2. **The assistant never writes free text.** Every utterance is a template from the language packs
   (`orchestrator/planner.py`) and passes `OutputValidator` (`orchestrator/validator.py`).
3. **Rules are merged across all supported language packs** (`language/registry.py`), so one rule fires in every language and
   a wrong language detection cannot disable it. The language detector is not a safety gate.
4. **Models are advisory.** With `SPARTA_LLM_PROVIDER=azure_openai` a model may return extra context signals; the engine
   keeps only the 13 codes in `MODEL_ALLOWED_SIGNALS`, only if the rules did not already raise them, with weight capped at
   0.6 and severity at `high`. It cannot raise protected-request or injection signals, cannot lower risk and cannot speak.
   Three tests in `services/api/tests/unit/test_engine.py` pin the allow-list, the weight cap and the rule that a model
   signal never lowers or removes what the rules found.
   An LLM summary is optional, rejected if it adds numbers, links or e-mail addresses that are not in its source, and always
   has the rules summary as the fallback. The model default is `rules` (no model).
5. **Protected information is a policy concept**: signals marked `protected` in the policy can never be fulfilled, by
   construction of the templates and the decision table.

## Consequences

* Positive: every decision can be explained with the signals and turns that caused it; the same input gives the same output
  (the simulator replay checksum and the evaluation harness both rely on this); the whole safety path runs without
  credentials and in unit tests; a model outage cannot stop screening.
* Positive: protection against spoken prompt injection does not depend on a model resisting it; there is no free-text
  output to hijack.
* Negative: recall is bounded by the vocabularies. Paraphrases, new scam scripts and unsupported languages are missed;
  [SAFETY_MODEL.md](../SAFETY_MODEL.md) section 8 lists verified misses. Held-out recall on the synthetic dataset is lower
  than on the development split the rules were tuned on ([eval/latest-test.md](../eval/latest-test.md)).
* Negative: every supported language needs vocabularies and templates reviewed by a native speaker; the Hindi and Kannada
  packs have not had that review.
* Negative: the assistant cannot hold a natural, open conversation. It asks for a name and a purpose, takes a message or
  ends the call.
* A model can still contribute to ending a call: two model-added signals reach the `high` threshold by noisy-OR.

## Alternatives considered

* **Model-first screening with rules as guardrails.** Rejected: a manipulated or mistaken model sits on the critical path,
  behaviour is not reproducible, and latency and cost accrue on every turn.
* **A model as the gate and rules as a fallback.** Rejected for the same reason on the critical path; it would also make
  results depend on the model version.
* **Free-text replies from a model, filtered afterwards.** Not wired in V1. The port (`generate_safe_reply`) and an Azure
  implementation exist, but no code calls them. A post-hoc filter can check for forbidden requests; it cannot prove a reply
  is safe in meaning, in Hindi and Kannada code-switched speech least of all.
* **A trained classifier.** Not available: no labelled multilingual dataset exists beyond the synthetic evaluation set.
  The conditions under which this could be explored are in [experiments/unsloth/README.md](../../experiments/unsloth/README.md).
