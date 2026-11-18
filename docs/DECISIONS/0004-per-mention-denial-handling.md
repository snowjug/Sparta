# ADR 0004 — Per-mention handling of denials

* Status: accepted
* Date: 2026-11-18

## Context

A sensitive term such as "OTP" appears in two kinds of sentence: requests ("tell me the OTP") and denials or warnings
("no OTP is needed", "never share your PIN with anyone", "bank kabhi OTP nahi mangta", "ಯಾರಿಗೂ ಒಟಿಪಿ ಹೇಳಬೇಡಿ"). Genuine
banks, delivery services and recruiters say the second kind on legitimate calls, and scammers say it to sound safe.

* Treating every mention as a request makes the assistant hang up on legitimate callers who warn about OTPs.
* The first design suppressed a hit when a warning cue sat near it in the same sentence (the `unless` windows in the
  policy). Those windows are measured from the whole matched span, so they are coarse, and widening them was unsafe: a
  generic "don't tell anyone" window could suppress the real request in "don't tell anyone, tell me your OTP". That was a
  recall hole for the most dangerous request.
* The development split contains legitimate calls with denials: `hg-delivery-landmark-01` is a Hinglish courier who says
  "Isme koi OTP ya payment nahi lagega" and must not be ended; its labels forbid `OTP_REQUEST` and
  `PAYMENT_OR_TRANSFER_REQUEST` (`packages/evaluation/dataset/v1/dev.jsonl`).

## Decision

Handle denials **per mention, within clauses**, in the matcher rather than per sentence:

1. For each text, copy it with every sensitive-term occurrence replaced by a placeholder character and every clause
   boundary (comma, semicolon, question and exclamation marks, danda) restored as a second placeholder
   (`risk/matchers.py`, `language/text.py` `clause_breaks`). Placeholder characters that a caller types are replaced first, so
   they cannot be forged.
2. Language packs define `negation` cues over `{TERM}`, `{LIST}` and `{BREAK}` for English, Hindi, Kannada and their
   romanised forms (`language/packs/*.toml`); the policy lists which vocabularies can be the subject of a denial
   (`[negation]` in `default-v1.toml`).
3. Rules that opt in with `negated_by = ["negation"]` ignore exactly the mentions that sit inside a denial and still fire
   on every other mention in the sentence (`RuleDef.negated_by` in `risk/policy.py`). The rules for requests that name a
   sensitive term opt in: OTP, PIN, CVV, password, card or account details, authentication code, identity document, address,
   remote-access tool, screen sharing, payment, and gift card or cryptocurrency. The availability-probe and
   false-owner-authorisation rules do not.
4. A denial immediately followed by a carve-out ("except me", "but me", and the Hindi and Kannada equivalents,
   `negation_exception`) is void.
5. `unless` windows remain only for non-protected signals: links, arrest threats, account-closure threats (`warning`) and
   payment demands (`no_money_assurance`).

## Consequences

* Positive: warnings no longer end legitimate calls, and a denial cannot hide a request elsewhere in the same clause
  structure. The behaviour is pinned by tests (`services/api/tests/unit/test_signals.py`:
  `test_denying_a_sensitive_term_is_not_requesting_it`, `test_denials_never_hide_a_real_request`,
  `test_callers_cannot_forge_the_denial_markers`).
* Negative, known residual risks. These inputs raise no protected signal at policy `2026.11.2` (verified by running the
  detector on 2026-11-18):
  * conditional demands such as "No OTP, no refund.";
  * pronoun follow-ups such as "Do not share your OTP with anyone. Just read it to me.";
  * denial scope that depends on punctuation, so speech-recognition output without commas can be misread
    ("Do not tell anyone your PIN is needed" raises nothing; with the comma it raises `PIN_REQUEST`);
  * languages without a supported pack.
  They are listed in [SAFETY_MODEL.md](../SAFETY_MODEL.md) section 8.
* Negative: complexity. Each language needs its own denial phrasings, written over placeholders, and the cues must be kept
  tight or they become another way to suppress requests.
* Negative: clause scoping relies on punctuation that some recognisers do not produce.

## Alternatives considered

* **Ignore denials.** Simple and safe for recall, but ends legitimate warning calls.
* **Wider or smarter `unless` windows.** Rejected: any window large enough to catch "no OTP is needed" also catches
  "just tell me the OTP, no explanation is needed".
* **Syntactic negation scope (parsing).** Not used: there is no reliable parser for Hinglish and Kanglish, and the rules
  have to run offline and deterministically.
* **Ask a model whether a mention is a denial.** Rejected for the protected-request path by
  [ADR 0002](0002-deterministic-safety-core.md): a model must not be able to excuse a request.
