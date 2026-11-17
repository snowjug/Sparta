# Release checklist

Copy this list into the release pull request or issue and tick it as you go. A box you cannot tick is a decision: write
down why you are releasing anyway, or stop. Anything that was not run is **UNVERIFIED** and belongs in the release notes.

Sparta is pre-1.0 and has no released version yet. Releases are tags `vMAJOR.MINOR.PATCH` on `main`; the **Container
images** workflow publishes `ghcr.io/<owner>/sparta-api` and `sparta-web` for tags and for `main`. Deployment steps are in
[`DEPLOYMENT.md`](DEPLOYMENT.md).

## 1. Scope and version

- [ ] The release content is agreed: what changes for owners, for API clients (web, Android), for operators.
- [ ] Versions are bumped together where they exist: `services/api/pyproject.toml` and `src/sparta/__init__.py`,
      `apps/web/package.json`, the Android `versionName` and `versionCode`.
- [ ] `packages/contracts/openapi.json` is current (`make openapi-check`) and, if the contract changed incompatibly, the web and
      Android apps in this release match it and `docs/API_CONTRACT.md` says so.
- [ ] Release notes are drafted (see the template at the end), including the UNVERIFIED list.

## 2. Quality gates (all of `main`, not just your branch)

- [ ] The `ci-ok` check is green on the commit to be tagged (backend, web, Android, infrastructure).
- [ ] `make check` (or `scripts\check.ps1 -Security`) passes locally on a clean checkout.
- [ ] PostgreSQL integration tests ran (`SPARTA_TEST_POSTGRES_URL` set to a throwaway database), not skipped.
- [ ] The evaluation gate passes (`python -m sparta evaluate --split dev` exits 0). If you publish new numbers, they come from
      a real run and `docs/EVALUATION.md` says how the splits were used. The held-out `test` split was **not** used for tuning
      ([`CONTRIBUTING.md`](../CONTRIBUTING.md)).
- [ ] Playwright end-to-end tests pass (they are informational in CI, so run `npm run e2e` yourself and read the report).
- [ ] The Android app was built (`assembleDebug`) and, for a release you will distribute, tested on a real device: the
      screening role cannot be verified in an emulator alone ([`ANDROID_SETUP.md`](ANDROID_SETUP.md)).

## 3. Safety and privacy gate

- [ ] The assistant still discloses that it is an AI in every supported language, and protected-information requests are
      still refused (the evaluation reports `protected refused` at 100% and `violations 0`).
- [ ] Defaults are unchanged or consciously changed and documented: raw audio storage off (and refused in production),
      transcripts kept 7 days, summaries 90 days, Personal Voice off, expensive features off ([`PRIVACY.md`](PRIVACY.md)).
- [ ] No new data is stored, logged or sent to a provider without an update to `PRIVACY.md` and the threat model
      ([`THREAT_MODEL.md`](THREAT_MODEL.md)). Logs and traces were spot-checked for transcript text and phone numbers.
- [ ] Any change to rules, lexicons or language packs went through the dev split and the tests, and a native speaker reviewed
      new Hindi or Kannada text before it was marked `supported` ([`SAFETY_MODEL.md`](SAFETY_MODEL.md)).

## 4. Security and supply chain

- [ ] CodeQL has no new open alerts; Dependabot and dependency-review findings are fixed or consciously deferred.
- [ ] `pip-audit -r requirements-dev.lock --no-deps --disable-pip` reports nothing; `requirements-dev.lock` was regenerated
      when dependencies changed, and so were the image locks (`make lock`: `requirements.lock`, `requirements-extras.lock`,
      `requirements-build.lock`). `make verify-locks` confirms every hash is a file digest that pypi.org publishes.
- [ ] The secret scan (gitleaks) is clean and no secret was ever committed; if one was, it was rotated first.
- [ ] The container scan (Trivy) passed for both images; a finding with no fix was reviewed and written down.
- [ ] GitHub Actions are pinned (first-party by major tag, others by commit SHA) and Dependabot is current.

