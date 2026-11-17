# Contributing to Sparta

Thanks for helping. Sparta is a multilingual AI call-screening assistant: a FastAPI backend (`services/api`), a Next.js web
app (`apps/web`), a native Android app (`apps/android`), an evaluation dataset and contract (`packages`), and the
infrastructure and delivery pipeline (`infrastructure`, `.github`, `scripts`). Read the [README](README.md) first, then
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Two rules sit above everything else:

1. **Safety before cleverness.** The assistant always says it is an AI, never asks for protected information, and refuses
   a caller who asks for it. Those behaviours come from deterministic rules, not from a model's goodwill
   ([`docs/SAFETY_MODEL.md`](docs/SAFETY_MODEL.md)). A change that weakens them needs a very good reason and a test.
2. **Honesty.** Documentation describes what exists and was verified. If you could not run something (a real call, an
   Azure deployment, a GitHub Actions run), say so and mark it **UNVERIFIED** with the reason. Never invent numbers.

## Set up

You need Git, Python 3.12, and for the web app Node.js 22.12 or newer. Docker is optional (PostgreSQL and Redis in
containers); the JDK 17 and Android SDK are only for the Android app.

Windows (PowerShell 5.1 or newer; `make` is not needed):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force   # this window only, if scripts are blocked
.\scripts\bootstrap.ps1          # Python environment, locked dependencies, npm ci, .env
.\scripts\dev.ps1                # API (SQLite, simulator) + web; add -Docker for PostgreSQL and Redis
```

Linux, macOS, WSL or Git Bash:

```bash
make bootstrap
make dev                         # make dev-docker adds PostgreSQL and Redis
```

Open <http://localhost:3000/simulator> and run a scenario. Everything runs on the built-in simulator: no cloud account, no
cost, no real phone call. Run `make help` (or `.\scripts\tasks.ps1 help`) for every task. The scripts stop with a plain
explanation when Python, Node or Docker is missing.

Configuration is environment variables: copy `.env.example` to `.env` (the setup does it for you). Never commit `.env`.

Prefer containers? `docker compose up --build` starts PostgreSQL, Redis, the API and the web app (`docker compose up -d --build
postgres redis api` starts only the backend). Check a running API with
`make smoke` or `.\scripts\smoke.ps1`. The compose stack uses the development identity (no sign-in) and sets
`SPARTA_ALLOW_NETWORK_DEV_AUTH=true`, which the API requires before it listens on `0.0.0.0` inside its container with
that identity; every published port is bound to `127.0.0.1`, so it is for a **trusted local machine only**. Never copy that
setting to a shared or public host (production uses OIDC, where it has no effect).

## Branches, commits and pull requests

* Branch from `main`: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, `chore/<topic>`.
* Commit messages follow Conventional Commits, as in the history: `type(scope): summary`, for example
  `feat(api): readable startup failures when the database or Redis is unreachable` or `fix(android): ...`. Types:
  `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`. Keep commits focused and the summary under about
  80 characters; explain *why* in the body when it is not obvious.
* Open a pull request against `main` and fill in the template. CI path-filters the jobs to what you changed; the
  `ci-ok` check must pass. A reviewer from `CODEOWNERS` approves.
* Do not push secrets, real phone numbers, real transcripts or recordings, in code, tests, fixtures, logs or screenshots.
  Use synthetic data. gitleaks runs on every pull request.

## Test commands, by component

The one-liner for everything CI checks is `make check` (or `.\scripts\check.ps1`; `-Fast` skips the slow steps).

**API** (`services/api`, with the environment activated or via `.venv\Scripts\python.exe -m ...`):

```bash
python -m ruff check .
python -m ruff format --check .        # python -m ruff format . to fix
python -m mypy src
python -m pytest tests
python -m sparta openapi --check       # python -m sparta openapi to regenerate packages/contracts/openapi.json
python -m sparta evaluate --split dev  # exits non-zero when a safety invariant fails
python -m bandit -q -c pyproject.toml -r src
python -m pip_audit -r requirements-dev.lock --no-deps --disable-pip   # needs network
```

PostgreSQL integration tests run when `SPARTA_TEST_POSTGRES_URL` is set, for example
`postgresql+asyncpg://sparta:sparta-dev-only@127.0.0.1:5432/sparta_test` against the compose PostgreSQL. **They drop every
table in that database**: create a dedicated throwaway one (`docker compose exec postgres createdb -U sparta sparta_test`).

