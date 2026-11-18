# Security review

Two automated security reviews of this repository were run by an AI agent (not a human penetration test): the first
against the backend at commit `62d7f7e`, the second, read-only, against everything that was new since then (the GitHub
Actions workflows, the Bicep, the Dockerfile, Compose and scripts, and the backend changes). Every finding was reproduced
in-process or by reading the code before it was fixed. This page records what was found, what changed, and what is still
open. For the design-level view see [`THREAT_MODEL.md`](THREAT_MODEL.md).

## Findings and resolution (first review)

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

## Second review (everything new since `62d7f7e`)

Three alerts were scored by the reviewer; testing by the documentation and web agents found three more defects in the
same code, one of them safety-relevant. All were reproduced before they were fixed.

| # | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| 1 | High | `deploy.yml` started on `workflow_run` of "Container images", filtered only by the head branch *name* and the conclusion. That workflow also runs for pull requests from forks, and a fork can have a branch called `main`, so a fork's commit could be checked out and deployed by the job that holds the Azure OIDC login and the production secrets. | Both the preflight and the deploy job require a successful run of a **push** to **this** repository's `main`. The commit must be a 40-hex SHA and an ancestor of `origin/main` (checked before it is checked out), and `image_tag` is validated (a newline could forge a second output line). `production` must be restricted to `main` with required reviewers; that is a GitHub setting, documented, not verified. Commit `0fd2a84`. |
| 2 | Medium | One user-assigned identity could read every Key Vault secret and was attached to the internet-facing web container, which needs none. Code execution in the web tier would have exposed the data keys, the pepper and the database login. | The web app has no identity unless a registry password is set (then its own identity, on that one secret). The API and the migration job get one `Key Vault Secrets User` assignment **per secret** they use, none on the vault. `0fd2a84`. Whether Azure accepts and honours a per-secret assignment is UNVERIFIED (nothing was deployed). |
| 3 | Low | `redact_owner_name` built its pattern from normalised words but searched the raw text, so "José", "Zoë", "Aaarav" and a nukta spelled the other way reached a model provider. | Words are compared in the detectors' canonical form on both sides; a possessive keeps its `'s`, a full name becomes one replacement. `2c63616`. |
| 4 | High (product safety) | The output validator took "Atharv" in "I'm Atharv Shukla's AI call assistant" for a claim to be the owner, so for any owner with a two-word name the default and the formal opening were replaced by "I can't share any personal details": the call began **without disclosing that it is an AI**. Tests and the evaluation used the one-word name "Atharv". | The claim check judges a full name as a whole. Regression tests cover every template, language and style for five full names, and the engine opening. `531e665`. |
| 7 | High (product safety) | The same failure with a different trigger, found by **GitHub's first Playwright run** (the end-to-end owner is a random id and one had four digits in a row): the validator judged the owner's display name as something the assistant *said*. A name with four digits, a phone-like number, a link-like word or an e-mail address (the `preferred_username` Entra ID sends when an account has no name) failed the number or link rule on every opening, so the call again began without saying it is an AI. | The name-dependent rules look at the same line in generic wording; if the line with the name still fails it is spoken without the name before the non-disclosing deflection is ever used; an e-mail address is not read aloud; the possessive check accepts `Doe, Jane`. 26 new tests fail on the old engine. `5f980d1`. |
| 5 | Medium | FastAPI 0.162's own OpenTelemetry instrumentation, active whenever a global provider exists (OTLP configured), exported the raw URL path and the full query string (a history search term is content), adopted a caller-supplied `traceparent` as the trace id and duplicated Sparta's request span. | Switched off (feature-detected); the tracing tests now run with a global provider configured, and 5 of 8 of them fail without the fix. `2c63616`. |
| 6 | Medium | `idempotency_keys.request_hash` was a bare SHA-256 of route + body, so a database reader could confirm guessed phone numbers (a blocked or trusted caller's number is in the body). | An HMAC keyed with the pepper and scoped to the owner. Removing a blocked or trusted entry also forgets the cached response that added it. `2c63616`. |

Also fixed because the same review or the testing found them:

- **Migrations were skipped on every automatic deployment.** `inputs.*` is null on the `workflow_run` trigger and
  `null != false` is false in a workflow expression. The step now runs explicitly on that trigger (`0fd2a84`).
- **`/readyz` did not wait for migrations**, so a new revision could take traffic before the migration job had run
  (`4316669`). Whether Container Apps keeps the old revision until the new one is ready is UNVERIFIED.
- **The daily screening-event cap counted the client's `occurred_at`**, which can be backdated a week; it now counts what
  the server received (`2c63616`).
- **`POST /simulator/replay` answered 500 when replays overlapped**: the driver gave up after 1500 polls of a 4 ms sleep,
  which on Windows is about 1.6 s. It waits by a 30 s wall-clock deadline and a real timeout is a 503 (`2ea11c5`).
- **A regex of my own added in the first fix of #4 backtracked exponentially** for a name such as "Anil A. A." (found by
  the reviewer on the uncommitted code, 1.1 s at 72 characters, 4.7 s at 78); names are now split on spaces and dots,
  deduplicated, and the checked text is capped (`531e665`).
- CI path filter ignored renames out of `services/api`, and its helper failed on a long file list; the gitleaks
  allowlist exempted any `build/`, `dist/` or `coverage/` directory at any depth (now exact paths, and a planted key
  under each of them is detected) (`0fd2a84`).

Checked with no finding: no `${{ }}` in any `run:` block, no `pull_request_target`, least-privilege job permissions,
third-party actions pinned by SHA (verified against the tags on GitHub), no secret in Bicep outputs or parameters,
PostgreSQL and Redis private with TLS by default, a non-root image with nothing baked into layers, loopback-only ports in
Compose, spans that carry identifiers and timings only, an atomic event counter, and `kv.py` (single-use `GETDEL`
tickets, token-checked lock release).

**Not reviewed by the reviewer:** `apps/web`, `apps/android`, the language packs and evaluation diffs, and every GitHub
and Azure *setting* (branch protection, environment reviewers, fork-approval rules, the role assignments actually
granted). The CI workflows ran on GitHub only after this review, on pull request 1; its CodeQL analysis found four further
alerts in the same code (a short key in a test, a case-sensitive tag regexp in a test, two regex-range warnings), all
resolved. The deploy workflow and anything on Azure have not run.

## What is still open

- **The engine still runs on the event loop.** The bounded worst case above is a stall of well under a second per
  adversarial turn, at most 240 requests per minute per owner. A hostile owner of a multi-tenant deployment could still
  load a worker; running several worker processes limits the blast radius. A process pool would remove it.
- **Matchers are still built per owner name.** The cost moved off the event loop and is bounded, not removed. A
  structural fix would compile owner-independent patterns once and match the owner's name separately.
- **Zero-width (non-)joiners next to Indic letters remain word breaks.** This is the tokenisation the lexicons and the
  published evaluation were built on (Kannada and Hindi writers put one between a word and its suffix). A person typing
  into a text channel can therefore split an Indic keyword with one. Between Latin letters they are deleted.
- **Look-alike folding is partial.** Cyrillic and Greek letters are folded; other confusables (Armenian "օ", full
  Unicode UTS #39 skeletons) are not.
- **`/readyz` is unauthenticated and not cached**: two database queries and a Redis ping per call. Platform probes call it
  every few seconds; a public caller could add load, so rate-limit it at the ingress.
- **Deployment defaults that are documented, not changed:** Key Vault is reachable on its public endpoint (every call
  needs Entra authentication), the application connects to PostgreSQL as its administrator, and `ssl=require` encrypts
  without verifying the certificate ([`DEPLOYMENT.md`](DEPLOYMENT.md)). Per-secret role assignments for the database and
  Redis URLs are created late in the deployment, so a first deployment may need a re-run.
- **Secret scanning has limits.** gitleaks' own built-in rules ignore any `node_modules/` and any `package-lock.json`, at
  any depth, and a pull request can edit `.gitleaks.toml` itself: code-owner review of that file is the control.
- **Release supply chain.** The published image is a second build from the build cache, not the exact scanned artifact
  (pushing the scanned image would drop its provenance and SBOM attestations), and any commit tagged `v*.*.*` publishes,
  so restrict who can create `v*` tags.
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
python -m pytest tests/unit/test_signals.py tests/unit/test_text.py tests/unit/test_audio_validation.py tests/api/test_api_hardening.py tests/api/test_api_tracing.py tests/unit/test_planner_validator.py tests/unit/test_transactions.py
```

`pip-audit` needs network access.
