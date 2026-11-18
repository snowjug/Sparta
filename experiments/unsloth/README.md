# Unsloth: optional research path, with a hard boundary

Status: **not started, and nothing in Sparta depends on it.** This directory holds a plan and the conditions for starting.
It contains no training code, no data and no model weights, and `services/` does not reference Unsloth or any fine-tuning
library (checked by searching the repository on 2026-11-18).

Unsloth is a library for fine-tuning and optimising open-source language models. It is training tooling for a research
workstation or CI job; it has no role in the web app, the Android app or the call path. It is documented here because the
product brief asks for a clearly bounded path rather than silently adding it, or silently ignoring it.

**The production MVP works without fine-tuning.** The call path is a deterministic engine with templated replies; an
optional hosted model may only add capped context signals ([ADR 0002](../../docs/DECISIONS/0002-deterministic-safety-core.md),
[SAFETY_MODEL.md](../../docs/SAFETY_MODEL.md)). Nothing in this directory changes that.

## The boundary: when any experiment may start

Work in this directory may begin only when **all** of the following are true. Each is a gate, and each has to be
demonstrable in writing, in the pull request that adds the experiment.

| Gate | What must exist | Where Sparta stands today |
| --- | --- | --- |
| 1. A labelled multilingual dataset | Real or properly sourced conversations in the target languages (English, Hindi, Kannada and their code-switched forms), labelled by more than one reviewer with measured agreement | Not met. The only data is the synthetic evaluation set: 70 development and 70 test scenarios, written by an AI assistant, labelled by one author, not reviewed by native speakers ([MANIFEST](../../packages/evaluation/dataset/v1/MANIFEST.md)). It is far too small and too artificial to train on or to make claims from |
| 2. Licensing | The licence of every dataset and every base model permits the intended use, including commercial use if relevant, and the terms are recorded | Not assessed. No model or dataset has been selected |
| 3. Privacy | The data was collected with consent for training; no private calls, no caller audio or transcripts from Sparta users, no personal data without a legal basis. Sparta stores no raw audio and does not train on calls by default ([PRIVACY.md](../../docs/PRIVACY.md) section 12) | Not met. No consented corpus exists, and the product's retention design removes verbatim speech after days |
| 4. Baselines | Evaluation results for the current rules on the same held-out data, from `python -m sparta evaluate` or an equivalent that is reviewed ([ADR 0005](../../docs/DECISIONS/0005-evaluation-discipline.md)) | Partly met: the rules baseline exists for the synthetic splits ([dev](../../docs/eval/latest-dev.md), [test](../../docs/eval/latest-test.md)). There is no baseline on real data |
| 5. Measurable gains | A held-out split that was not used for training or tuning, written independently of the training data, shows a gain over the baseline with intervals that exclude "no difference", and no worsening of the safety invariants (zero prohibited behaviours, zero validator fallbacks) | Not met. No candidate model exists |
| 6. Cost and latency | A written comparison of inference cost and added latency per turn (server or on device) against the rules baseline, within the product's latency budget, and a deployment plan | Not met. The existing evaluation latency covers decision logic only and excludes speech recognition, synthesis and network |

If a gate cannot be shown, the experiment does not start. Passing the gates allows a research branch; it does not by itself
allow a change to production behaviour.

## Where a model could fit (and where it may not)

Potential uses named in the brief, with how each would have to attach to the existing architecture:

| Potential use | Fit | Constraint |
| --- | --- | --- |
| Multilingual spam intent classification | Another source of advisory context signals through `ConversationModelProvider.evaluate_turn` | Signals only from the 13 codes in `MODEL_ALLOWED_SIGNALS`, capped weight, never protected-request or injection signals |
| Kannada-English (Kanglish) scam-signal detection | Same port; the current Kanglish vocabulary is the thing to beat | Same, and it must be measured on code-switched held-out data ([MULTILINGUAL_SPEECH.md](../../docs/MULTILINGUAL_SPEECH.md)) |
| Concise safe response generation | `generate_safe_reply` exists on the port but is not called by the call path | A generated reply would have to pass `OutputValidator` and a new decision recorded as an ADR; replies are templates today by design |
| Local or on-device classification | A small model running next to the Android screening rules | Needs its own size, latency and battery budget, and the Android app's 1.5 second decision budget ([ANDROID_SETUP.md](../../docs/ANDROID_SETUP.md)) |
| Lower-cost summary generation | `summarize_call`, already optional behind `SPARTA_FEATURE_LLM_SUMMARIES` | Output is rejected if it adds numbers, links or e-mail addresses that are not in the source; the rules summary stays the fallback |

A model never replaces the deterministic core: it cannot lower a risk score, cannot excuse a protected request and cannot
speak to a caller on its own.

## Rules for any future experiment

* **Never train on private calls by default.** Training data must be consented, documented and separate from production
  data. Owner feedback (`feedback` rows) must not be used for training without a separate, explicit opt-in, and it never
  changes production behaviour by itself today.
* **No automatic voice cloning** and no training on caller audio; Sparta does not keep audio.
* **No secrets or personal data in this repository.** Datasets and weights stay out of version control.
* **Keep the held-out discipline.** Use a new split for any model that is trained, report both splits, and state how many
  times each was run ([ADR 0005](../../docs/DECISIONS/0005-evaluation-discipline.md)).
* **Record the decision.** Adopting a model in production needs an ADR in `docs/DECISIONS/` that states the gains, the
  costs, the failure modes and how it is switched off.
* **Add dependencies only inside the experiment.** Training libraries must not enter `services/api/pyproject.toml`; the
  production service must not import them.
