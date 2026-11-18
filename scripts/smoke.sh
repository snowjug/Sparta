#!/usr/bin/env bash
# Smoke-tests a running Sparta API: liveness, readiness, public status and one simulator call.
#
#   bash scripts/smoke.sh [--base-url http://127.0.0.1:8000] [--timeout 60]
#
# Needs curl, the development identity (SPARTA_AUTH_MODE=dev) and the simulator (SPARTA_SIMULATOR_ENABLED=true), which
# is how docker-compose.yml and scripts/dev.sh run the API. It never prints transcripts or tokens.
set -euo pipefail
# shellcheck source=scripts/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BASE_URL=""
TIMEOUT=60
while [ $# -gt 0 ]; do
  case "$1" in
    --base-url) shift; BASE_URL="${1:-}" ;;
    --timeout) shift; TIMEOUT="${1:-60}" ;;
    -h | --help) sed -n '2,7p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Unknown option: $1" "Run scripts/smoke.sh --help." ;;
  esac
  shift
done

have curl || die "curl was not found on PATH." "Install curl (apt install curl, brew install curl)."
root="${BASE_URL:-http://127.0.0.1:${SPARTA_API_PORT:-8000}}"
root="${root%/}"

# json_field NAME JSON: first string value of "NAME" in compact JSON (no jq or python needed).
json_field() { printf '%s' "$2" | grep -o "\"$1\":\"[^\"]*\"" | head -n1 | cut -d'"' -f4; }

api() { # api METHOD URL [JSON_BODY]
  local method="$1" url="$2" body="${3:-}" out
  if [ -n "$body" ]; then
    out="$(curl -fsS --max-time 20 -X "$method" -H 'Content-Type: application/json' -d "$body" "$url" 2>&1)" || die "$method $url failed: $(printf '%s' "$out" | tail -n1)" \
      "Is the API running at that address? Start it with 'make dev' or 'docker compose up -d --build postgres redis api'." \
      "HTTP 401 means the API demands sign-in (oidc); HTTP 404 on the simulator means SPARTA_SIMULATOR_ENABLED=false."
  else
    out="$(curl -fsS --max-time 20 -X "$method" "$url" 2>&1)" || die "$method $url failed: $(printf '%s' "$out" | tail -n1)" \
      "Is the API running at that address? Start it with 'make dev' or 'docker compose up -d --build postgres redis api'."
  fi
  printf '%s' "$out"
}

say "Waiting for $root/healthz"
wait_http "$root/healthz" "$TIMEOUT" || die "No answer from $root/healthz within $TIMEOUT seconds." \
  "Start the API first: make dev, or docker compose up -d --build postgres redis api." \
  "Different port? Pass --base-url http://127.0.0.1:<port>."
ok "/healthz answered 200"

ready="$(api GET "$root/readyz")"
[ "$(json_field status "$ready")" = "ready" ] || die "/readyz reports '$(json_field status "$ready")'." "Check the database and shared-state (Redis) connections of the API."
ok "/readyz ready"

status="$(api GET "$root/api/v1/system/status")"
ok "/api/v1/system/status: version $(json_field version "$status"), env $(json_field env "$status"), auth $(json_field auth_mode "$status")"
[ "$(json_field auth_mode "$status")" = "dev" ] || die "The API is not in development identity mode." "Only the dev identity can be smoke-tested without a token."

call="$(api POST "$root/api/v1/simulator/calls" '{"caller_number":"+15550100","caller_label":"smoke test","language_mode":"auto"}')"
call_id="$(json_field id "$call")"
[ -n "$call_id" ] || die "The simulator did not return a call id."
ok "simulator call created ($call_id)"

api POST "$root/api/v1/calls/$call_id/turns" '{"text":"This is your bank. Please read out the one time password sent to your phone right now.","source":"typed"}' >/dev/null
detail="$(api GET "$root/api/v1/calls/$call_id")"
risk="$(json_field risk_level "$detail")"
case "$risk" in
  "" | none | low | unknown) die "The risk engine did not flag an OTP request (risk level: ${risk:-missing})." "This is a safety regression: run the evaluation (python -m sparta evaluate --split dev)." ;;
esac
ok "OTP request flagged: risk level $risk"

# A refused request ends the call by itself (it can read "active" for a moment): ending an ended call answers 409, which is fine.
if [ "$(json_field status "$detail")" = "active" ]; then
  curl -sS --max-time 20 -o /dev/null -X POST -H 'Content-Type: application/json' -d '{}' "$root/api/v1/calls/$call_id/end" || true
fi

echo
ok "Smoke test passed."
