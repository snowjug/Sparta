# sparta-api

FastAPI backend for Sparta (modular monolith). See the repository root `README.md` and `docs/ARCHITECTURE.md`.

Quick start from this directory (Python 3.12 or newer). Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --require-hashes -r requirements-dev.lock
pip install --no-deps -e .
python -m sparta serve --port 8000
```

Linux or macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install --require-hashes -r requirements-dev.lock
pip install --no-deps -e .
python -m sparta serve --port 8000
```

`requirements-dev.lock` pins the runtime and development dependencies with sha256 hashes (generated with
`uv pip compile --universal --generate-hashes`). With `uv` you can use `uv pip sync requirements-dev.lock` instead.

Outside production the server applies the database migrations on start (SQLite file `var/sparta.db` by default). To
run them yourself: `python -m sparta migrate`. Health: `http://127.0.0.1:8000/healthz` and `/readyz`; interactive API
docs: `/docs` (switched off in production). Other commands: `python -m sparta seed|openapi|evaluate|keygen`.

Checks:

```
python -m pytest
ruff check .
ruff format --check .
mypy src
```

The PostgreSQL and Redis variants of the tests only run when `SPARTA_TEST_POSTGRES_URL` (for example
`postgresql+asyncpg://user:password@localhost:5432/sparta_test`) or `SPARTA_TEST_REDIS_URL` (for example
`redis://localhost:6379/1`) is set; everything else runs on SQLite and an in-memory store. Configuration is
read from `SPARTA_*` environment variables or a `.env` file; see `../../.env.example`.
