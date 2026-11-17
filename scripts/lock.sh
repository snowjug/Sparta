#!/usr/bin/env bash
# Regenerates the hash-pinned lock files used to build the container image (and checks them).
#
#   bash scripts/lock.sh [--venv DIR] [--skip-verify] [--dry-run]
#
# Writes, in services/api:
#   requirements.lock         runtime dependencies only            (image built with --build-arg SPARTA_EXTRAS=)
#   requirements-extras.lock  runtime + the azure and otlp extras  (the default image)
#   requirements-build.lock   uv and hatchling, from requirements-build.in (the image's build tools)
# Every package is pinned with sha256 hashes only (md5 lines that some package mirrors add are removed) and the versions are
# held to the ones in requirements-dev.lock, so the image runs what the test suite ran against. Order of work when you
# change dependencies: edit pyproject.toml, regenerate requirements-dev.lock (uv pip compile ... --group dev), then run
# this script and commit all lock files together.
#
# It creates services/api/var/lock-venv (git-ignored) with uv, needs network access to the package index (set
# PIP_INDEX_URL when you build behind a mirror) and changes nothing else. Afterwards it runs scripts/verify_locks.py, which
# asks pypi.org whether every sha256 in the new locks is a published file digest (a mirror cannot slip a different file into
# the lock unnoticed): an unreachable pypi.org is only a warning, a hash it does not know is an error (--skip-verify omits it).
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

LOCK_VENV="$API_DIR/var/lock-venv"
SKIP_VERIFY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --venv)
      shift
      [ $# -gt 0 ] || die "--venv needs a directory."
      LOCK_VENV="$1"
      ;;
    --skip-verify) SKIP_VERIFY=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h | --help) sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Unknown option: $1" "Run scripts/lock.sh --help." ;;
  esac
  shift
done

# A mirror configured for pip also applies to uv.
[ -z "${PIP_INDEX_URL:-}" ] || export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-$PIP_INDEX_URL}"
export PYTHONUTF8=1

for needed in "$API_DIR/requirements-build.in" "$API_DIR/requirements-dev.lock" "$API_DIR/pyproject.toml"; do
  [ -f "$needed" ] || die "Missing $needed" "Run this script from a complete checkout."
done
uv_version="$(sed -n 's/^uv==\(.*\)$/\1/p' "$API_DIR/requirements-build.in" | head -n1 | tr -d '[:space:]')"
[ -n "$uv_version" ] || die "requirements-build.in does not pin uv (a line like uv==0.13.7)."

py="$(find_python)"
[ -n "$py" ] || die "Python 3.12 or newer was not found." "Install Python 3.12, then retry (it is only used to install uv)."

venv_py=""
for candidate in "$LOCK_VENV/bin/python" "$LOCK_VENV/Scripts/python.exe"; do
  if [ -x "$candidate" ]; then venv_py="$candidate"; fi
done
if [ -z "$venv_py" ]; then
  say "Creating $LOCK_VENV"
  run "$py" -m venv "$LOCK_VENV"
  if [ -x "$LOCK_VENV/bin/python" ]; then venv_py="$LOCK_VENV/bin/python"; else venv_py="$LOCK_VENV/Scripts/python.exe"; fi
fi
say "Installing uv $uv_version (the version named in requirements-build.in)"
run "$venv_py" -m pip install --disable-pip-version-check --quiet "uv==$uv_version" || die "pip could not download uv." \
  "If pypi.org is unreachable, set PIP_INDEX_URL to a mirror and retry."

compile_lock() { # compile_lock OUTPUT ARGS...
  local out="$1"
  shift
  say "Compiling $out"
  (cd "$API_DIR" && run "$venv_py" -m uv pip compile -qq --universal --generate-hashes --python-version 3.12 "$@" -o "$out") || die "uv could not resolve the dependencies." \
    "Check the network, or set PIP_INDEX_URL (also used by uv) to a reachable index."
  [ "$DRY_RUN" = "1" ] && return 0
  local path="$API_DIR/$out" removed
  removed="$(grep -c '^[[:space:]]*--hash=md5:' "$path" || true)"
  grep -v '^[[:space:]]*--hash=md5:' "$path" >"$path.tmp" && mv "$path.tmp" "$path"
  if grep -q '^[[:space:]]*--hash=' "$path" && grep '^[[:space:]]*--hash=' "$path" | grep -qv '^[[:space:]]*--hash=sha256:'; then
    die "$out still contains non-sha256 hashes."
  fi
  local pins hashes
  pins="$(grep -cE '^[A-Za-z0-9_.-]+(\[[^]]+\])?==' "$path" || true)"
  hashes="$(grep -cE '^[[:space:]]+--hash=sha256:[0-9a-f]{64}' "$path" || true)"
  if [ "$pins" -le 0 ] || [ "$hashes" -lt "$pins" ]; then
    die "$out is malformed ($pins requirements, $hashes sha256 hashes)."
  fi
  ok "$out: $pins pinned packages, sha256 only (removed $removed md5 lines)"
}

compile_lock requirements.lock pyproject.toml --constraint requirements-dev.lock
compile_lock requirements-extras.lock pyproject.toml --extra azure --extra otlp --constraint requirements-dev.lock
compile_lock requirements-build.lock requirements-build.in

echo
if [ "$DRY_RUN" = "1" ]; then
  ok "Dry run complete: nothing was executed."
else
  if [ "$SKIP_VERIFY" = "1" ]; then
    warn "Skipped the cross-check against pypi.org: run 'make verify-locks' before committing."
  else
    say "Cross-checking every sha256 against pypi.org (scripts/verify_locks.py)"
    verify_code=0
    "$venv_py" "$REPO_ROOT/scripts/verify_locks.py" "$API_DIR/requirements.lock" "$API_DIR/requirements-extras.lock" "$API_DIR/requirements-build.lock" || verify_code=$?
    case "$verify_code" in
      0) ok "Every sha256 in the new locks is a file digest that pypi.org publishes." ;;
      1) die "A lock lists a hash that pypi.org does not publish for that release." \
           "Do not commit these files: the package index you used served files that differ from the published ones." \
           "Retry with PIP_INDEX_URL unset (pypi.org itself) or another trusted index." ;;
      *) warn "Could not reach pypi.org, so the hashes were not cross-checked: run 'make verify-locks' from a network that can, before committing." ;;
    esac
  fi
  ok "Lock files regenerated. Review the diff, then commit requirements*.lock together."
  note "The image build verifies every file against these hashes (pip/uv --require-hashes); the build fails if an index serves different bytes."
fi
