#!/usr/bin/env bash
# Container health: Asterisk is fully booted, both SIP endpoints exist and the media bridge module is loaded.
# Uses the control socket inside the container only; prints nothing secret.
set -eu
ast() { asterisk -C /etc/asterisk/asterisk.conf -rx "$1" 2>&1; }

ast 'core waitfullybooted' | grep -qi 'fully booted'
endpoints="$(ast 'pjsip show endpoints')"
grep -q '6001' <<<"$endpoints"
grep -q '6002' <<<"$endpoints"
ast 'module show like app_audiosocket' | grep -q 'app_audiosocket'
