#!/usr/bin/env bash
# Shared helpers for the Sparta shell scripts (Linux, macOS, WSL, Git Bash). Source it, do not run it:
#   . "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck shell=bash

# shellcheck disable=SC2034  # WEB_DIR and DRY_RUN are used by the scripts that source this file
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_DIR="$REPO_ROOT/services/api"
WEB_DIR="$REPO_ROOT/apps/web"
DRY_RUN="${DRY_RUN:-0}"

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_OFF=$'\033[0m'
else
  C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_OFF=""
fi

say() { printf '%s==>%s %s\n' "$C_CYAN" "$C_OFF" "$*"; }
ok() { printf '%s[ok]%s   %s\n' "$C_GREEN" "$C_OFF" "$*"; }
note() { printf '       %s\n' "$*"; }
warn() { printf '%s[warn]%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }

# die "message" "hint" ... : explain what is wrong and what to do about it, then exit 1 (no stack trace).
die() {
  local message="$1"
  shift
  printf '%sERROR:%s %s\n' "$C_RED" "$C_OFF" "$message" >&2
  local hint
  for hint in "$@"; do printf '  - %s\n' "$hint" >&2; done
  exit 1
}

have() { command -v "$1" >/dev/null 2>&1; }

# run CMD...: execute in the current directory, or only print it when DRY_RUN=1.
run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[dry-run] (%s) %s\n' "$PWD" "$*"
    return 0
  fi
  "$@"
}

venv_dir() { printf '%s' "${SPARTA_VENV:-$API_DIR/.venv}"; }

# Prints the interpreter inside the environment (bin/python, or Scripts/python.exe under Git Bash); empty if missing.
venv_python() {
  local venv candidate
  venv="$(venv_dir)"
  for candidate in "$venv/bin/python" "$venv/Scripts/python.exe"; do
    if [ -x "$candidate" ]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 0
}

require_venv_python() {
  local python
  python="$(venv_python)"
  if [ -z "$python" ]; then
    if [ "$DRY_RUN" = "1" ]; then
      printf '%s' "$(venv_dir)/bin/python"
      return 0
    fi
    die "The Python environment $(venv_dir) does not exist yet." \
      "Run 'make bootstrap' (or scripts/bootstrap.sh) once; it creates the environment and installs the locked dependencies." \
      "Using another location? Set SPARTA_VENV to that environment folder."
  fi
  printf '%s' "$python"
}

# Finds a Python >= 3.12. Exactly 3.12 (what CI and the lock use) wins over newer versions.
find_python() {
  local candidate version major minor fallback=""
  for candidate in "${SPARTA_PYTHON:-}" python3.12 python3 python; do
    [ -n "$candidate" ] || continue
    have "$candidate" || continue
    version="$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || continue
    major="${version%%.*}"
    minor="${version#*.}"
    case "$major$minor" in *[!0-9]* | "") continue ;; esac
    if [ "$major" -gt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -ge 12 ]; }; then
      if [ "$version" = "3.12" ]; then
        printf '%s' "$candidate"
        return 0
      fi
      [ -n "$fallback" ] || fallback="$candidate"
    fi
  done
  printf '%s' "$fallback"
}

require_node() {
  have node || die "Node.js was not found on PATH." \
    "Install Node.js 22.12 or newer (https://nodejs.org, or your package manager / nvm), then open a new terminal." \
    "The web app (apps/web) needs it; the API does not."
  local version major minor
  version="$(node --version 2>/dev/null | sed 's/^v//')"
  major="${version%%.*}"
  minor="${version#*.}"
  minor="${minor%%.*}"
  case "$major$minor" in *[!0-9]* | "") die "Could not read the Node.js version ('$version')." ;; esac
  if [ "$major" -lt 22 ] || { [ "$major" -eq 22 ] && [ "$minor" -lt 12 ]; }; then
    die "Node.js 22.12 or newer is required (found $version)." "Upgrade Node.js, then open a new terminal."
  fi
}

require_docker() {
  have docker || die "Docker was not found on PATH." \
    "Install Docker Desktop or Docker Engine with the compose plugin." \
    "No Docker? The simulator also runs without it: use 'make dev' (SQLite, in-process state)."
  docker info >/dev/null 2>&1 || die "The Docker engine is not running." \
    "Start Docker Desktop (or the docker service) and wait until it reports it is running, then retry."
}

# load_env: export KEY=VALUE lines from the repository's .env (variables that are already set win, like pydantic-settings).
# It parses the file instead of sourcing it, so a stray command in .env cannot run.
load_env() {
  local file="$REPO_ROOT/.env" line key value
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    case "$line" in "" | "#"*) continue ;; esac
    line="${line#export }"
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    case "$value" in
      \"*\") value="${value#\"}"; value="${value%\"}" ;;
      \'*\') value="${value#\'}"; value="${value%\'}" ;;
      *" #"*) value="${value%% \#*}" ;;
    esac
    case "$key" in "" | [0-9]* | *[!A-Za-z0-9_]*) continue ;; esac
    if [ -z "$value" ]; then
      warn "$key is empty in .env and was ignored (an empty value counts as set for the API). Comment the line out instead."
      continue
    fi
    if [ -z "$(printenv "$key" 2>/dev/null || true)" ]; then
      export "$key=$value"
    fi
  done <"$file"
}

# wait_http URL [SECONDS]: poll until the URL answers 2xx (curl, or Python as a fallback).
wait_http() {
  local url="$1" seconds="${2:-60}" i=0
  while [ "$i" -lt "$((seconds * 2))" ]; do
    if have curl; then
      curl -fsS -o /dev/null --max-time 3 "$url" 2>/dev/null && return 0
    elif have python3; then
      python3 -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=3)" "$url" 2>/dev/null && return 0
    else
      die "Neither curl nor python3 is available to poll $url." "Install curl."
    fi
    sleep 0.5
    i=$((i + 1))
  done
  return 1
}