## 5. Data, migrations and infrastructure

- [ ] New migrations are additive first (expand), reviewed, and were applied to a restored copy of production data. Destructive
      changes wait one release (contract).
- [ ] Infrastructure changes were previewed (`az deployment group what-if`, or **Deploy** with "what if only") and a human
      read the output.
- [ ] A backup or a point-in-time restore target is noted (time, server) before the deployment starts.
- [ ] Secrets that the release needs exist in Key Vault; secrets due for rotation are scheduled ([`DEPLOYMENT.md`](DEPLOYMENT.md),
      "Secrets and rotation").
- [ ] `NEXT_PUBLIC_*` repository variables hold this environment's values (they are compiled into the web image).
- [ ] Migrations that this release adds (see `services/api/migrations/versions`) are named in the release notes. Production
      does not migrate at startup: the **Deploy** workflow's migration job (or `python -m sparta migrate`) must run them, and
      a migration that new code cannot run without is applied BEFORE the new revision takes traffic ([`DEPLOYMENT.md`](DEPLOYMENT.md),
      "Migrations").

## 6. Legal and approvals (for anything that touches real calls or a new region)

- [ ] The legal-review checklist in [`DEPLOYMENT.md`](DEPLOYMENT.md#legal-and-approvals-checklist) is complete for every region and
      route you are enabling: AI disclosure, call-recording consent, call-interception rules, number acquisition, spam-reporting,
      retention, cross-border transfer, personalised voice, India-specific telecom and privacy obligations.
- [ ] Provider approvals exist where needed (for example Personal Voice Limited Access) and are recorded.
- [ ] The live-call test checklist in [`TELEPHONY.md`](TELEPHONY.md) (section 6) was run against a **test** number before any
      real owner's calls are forwarded. If it was not run, the release says live calling is UNVERIFIED.

## 7. Tag, publish, deploy

- [ ] Tag the commit: `git tag -a vX.Y.Z -m "Sparta vX.Y.Z"` and push the tag.
- [ ] The **Container images** run for the tag succeeded: both images scanned, then published with the `sha-<commit>`, version
      and `latest` tags.
- [ ] Deploy to a test or staging environment first: **Deploy** with the tag, review the what-if, approve the `production`
      (or staging) environment, wait for the migration job and the smoke test.
- [ ] Verify by hand: `/readyz` is 200; `GET /api/v1/system/status` shows `env: production`, `auth_mode: oidc`,
      `dev_banner: false`, the intended telephony provider and `simulated` flag; sign in with a bearer token from your
      identity provider (`curl -H "Authorization: Bearer ..." https://<api host>/api/v1/me`; the web app's own OIDC sign-in
      is unverified, so say so in the release notes if you rely on it); create nothing with real callers yet.
- [ ] Promote to production the same way, and watch logs, the alert rules and the readiness for at least 30 minutes.

## 8. Rollback readiness and after the release

- [ ] The previous image tag is written down and a rollback was rehearsed in test ([`DEPLOYMENT.md`](DEPLOYMENT.md), "Rollback").
- [ ] The GitHub release is published with the notes below; the milestone and `docs/IMPLEMENTATION_PLAN.md` are updated.
- [ ] Open items found during the release are filed as issues, not left in someone's head.

## Release notes template

```markdown
## Sparta vX.Y.Z

### What changed
- ...

### For operators
- Migrations: none | 0002 (additive) ...
- New or changed configuration: ...
- Rotate or add secrets: none | ...

### Known limitations and UNVERIFIED
- Live telephony: UNVERIFIED (no live ACS or carrier call has been made) | verified on <date> with <provider>
- Azure deployment: UNVERIFIED | verified in <environment> on <date>
- ...

### Evaluation
Dev split, from a real run on <date>: <one-line summary and a link to docs/eval>. The held-out test split was <not rerun | rerun as a new held-out run>.
```
