### Results on the `test` split (70 scenarios)

Generated 2026-11-17T19:56:24+00:00 by `sparta evaluate` (Sparta 0.1.0, policy 2026.11.2, language packs bn:1,en:1,hi:1,kn:1,ml:1,mr:1,ta:1,te:1). Dataset files and checksums: `test.jsonl` sha256 `51b96f447da2...`.

#### Safety

| Measure | Result | 95% interval |
| --- | --- | --- |
| Scam calls ended by the assistant | 82.0% (32/39) | 67.3% to 91.0% |
| Legitimate calls wrongly ended (false blocks, lower is better) | 4.8% (1/21) | 0.9% to 22.7% |
| Legitimate calls rated high risk (lower is better) | 14.3% (3/21) | 5.0% to 34.6% |
| Protected-information requests refused | 100.0% (35/35) | 90.1% to 100.0% |
| Prompt-injection attempts resisted (refused and call ended) | 75.0% (6/8) | 40.9% to 92.8% |
| Unwanted calls ended politely | 60.0% (3/5) | 23.1% to 88.2% |

Scam flagged (risk high or refuse/block/report): precision 91.2%, recall 75.6%, F1 82.7% (TP 31, FP 3, FN 10). Escalation to the owner: precision 66.7%, recall 85.7%. Prohibited assistant behaviours found: **0**; output-validator fallbacks: **0**.

#### Expectation checks

| Check | Result | 95% interval |
| --- | --- | --- |
| All checks pass for a scenario | 12.9% (9/70) | 6.9% to 22.7% |
| Risk level acceptable | 84.3% (59/70) | 74.0% to 91.0% |
| Category acceptable | 70.0% (49/70) | 58.5% to 79.5% |
| Final action acceptable | 82.9% (58/70) | 72.4% to 89.9% |
| Required signals recognised in the scripted call (per signal) | 67.9% (89/131) | 59.5% to 75.3% |
| Required signals raised before the assistant hung up (per signal) | 55.7% (73/131) | 47.2% to 63.9% |
| Forbidden signals raised (false alarms, lower is better) | 5.8% (5/87) | 2.5% to 12.8% |
| Escalation as expected | 82.9% (58/70) | 72.4% to 89.9% |
| Summary mentions the key facts | 40.0% (28/70) | 29.3% to 51.7% |

#### Language

| Measure | Result | 95% interval |
| --- | --- | --- |
| Per-turn language detected correctly (en/hi/kn/other) | 97.1% (165/170) | 93.3% to 98.7% |
| Call language profile exact match | 95.7% (67/70) | 88.1% to 98.5% |
| Code-switched calls (Hinglish, Kanglish, mixed): profile match | 97.1% (33/34) | 85.1% to 99.5% |

| Language | Precision | Recall | F1 |
| --- | --- | --- | --- |
| en-IN | 89.6% | 100.0% | 94.5% |
| hi-IN | 100.0% | 100.0% | 100.0% |
| kn-IN | 100.0% | 96.4% | 98.2% |
| other | 100.0% | 66.7% | 80.0% |

#### Slices

Tag slices with fewer than 5 scenarios are left out here (the JSON report has them all); intervals on the rest are wide.

| Slice | n | All checks | Scam flagged | Legitimate ended |
| --- | --- | --- | --- | --- |
| profile:english | 15 | 26.7% (4/15) | 75.0% (6/8) | 0.0% (0/5) |
| profile:hindi | 9 | 0.0% (0/9) | 80.0% (4/5) | 33.3% (1/3) |
| profile:hinglish | 15 | 6.7% (1/15) | 100.0% (9/9) | 0.0% (0/5) |
| profile:kanglish | 15 | 6.7% (1/15) | 80.0% (8/10) | 0.0% (0/4) |
| profile:kannada | 9 | 11.1% (1/9) | 60.0% (3/5) | 0.0% (0/2) |
| profile:mixed | 4 | 0.0% (0/4) | 33.3% (1/3) | 0.0% (0/1) |
| profile:unsupported | 3 | 66.7% (2/3) | 0.0% (0/1) | 0.0% (0/1) |
| tag:bank_otp | 7 | 0.0% (0/7) | 85.7% (6/7) | - |
| tag:escalate | 19 | 26.3% (5/19) | - | 5.3% (1/19) |
| tag:hard_negative | 7 | 0.0% (0/7) | - | 14.3% (1/7) |
| tag:legal_threat | 5 | 0.0% (0/5) | 80.0% (4/5) | - |
| tag:legitimate | 17 | 17.6% (3/17) | - | 5.9% (1/17) |
| tag:noisy_transcript | 18 | 5.6% (1/18) | 81.8% (9/11) | 0.0% (0/5) |
| tag:owner_probe | 8 | 0.0% (0/8) | 37.5% (3/8) | - |
| tag:prompt_injection | 8 | 0.0% (0/8) | 75.0% (6/8) | - |
| tag:slow_build | 5 | 0.0% (0/5) | 80.0% (4/5) | - |
| tag:upi_payment | 9 | 0.0% (0/9) | 77.8% (7/9) | - |
| tag:urgency | 8 | 0.0% (0/8) | 87.5% (7/8) | - |

#### Robustness to synthetic recognition noise

Words are dropped or have two letters swapped at the given rate (deterministic, seeded). This is not real ASR error.

| Noise | Scam recall | Legit calls ended | Protected requests refused | All checks |
| --- | --- | --- | --- | --- |
| none | 75.6% | 4.8% | 100.0% | 12.9% |
| 10% | 68.3% | 14.3% | 97.1% | 12.9% |
| 20% | 65.8% | 9.5% | 97.0% | 11.4% |
| 30% | 58.5% | 9.5% | 96.5% | 12.9% |

Decision latency: p50 82.123 ms, p95 146.943 ms, max 182.666 ms over 174 engine steps (decision logic only). Determinism: 0 of 70 scenarios differed between two runs.

#### Failing scenarios: 61

withheld: this split is held out and must not be used to tune the rules

#### Limitations

- The dataset is synthetic and written by the project (LLM-authored, not reviewed by native speakers); it cannot represent the diversity of real calls or adversaries who read the rules.
- Transcripts are scripted text. Real speech-recognition errors differ from the synthetic noise used here.
- Labels are one author's judgement; no inter-annotator agreement was measured.
- Small samples: individual language profiles have 3-15 scenarios, so intervals are wide.
- Latency covers the decision logic only; it excludes speech recognition, synthesis and network.
- The language detector is a script and lexicon heuristic, not a trained model.
