# Sparta API image (multi-stage, non-root, no dev dependencies, hash-verified third-party installs).
#
# Build (needs BuildKit, i.e. Docker 23+ or `docker buildx`), from this directory:
#   docker build -t sparta-api .
#   docker build -t sparta-api:slim --build-arg SPARTA_EXTRAS= .          # simulator-only, no Azure/OTLP SDKs
#   docker build -t sparta-api --build-arg PIP_INDEX_URL=https://my.mirror/simple/ .
#   docker build -t sparta-api:local-speech --build-arg SPARTA_LOCAL_SPEECH=1 .   # + free local speech (GPL-3.0 Piper), see below
#
# Every third-party package comes from a sha256-pinned lock and is installed with --require-hashes, so a package index
# (or a mirror) cannot substitute a different file: requirements-build.lock (uv and the hatchling build backend, in a
# throwaway environment that is not shipped), requirements.lock (runtime dependencies), requirements-extras.lock
# (runtime + the azure and otlp extras) and, for the optional local-speech build only, requirements-local-speech.lock
# (linux/amd64, see below). Regenerate them with scripts/lock.ps1 or scripts/lock.sh. Only the application's own
# wheel is built from the source in this build context.
#
# Run. The development identity has no sign-in, so the server refuses to listen on a non-loopback address (0.0.0.0 inside
# a container) with it unless you opt in explicitly. Do that only for a trusted local network and publish the port on
# 127.0.0.1 only:
#   docker run --rm -e SPARTA_ALLOW_NETWORK_DEV_AUTH=true -p 127.0.0.1:8000:8000 sparta-api
# Real deployments use SPARTA_ENV=production with SPARTA_AUTH_MODE=oidc, PostgreSQL and Redis (docker-compose.yml shows the
# local development stack, docs/DEPLOYMENT.md the Azure one). Other commands:
#   docker run --rm sparta-api python -m sparta keygen      # prints SPARTA_DATA_KEYS / SPARTA_PEPPER / SPARTA_WEBHOOK_SECRET
#   docker run --rm -e SPARTA_DATABASE_URL=... sparta-api python -m sparta migrate
#
# No .env file and no secret is ever baked into the image: configuration is injected through SPARTA_* environment
# variables at run time (see .env.example at the repository root).

ARG PYTHON_IMAGE=python:3.12-slim

# --------------------------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

# Optional extras: "azure" = Azure Communication Services Call Automation SDK, "otlp" = OpenTelemetry OTLP/HTTP exporter.
# The dependency locks cover exactly two sets: empty (the simulator-only image) and azure,otlp (the default).
ARG SPARTA_EXTRAS=azure,otlp
# Package index used by pip and uv. Override it to build behind a corporate mirror.
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    UV_DEFAULT_INDEX=${PIP_INDEX_URL} \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

# Build tools: uv and hatchling from a hash-pinned lock, in /opt/tools (never copied to the runtime image).
COPY requirements-build.lock ./
RUN python -m venv /opt/tools \
    && /opt/tools/bin/pip install --no-cache-dir --require-hashes --no-deps -r requirements-build.lock

# Layer 1: third-party runtime dependencies from a hash-pinned, runtime-only lock (cached until a lock changes). It lists
# exactly what the API needs (plus the selected extras), so pytest, ruff, mypy, bandit... never reach the image, and
# --require-hashes makes uv refuse any file whose sha256 is not in the lock.
COPY requirements.lock requirements-extras.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu; \
    case "${SPARTA_EXTRAS}" in \
      "") lock=requirements.lock ;; \
      "azure,otlp" | "otlp,azure") lock=requirements-extras.lock ;; \
      *) echo "SPARTA_EXTRAS must be empty or azure,otlp: the dependency locks cover those two sets (got '${SPARTA_EXTRAS}')." >&2; exit 1 ;; \
    esac; \
    /opt/tools/bin/uv venv --python /usr/local/bin/python /opt/venv; \
    /opt/tools/bin/uv pip install --python /opt/venv/bin/python --require-hashes --no-deps -r "$lock"

# Optional free local speech: faster-whisper (MIT) recognises and Piper (GPL-3.0-or-later) speaks, both on this machine's CPU.
# Off by default: with SPARTA_LOCAL_SPEECH=0 nothing is added and the image is what it always was. Building it with 1 is a
# licensing decision (Piper's engine is copyleft). requirements-local-speech.lock is hash-pinned for linux/amd64 on Python
# 3.12 (manylinux wheels, glibc 2.28 or newer: python:3.12-slim has 2.36) and installed on top of the lock chosen above, with
# the same --require-hashes discipline. It carries the code only: models are never baked into an image or downloaded at run
# time, mount a volume and fetch them into it (`python -m sparta models fetch`, SPARTA_LOCAL_MODEL_DIR).
ARG SPARTA_LOCAL_SPEECH=0
COPY requirements-local-speech.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    set -eu; \
    case "${SPARTA_LOCAL_SPEECH}" in \
      0) ;; \
      1) /opt/tools/bin/uv pip install --python /opt/venv/bin/python --require-hashes --no-deps -r requirements-local-speech.lock ;; \
      *) echo "SPARTA_LOCAL_SPEECH must be 0 or 1 (got '${SPARTA_LOCAL_SPEECH}')." >&2; exit 1 ;; \
    esac

