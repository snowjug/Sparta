# Security review

An automated security review of the backend (an AI agent, not a human penetration test) was run against commit
`62d7f7e`. Every finding was reproduced in-process against the real code before it was fixed. This page records what was
found, what changed, and what is still open. For the design-level view see [`THREAT_MODEL.md`](THREAT_MODEL.md).

## Findings and resolution

| # | Severity | Finding | Resolution (commit `117752e`) |
| --- | --- | --- | --- |
| 1 | Medium | A 1000-character turn could expand to about 18,000 characters under NFKD (one U+FDFA becomes 18), then about 50 rules ran twice over it; denial matching also grew quadratically with the number of sensitive-term mentions. Everything ran on the event loop: 6 to 21 s stalls were measured. | `sanitize_text` and `SignalDetector.detect` expand compatibility forms (NFKC) *before* capping, so the cap is real (`MAX_INPUT_CHARS` 1000, `MAX_DETECT_CHARS` 2048). Denial matching looks at the first 32 mentions only (`MAX_DENIAL_MENTIONS`); later mentions are simply not denied, so their signals still fire. |
| 2 | Medium | The per-owner-name matcher cache was unbounded; each new display name rebuilt the regexes (about 1 s of CPU) on the event loop. | LRU of 64 (`MAX_OWNER_DETECTORS`). Matchers are built in a worker thread when a profile is saved, a call is created or a preview runs (`CallService.warm_matchers`). `PUT /assistant-profile` is limited to 12 per minute (`SPARTA_PROFILE_WRITE_RATE_LIMIT_PER_MINUTE`). |
| 3 | Low | The WAV chunk walk was unbounded: a file of empty chunks kept the loop busy for about 0.5 s and skipped the duration limit; the declared byte rate was trusted. | The walk stops after 32 chunks; an unreadable header is a 422; for PCM the byte rate is capped at sample rate x channels x bits (`services/audio_validation.py`, `providers/stt/azure.py`). |
| 4 | Low | Invisible characters (soft hyphen, bidi marks, variation selectors, private use) became spaces *before* normalisation and split keywords; Cyrillic/Greek look-alikes ("оtp") were not folded. Text channels only: speech recognition does not produce these. | `normalize` deletes invisible characters and folds look-alikes inside words that are otherwise Latin; `sanitize_text` deletes them. See the open item below for zero-width joiners. |
| 5 | Low | Idempotent POSTs cached the full response (transcript text, notes) for 24 h and deletion or retention never removed those rows. | Responses of content-bearing routes (`/calls/{id}/turns`, `audio`, `silence`, `feedback`) are kept for 15 minutes, are not kept at all when the owner stores no transcripts (a 409 marker is stored instead), and are deleted with the call content or the call. |

Not scored by the reviewer, also addressed:

- **Development identity on a network address.** `python -m sparta serve` now refuses (exit code 2) to listen on a
  non-loopback address while the development identity is active, unless `SPARTA_ALLOW_NETWORK_DEV_AUTH=true`.
- **Unbounded screening events and slow purging.** Native screening events have a daily cap per owner
  (`SPARTA_DAILY_SCREENING_EVENT_CAP`, 2000) and a retention run purges in batches until the backlog is gone (up to
  10,000 calls per owner per run).
- **Hashes not enforced when building the image.** Owned by the infrastructure work; see `DEPLOYMENT.md`.

Measured after the fixes (one development machine, rules provider): an ordinary turn takes about 25 ms; the worst
adversarial inputs found (1000 characters of U+FDFA, a flood of "otp", with an equally bad previous turn) take 0.26 to
0.67 s. Building the matchers for a never-seen owner name takes about 1.1 s, now off the event loop.

## What is still open

- **The engine still runs on the event loop.** The bounded worst case above is a stall of well under a second per
  adversarial turn, at most 240 requests per minute per owner. A hostile owner of a multi-tenant deployment could still
  load a worker; running several worker processes limits the blast radius. A process pool would remove it.
- **Matchers are still built per owner name.** The cost moved off the event loop and is bounded, not removed. A
  structural fix would compile owner-independent patterns once and match the owner's name separately.
- **Zero-width (non-)joiners next to Indic letters remain word breaks.** This is the tokenisation the lexicons and the
  published evaluation were built on (Kannada and Hindi writers put one between a word and its suffix). A person typing
  into a text channel can therefore split an Indic keyword with one. Between Latin letters they are deleted.
- **Look-alike folding is partial.** Cyrillic and Greek letters are folded; other confusables (for example full
  Unicode UTS #39 skeletons) are not.
- **Not a human penetration test.** No fuzzing of the WebSocket protocol beyond the unit tests, no review of the web and
  Android apps by the security reviewer, and no test against live Azure services.

## Areas reviewed with no finding

Authentication (OIDC accepts RS256 only; required `iss`, `aud`, `exp`, `sub`; keys only from a pinned https JWKS URL
with no redirects; the development header is ignored in OIDC mode and refused in production); owner isolation (17
cross-owner probes returned 404); WebSocket tickets (192-bit, single use, bound to user and call, origin checked);
webhooks (JWT verified before parsing, constant-time HMAC compare, 300 s window, replay recorded only after the signature
verifies); outbound requests (hosts come from operator configuration, redirects are not followed); the safety core
(replies come from closed templates; the model can only add allow-listed signals with a capped weight); regular
expression backtracking (all merged vocabularies fuzzed at 2,000 characters, worst case 25 ms); secrets (no secrets in
tracked files or history); SQL (no string-built queries); logging (redaction held). Dependency audit of the Python lock:
`pip-audit` reports no known vulnerabilities.

## Reproducing the checks

```
cd services/api
python -m bandit -c pyproject.toml -r src
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip
python -m pytest tests/unit/test_signals.py tests/unit/test_text.py tests/unit/test_audio_validation.py tests/api/test_api_hardening.py
```

`pip-audit` needs network access.
