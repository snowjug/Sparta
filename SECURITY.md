# Security policy

Sparta handles call content and personal data, and it decides what an automated assistant may say to a stranger on the
phone. Security problems and **safety** problems (the assistant doing something it must never do) are both taken
seriously.

## Reporting a vulnerability

**Do not open a public issue, pull request or discussion for a vulnerability.** Report it privately with a GitHub
security advisory:

<https://github.com/snowjug/Sparta/security/advisories/new>

Include what you can: the affected component and commit, the impact, steps or a proof of concept, and whether you have
shared the details with anyone else. **Use synthetic data only.** Never include real call recordings, transcripts, phone
numbers, access tokens or keys in a report; if you found real secrets or personal data, say where, and do not copy them.

The response targets below are goals for a small project run by one owner, not guarantees or a service-level agreement:

| Step | Goal |
| --- | --- |
| Acknowledge your report | within 3 working days |
| Initial assessment (accepted, needs information, or not a vulnerability) | within 7 days |
| Fix or mitigation for a critical or high issue | as soon as practicable, aiming for 30 days |
| Fix for a medium or low issue | in a normal release |
| Public disclosure (advisory, and credit if you want it) | after a fix is available, agreed with you |

If a deadline slips you will be told why. If you do not hear back, comment on your advisory.

Acting in good faith (you test only your own deployment or a local copy, stop when you reach personal data, report
promptly and keep the details private until a fix exists) is welcome, and the intention is not to take action against
researchers who do. This is a statement of intent by the maintainer, not legal advice or a legal safe harbour.

## Supported versions

Sparta is pre-1.0 and has no released versions yet. Only the latest commit on `main` is supported: security fixes land on
`main`, and a tagged release (`v*`) is cut from it when there is something to ship. Once releases exist, this table will
list the supported ones.

| Version | Supported |
| --- | --- |
| `main` (latest commit) | yes |
| anything else | no |

## Scope

In scope:

* **Backend API** (`services/api`): authentication and authorisation, access to another owner's data, forged provider
  webhooks and WebSocket tickets, injection, request-forgery and file-handling bugs, secrets or personal data in logs
  and telemetry, rate-limit and cost-guardrail bypasses, weaknesses in field encryption and key handling.
* **Safety behaviour:** any way for a caller (spoken or typed) to make the assistant request, accept or reveal protected
  information, omit that it is an AI, or be talked out of its deterministic rules (prompt injection, language tricks,
  code-switching, obfuscation). Report these privately like any vulnerability.
* **Web app** (`apps/web`): cross-site scripting, content-security-policy bypasses, token handling, open redirects.
* **Android app** (`apps/android`): exported components, permission misuse, insecure local storage, insecure transport.
* **Infrastructure and delivery** (`infrastructure`, `.github`, `Dockerfile`s, `scripts`): secret exposure,
  over-broad permissions, workflow injection, supply-chain weaknesses.

Out of scope:

* Vulnerabilities in third-party services (Azure, GitHub, your telephony provider): report those to the vendor.
* A deployment that you configured unsafely. The **development identity** (`SPARTA_AUTH_MODE=dev`) is unauthenticated by
  design and refuses to run with `SPARTA_ENV=production`; exposing it on an untrusted network is a configuration error.
  A way to enable it silently in production *is* in scope.
* Denial of service by raw network volume, social engineering of the maintainer, physical attacks.
* Reports from automated scanners without a demonstrated impact on Sparta, and missing hardening headers on endpoints
  that carry no data.
* Known issues listed as limitations in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) (residual risks), unless you can
  show a worse impact than described.

## What is already in place

The threat model and the controls behind these are in [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md),
[`docs/SAFETY_MODEL.md`](docs/SAFETY_MODEL.md) and [`docs/PRIVACY.md`](docs/PRIVACY.md). In short:

* no secret is committed; production reads secrets only from Azure Key Vault through a managed identity
  ([`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md));
* production refuses to start with the development identity, SQLite, missing keys, missing Redis, wildcard CORS or hosts;
* call content is encrypted in the application before it reaches the database, with key rotation;
* logs and traces are redacted and never carry transcript text or phone numbers;
* CI runs `ruff`, `mypy`, tests, `bandit`, `pip-audit`, CodeQL, dependency review, secret scanning (gitleaks) and a
  container vulnerability scan; Dependabot keeps dependencies and GitHub Actions current;
* the API container image installs every third-party package from sha256-pinned lock files with `--require-hashes`
  (runtime dependencies only, no test or lint tools), and CI checks that each locked hash is a file digest that pypi.org
  publishes (see "The container images" in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)).

The CI workflows ran on GitHub for the first time on pull request 1. On `main` the publish workflow has since pushed both
images to GHCR and the deploy workflow has skipped itself (the Azure repository variables are not set); the deploying job
has not run, and nothing has been deployed to Azure by the authors; see "What is not verified" in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## If you committed a secret

Treat it as compromised: rotate it first (see "Secrets and rotation" in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)),
then remove it from the code. Deleting a commit does not un-leak a secret that was already pushed.