Changing dependencies: edit `services/api/pyproject.toml`, regenerate `requirements-dev.lock` with
`uv pip compile --universal --generate-hashes` (see [`services/api/README.md`](services/api/README.md)), install it with
`pip install --require-hashes -r requirements-dev.lock`, then run `make lock` (or `.\scripts\lock.ps1`). That refreshes the
**runtime-only, sha256-pinned locks the container image is built from**: `requirements.lock` (no extras),
`requirements-extras.lock` (azure + otlp) and `requirements-build.lock` (uv and hatchling, from `requirements-build.in`),
then asks pypi.org whether every hash in them is a published file digest (`make verify-locks`, or
`.\scripts\tasks.ps1 verify-locks`, repeats that check; CI runs it too, so a mirror cannot slip a different file into a
lock). Commit all lock files together; the image build installs them with `--require-hashes` and fails on any mismatch.

Changing the HTTP API: run `make openapi`, commit `packages/contracts/openapi.json`, update
[`docs/API_CONTRACT.md`](docs/API_CONTRACT.md), and regenerate the web types (`npm run types:api` in `apps/web`).

**Web** (`apps/web`): `npm ci`, then `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`; end-to-end tests
with `npm run e2e:install` once and `npm run e2e` (Playwright starts a real API and the production build; see
[`docs/WEB_APP.md`](docs/WEB_APP.md)). `npm run lock:check` fails if `package-lock.json` points at a package mirror instead
of `registry.npmjs.org`.

**Android** (`apps/android`, JDK 17): `./gradlew testDebugUnitTest lintDebug assembleDebug` (`.\gradlew.bat ...` on
Windows). Setup and caveats: [`docs/ANDROID_SETUP.md`](docs/ANDROID_SETUP.md).

**Infrastructure and delivery**: `docker compose --env-file .env.example config --quiet`;
`az bicep build --file infrastructure/azure/main.bicep` and `az bicep lint --file infrastructure/azure/main.bicep`;
`actionlint` for workflows; `shellcheck -x scripts/*.sh`. Deployment is described in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md); do not run it against a subscription you do not own.

## Adding a language pack

Languages are data, not code. The full procedure is in
[`docs/MULTILINGUAL_SPEECH.md`](docs/MULTILINGUAL_SPEECH.md#10-adding-a-language); in outline:

1. Add `services/api/src/sparta/language/packs/<iso>.toml` with its metadata, detection markers, vocabularies
   (`[terms]`, `[cues]`), owner-reference words and a template for **every** template key in the English pack. Start with
   `status = "planned"`.
2. Patterns are compiled at load time, so a broken pattern fails at startup. No rule code changes are needed.
3. Mark it `supported` only after a native speaker has reviewed the vocabularies and templates, it has a documented speech
   locale and a default voice, and dataset scenarios for it exist.
4. Add scenarios to the **dev** split of `packages/evaluation/dataset/v1`, run the tests, then tune on dev.

## Running the evaluation honestly

`python -m sparta evaluate --split dev` scores the engine on the development split, and CI runs it as a gate.

* **Tune on `dev` only.** The `dev` numbers are training-set numbers, published for transparency.
* **Never tune on `test`.** The held-out split was run once with the final code. Do not run `--split test` or `--split all`
  while changing rules, do not use `--details` to read failing test scenarios, and do not overwrite `docs/eval/latest-test.*`
  unless you are publishing a new held-out run. If the test split is ever used for tuning it is burned, and a new held-out
  split has to be written ([`docs/EVALUATION.md`](docs/EVALUATION.md), section 4).
* Report results exactly as they come out, including the gap between the splits, and regenerate `docs/eval/latest-*` only
  from real runs. The dataset is synthetic and not native-speaker reviewed; say so when you quote a number.

## Code style

Python is formatted and linted by `ruff` and type-checked strictly by `mypy`; the web app by ESLint and TypeScript; Android
by Android lint. `.editorconfig` sets indentation and line endings (LF everywhere except `.bat`/`.cmd`). Comment only code
that needs clarification. Keep PowerShell scripts ASCII-only (Windows PowerShell 5.1 reads BOM-less files as ANSI).

## Reporting problems

Bugs and ideas: use the issue templates. Vulnerabilities, and any case where the assistant reveals or accepts a request
for protected information: **privately**, as described in [SECURITY.md](SECURITY.md).

## License

The repository owner has not chosen a license yet, so the code is not licensed for reuse. Contributions are made on the
understanding that the owner will choose one.
