<!-- Thanks for contributing to Sparta. Keep this short and honest: say what you ran and what you did not. -->

## What and why

<!-- One or two sentences: the problem and the change. Link the issue if there is one (Closes #123). -->

## Area

- [ ] API (`services/api`)
- [ ] Web (`apps/web`)
- [ ] Android (`apps/android`)
- [ ] Infrastructure / CI (`infrastructure`, `.github`, `scripts`, Docker)
- [ ] Documentation only

## How it was verified

<!-- Commands you ran and their result. "Not run" is a fine answer when it is true: say why. -->

- [ ] `make check` (or `scripts\check.ps1`) passes, or the exceptions are explained below
- [ ] New behaviour has focused tests (and a failing test existed before a bug fix)
- [ ] I did not tune anything against the held-out **test** evaluation split (tune on `dev` only)

## Safety, privacy and security

- [ ] No secret, token, real phone number or real call content is in the diff, a fixture or a log line
- [ ] The assistant still discloses that it is an AI, and protected information is still refused by the deterministic rules
- [ ] No new data is stored or sent to a provider without being documented in `docs/PRIVACY.md`
- [ ] Not applicable (docs or tooling only)

## Contracts and docs

- [ ] If the HTTP API changed: `packages/contracts/openapi.json` is regenerated (`make openapi`) and `docs/API_CONTRACT.md` updated
- [ ] If configuration changed: `.env.example`, `docs/DEPLOYMENT.md` and the Bicep parameters are updated
- [ ] Documentation describes only what is implemented and verified; anything unverified is labelled UNVERIFIED

## Risk and rollback

<!-- What could go wrong in production, and how to roll back (see docs/DEPLOYMENT.md, "Rollback"). -->
