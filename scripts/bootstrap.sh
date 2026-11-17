#!/usr/bin/env bash
# One-time developer setup (Linux, macOS, WSL, Git Bash): Python environment with the locked dependencies, web
# dependencies and a .env file. Nothing is installed globally.
#
#   bash scripts/bootstrap.sh [--skip-api] [--skip-web] [--force] [--venv DIR] [--dry-run]
#
#   --skip-api   do not set up the Python environment
#   --skip-web   do not install the web dependencies
#   --force      recreate the Python environment and reinstall the web dependencies
#   --venv DIR   environment location (default services/api/.venv, or $SPARTA_VENV)
#   --dry-run    print what would run, change nothing
#
# Behind a corporate package mirror set PIP_INDEX_URL (pip and uv) and the npm registry before running.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SKIP_API=0
SKIP_WEB=0
FORCE=0

usage() { sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-api) SKIP_API=1 ;;
    --skip-web) SKIP_WEB=1 ;;
    --force) FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --venv)
      shift
      [ $# -gt 0 ] || die "--venv needs a directory."
      SPARTA_VENV="$1"
      export SPARTA_VENV
      ;;
    -h | --help) usage; exit 0 ;;
    *) die "Unknown option: $1" "Run scripts/bootstrap.sh --help." ;;
  esac
  shift
done

# A mirror configured for pip also applies to uv.
[ -z "${PIP_INDEX_URL:-}" ] || export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-$PIP_INDEX_URL}"
export PYTHONUTF8=1

setup_api() {
  local venv python py
  venv="$(venv_dir)"
  [ -f "$API_DIR/requirements-dev.lock" ] || die "Missing $API_DIR/requirements-dev.lock" "Run this script from a complete checkout of the repository."
  python="$(venv_python)"

  if [ -n "$python" ] && [ "$FORCE" != "1" ]; then
    ok "Python environment already exists: $venv (use --force to recreate it)"
  else
    if [ -n "$python" ] && [ "$FORCE" = "1" ] && [ "$DRY_RUN" != "1" ]; then
      [ -f "$venv/pyvenv.cfg" ] || die "$venv does not look like a Python environment; refusing to delete it."
      say "Removing $venv"
      rm -rf "$venv"
    fi
    say "Creating the Python environment at $venv"
    if have uv; then
      run uv venv --python 3.12 "$venv" || die "uv could not create the environment." \
        "uv downloads Python 3.12 when none is installed: check your network or proxy."
    else
      py="$(find_python)"
      [ -n "$py" ] || die "Python 3.12 or newer was not found, and uv is not installed." \
        "Install Python 3.12 (python.org, pyenv, or your package manager), then retry." \
        "Alternatively install uv (https://docs.astral.sh/uv/getting-started/installation/); it can download Python 3.12 itself."
      if [ "$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])')" != "3.12" ]; then
        warn "$py is not Python 3.12 (the tested version). Locked packages may lack wheels for it; install Python 3.12 if installation fails."
      fi
      run "$py" -m venv "$venv" || die "The venv module failed." \
        "On Debian/Ubuntu install the python3-venv package."
    fi
    python="$(require_venv_python)"
  fi

  # The lock carries sha256 hashes only, so plain pip (hash-checking mode) and uv both install it.
  if have uv; then
    say "Installing the locked dependencies with uv (services/api/requirements-dev.lock)"
    run uv pip install --python "$python" -r "$API_DIR/requirements-dev.lock" || die "Dependency installation failed." \
      "If pypi.org is unreachable, set PIP_INDEX_URL to a mirror and retry."
    say "Installing the API package in editable mode"
    run uv pip install --python "$python" --no-deps -e "$API_DIR"
  else
    say "Installing the locked dependencies with pip (services/api/requirements-dev.lock, hashes verified)"
    run "$python" -m pip install --disable-pip-version-check -r "$API_DIR/requirements-dev.lock" || die "Dependency installation failed." \
      "If pypi.org is unreachable, set PIP_INDEX_URL to a mirror and retry." \
      "A hash mismatch means the lock file and the package index disagree: do not bypass it, regenerate the lock."
    say "Installing the API package in editable mode"
    run "$python" -m pip install --disable-pip-version-check --no-deps -e "$API_DIR"
  fi

  if [ "$DRY_RUN" != "1" ]; then
    (cd "$API_DIR" && "$python" -m sparta --help >/dev/null) || die "The API package did not import after installation."
    ok "API environment ready: $python"
  fi
}

setup_web() {
  if [ ! -f "$WEB_DIR/package.json" ]; then
    warn "apps/web/package.json not found: skipping the web dependencies."
    return 0
  fi
  if [ "$DRY_RUN" != "1" ]; then require_node; fi
  if [ -d "$WEB_DIR/node_modules" ] && [ "$FORCE" != "1" ]; then
    ok "Web dependencies already installed (use --force to reinstall)."
    return 0
  fi
  have npm || [ "$DRY_RUN" = "1" ] || die "npm was not found on PATH." "Install Node.js (it ships npm), then open a new terminal."
  say "Installing the web dependencies (npm ci)"
  (cd "$WEB_DIR" && run npm ci) || die "npm ci failed." \
    "Behind a corporate mirror, set the npm registry (npm config set registry <url>) and retry." \
    "The lockfile must point at registry.npmjs.org: run 'npm run lock:check' in apps/web."
  [ "$DRY_RUN" = "1" ] || ok "Web dependencies installed."
}

setup_env_file() {
  if [ -f "$REPO_ROOT/.env" ]; then
    ok ".env already exists (left untouched)."
  elif [ "$DRY_RUN" = "1" ]; then
    echo "[dry-run] copy .env.example to .env"
  else
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    ok "Created .env from .env.example (development defaults, no secrets)."
  fi
}

say "Checking prerequisites"
[ "$DRY_RUN" != "1" ] || note "Dry run: nothing will be changed."
if have docker; then note "Docker: found (needed only for docker compose and the container build)"; else note "Docker: not found (optional; the simulator runs without it)"; fi
have git || warn "Git was not found on PATH."

[ "$SKIP_API" = "1" ] || setup_api
[ "$SKIP_WEB" = "1" ] || setup_web
setup_env_file

echo
ok "Setup finished. Next steps:"
note "make dev            start the API (SQLite, simulator) and the web app"
note "make dev-docker     same, with PostgreSQL and Redis from docker compose"
note "make check          run the same checks as CI"
note "Simulator Lab: http://localhost:3000/simulator"