# Layer 2: the application wheel, built from this build context with the hash-pinned backend (no network, no isolated
# build environment) and installed (not editable) together with its package data: language packs (*.toml), the safety
# policy (default-v1.toml), the curated simulator scenarios (curated.json) and, through the hatch force-include in
# pyproject.toml, the Alembic scripts (sparta/_migrations), so `python -m sparta migrate` works from the installed package.
COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations
RUN /opt/tools/bin/uv build --wheel --no-build-isolation --python /opt/tools/bin/python --out-dir /wheels . \
    && /opt/tools/bin/uv pip install --python /opt/venv/bin/python --no-deps /wheels/sparta_api-*.whl

# Fail the build (not the first request) if package data or the migrations are missing from the wheel.
RUN /opt/venv/bin/python -c "from sparta.db.session import MIGRATIONS_DIR; from sparta.language.registry import load_registry; from sparta.risk.policy import load_default_policy; from sparta.services.simulator import curated_scenarios; packs = load_registry().packs(); load_default_policy(); scenarios = curated_scenarios(); versions = sorted((MIGRATIONS_DIR / 'versions').glob('*.py')); assert packs and scenarios and versions and (MIGRATIONS_DIR / 'env.py').is_file() and MIGRATIONS_DIR.name == '_migrations', MIGRATIONS_DIR; print(len(packs), 'language packs,', len(scenarios), 'curated scenarios, safety policy loaded,', len(versions), 'migration(s) at', MIGRATIONS_DIR)"

# Fail the build if the lock files have drifted from pyproject.toml. The wheel is installed with --no-deps, so a dependency
# that pyproject.toml declares but the lock lacks would otherwise surface as an ImportError at run time: `uv pip check`
# reports it here, and the extras' SDKs (imported lazily by the application) must be importable when they were requested.
RUN set -eu; \
    /opt/tools/bin/uv pip check --python /opt/venv/bin/python; \
    if [ -n "${SPARTA_EXTRAS}" ]; then \
      /opt/venv/bin/python -c "import azure.communication.callautomation, opentelemetry.exporter.otlp.proto.http.trace_exporter"; \
    fi; \
    if [ "${SPARTA_LOCAL_SPEECH}" = "1" ]; then \
      /opt/venv/bin/python -c "import ctranslate2, faster_whisper, onnxruntime, piper"; \
    fi

# --------------------------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# Apply the Debian security updates that are newer than the base image: the official image is rebuilt only periodically, and
# the CI vulnerability scan fails on a HIGH or CRITICAL finding that has a fix. Trade-off: two builds of the same commit can
# differ by whatever Debian published in between (the Python packages never do: they come from the hash-pinned locks).
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:${PATH}" \
    SPARTA_DATA_DIR=/var/lib/sparta \
    SPARTA_DATABASE_URL=sqlite+aiosqlite:////var/lib/sparta/sparta.db

# Unprivileged runtime user (fixed ids so volume permissions are predictable). /var/lib/sparta is the only writable
# location the application needs: development keys (when SPARTA_DATA_KEYS is unset) and the default SQLite file.
RUN groupadd --gid 10001 sparta \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin sparta \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/sparta

COPY --from=builder /opt/venv /opt/venv

# Health probe without curl. It sends an allowed Host header because production refuses unlisted hosts
# (SPARTA_TRUSTED_HOSTS must be explicit there) and the probe talks to 127.0.0.1.
COPY --chmod=0555 <<'PYTHON' /usr/local/bin/sparta-healthcheck
#!/usr/local/bin/python
import os
import sys
import urllib.request

port = os.environ.get("SPARTA_HEALTHCHECK_PORT", "8000")
host = os.environ.get("SPARTA_TRUSTED_HOSTS", "").split(",")[0].strip().replace("*.", "health.")
headers = {} if host in ("", "*") else {"Host": host}
request = urllib.request.Request(f"http://127.0.0.1:{port}/healthz", headers=headers)
try:
    healthy = urllib.request.urlopen(request, timeout=4).status == 200
except Exception:
    healthy = False
sys.exit(0 if healthy else 1)
PYTHON

WORKDIR /app
USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=6s --start-period=30s --retries=3 CMD ["sparta-healthcheck"]

STOPSIGNAL SIGTERM
CMD ["python", "-m", "sparta", "serve", "--host", "0.0.0.0", "--port", "8000"]

ARG VERSION=0.1.0
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="sparta-api" \
      org.opencontainers.image.description="Sparta: multilingual AI call-screening backend" \
      org.opencontainers.image.source="https://github.com/snowjug/Sparta" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}"
