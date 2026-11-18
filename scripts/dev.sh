#!/usr/bin/env bash
# Runs the Sparta development stack on this machine (Linux, macOS, WSL, Git Bash).
#
#   bash scripts/dev.sh [all|api|web|migrate|seed] [--docker] [--api-port N] [--web-port N] [--dry-run]
#
#   all (default)  migrate, seed, then API and web together; Ctrl+C stops both (and nothing else)
#   api            migrate, seed, then the API in the foreground
#   web            the web dev server in the foreground (an API must already be running)
#   migrate | seed apply migrations / create the development owner, then exit
#   --docker       start PostgreSQL and Redis with `docker compose up -d --wait` and point the API at them
#
# .env (repository root) is loaded first; variables already set in your shell win.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

MODE="all"
USE_DOCKER=0
API_PORT=""
WEB_PORT=""

usage() { sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

case "${1:-}" in
  all | api | web | migrate | seed)
    MODE="$1"
    shift
    ;;
esac
while [ $# -gt 0 ]; do
  case "$1" in
    --docker) USE_DOCKER=1 ;;
    --api-port) shift; API_PORT="${1:-}" ;;
    --web-port) shift; WEB_PORT="${1:-}" ;;
    --dry-run) DRY_RUN=1 ;;
    -h | --help) usage; exit 0 ;;
    *) die "Unknown option: $1" "Run scripts/dev.sh --help." ;;
  esac
  shift
done

load_env
[ -n "$API_PORT" ] || API_PORT="${SPARTA_API_PORT:-8000}"
[ -n "$WEB_PORT" ] || WEB_PORT="${SPARTA_WEB_PORT:-3000}"
case "$API_PORT$WEB_PORT" in *[!0-9]* | "") die "Ports must be numbers (api: '$API_PORT', web: '$WEB_PORT')." ;; esac

export PYTHONUTF8=1
export SPARTA_PUBLIC_BASE_URL="http://localhost:$API_PORT"
export SPARTA_CORS_ORIGINS="${SPARTA_CORS_ORIGINS:-http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT}"
export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:$API_PORT}"

NEXT_CLI="$WEB_DIR/node_modules/next/dist/bin/next"

need_api=1
need_web=1
case "$MODE" in
  api | migrate | seed) need_web=0 ;;
  web) need_api=0 ;;
esac

python=""
if [ "$need_api" = "1" ]; then python="$(require_venv_python)"; fi
if [ "$need_web" = "1" ] && [ "$DRY_RUN" != "1" ]; then
  [ -f "$WEB_DIR/package.json" ] || die "apps/web/package.json was not found." "Use 'dev.sh api' to run just the API."
  require_node
  [ -f "$NEXT_CLI" ] || die "The web dependencies are not installed." "Run 'make bootstrap' (or 'npm ci' in apps/web)." "Use 'dev.sh api' to run just the API."
fi

if [ "$USE_DOCKER" = "1" ]; then
  [ "$DRY_RUN" = "1" ] || require_docker
  say "Starting PostgreSQL and Redis (docker compose)"
  (cd "$REPO_ROOT" && run docker compose up -d --wait postgres redis) || die "docker compose could not start PostgreSQL and Redis." \
    "Port already in use? Set SPARTA_POSTGRES_PORT / SPARTA_REDIS_PORT in .env." \
    "See 'docker compose logs postgres redis' for the reason."
  export SPARTA_DATABASE_URL="${SPARTA_DATABASE_URL:-postgresql+asyncpg://sparta:${SPARTA_POSTGRES_PASSWORD:-sparta-dev-only}@127.0.0.1:${SPARTA_POSTGRES_PORT:-5432}/sparta}"
  export SPARTA_REDIS_URL="${SPARTA_REDIS_URL:-redis://:${SPARTA_REDIS_PASSWORD:-sparta-dev-only}@127.0.0.1:${SPARTA_REDIS_PORT:-6379}/0}"
fi

if [ "$need_api" = "1" ]; then
  say "Applying database migrations"
  (cd "$API_DIR" && run "$python" -X utf8 -m sparta migrate) || die "Migrations failed." \
    "The 'error:' line above says which dependency is unreachable (database or Redis) and what to start; dev.sh --docker starts PostgreSQL and Redis." \
    "Configuration problems are listed one per line under 'Invalid Sparta configuration'."
  if [ "$MODE" != "migrate" ]; then
    say "Creating the development owner"
    (cd "$API_DIR" && run "$python" -X utf8 -m sparta seed) || die "Seeding failed." \
      "The 'error:' line above says which dependency is unreachable. If Redis is configured (SPARTA_REDIS_URL), it must answer PING."
  fi
fi

case "$MODE" in
  migrate | seed) exit 0 ;;
esac

if [ "$DRY_RUN" = "1" ]; then
  [ "$need_api" != "1" ] || echo "[dry-run] ($API_DIR) $python -X utf8 -m sparta serve --host 127.0.0.1 --port $API_PORT"
  [ "$need_web" != "1" ] || echo "[dry-run] ($WEB_DIR) node $NEXT_CLI dev -p $WEB_PORT"
  note "Environment: SPARTA_PUBLIC_BASE_URL=$SPARTA_PUBLIC_BASE_URL SPARTA_CORS_ORIGINS=$SPARTA_CORS_ORIGINS NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL"
  ok "Dry run complete: nothing was started."
  exit 0
fi

if [ "$MODE" = "api" ]; then
  say "Starting the API on http://127.0.0.1:$API_PORT"
  cd "$API_DIR"
  exec "$python" -X utf8 -m sparta serve --host 127.0.0.1 --port "$API_PORT"
fi
if [ "$MODE" = "web" ]; then
  say "Starting the web app on http://localhost:$WEB_PORT"
  cd "$WEB_DIR"
  exec node "$NEXT_CLI" dev -p "$WEB_PORT"
fi

# MODE=all: both servers in the background, supervised; everything this script started stops on exit or Ctrl+C.
PIDS=()
cleanup() {
  trap - EXIT INT TERM
  local pid
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  note "Stopped the processes started by this script."
}
trap cleanup EXIT INT TERM

say "Starting the API on http://127.0.0.1:$API_PORT"
(cd "$API_DIR" && exec "$python" -X utf8 -m sparta serve --host 127.0.0.1 --port "$API_PORT") &
PIDS+=("$!")
say "Starting the web app on http://localhost:$WEB_PORT"
(cd "$WEB_DIR" && exec node "$NEXT_CLI" dev -p "$WEB_PORT") &
PIDS+=("$!")

wait_http "http://127.0.0.1:$API_PORT/healthz" 90 || die "The API did not answer /healthz within 90 seconds." \
  "Read the output above for the reason (configuration problems are listed one per line)." \
  "Port in use? Pass --api-port <free port>."
echo
ok "Sparta is running (development identity, simulator providers: no real calls, no cloud accounts)."
note "API        http://localhost:$API_PORT   (interactive docs: /docs, status: /api/v1/system/status)"
note "Web        http://localhost:$WEB_PORT"
note "Simulator  http://localhost:$WEB_PORT/simulator"
note "Press Ctrl+C to stop."

while true; do
  sleep 1
  for pid in "${PIDS[@]}"; do
    kill -0 "$pid" 2>/dev/null || die "A server process exited unexpectedly. Everything started by this script is being stopped." "Read the output above for the reason."
  done
done
