#!/usr/bin/env bash
# Sparta Asterisk entrypoint: validates the secrets it is given, renders the PJSIP configuration, then runs Asterisk.
#
# Secrets come from the environment (or from files named by NAME_FILE, for Docker/Kubernetes secrets) and are never printed,
# never written anywhere except the rendered /etc/asterisk/pjsip.conf (a tmpfs in the compose file, mode 0640), and are
# removed from the environment before Asterisk starts. Generate them with `python scripts/sip_local.py init`.
set -Eeuo pipefail
umask 027

SRC=/opt/sparta-asterisk/conf
ETC=/etc/asterisk

die() {
  echo "sparta-asterisk: $*" >&2
  exit 64
}

# secret NAME -> the value of $NAME, else the first line of the file named by $NAME_FILE, else empty.
secret() {
  local name="$1" file_var="${1}_FILE" value=""
  if [ -n "${!name:-}" ]; then
    value="${!name}"
  elif [ -n "${!file_var:-}" ] && [ -r "${!file_var}" ]; then
    IFS= read -r value <"${!file_var}" || true
  fi
  printf '%s' "$value"
}

# A secret is at least 24 characters, with at least 8 different ones, from a set that is safe in every place it ends up (a
# config file, a URL userinfo). `python scripts/sip_local.py init` makes 32 random ones; a hand-typed word is refused.
check_secret() {
  local label="$1" value="$2"
  [ -n "$value" ] || die "$label is not set. Run 'python scripts/sip_local.py init' (it writes them to .env), or set it."
  [ "${#value}" -ge 24 ] || die "$label is too short (at least 24 characters)."
  [[ "$value" =~ ^[A-Za-z0-9._~-]+$ ]] || die "$label may contain only letters, digits and . _ ~ -"
  [ "$(printf '%s' "$value" | fold -w1 | sort -u | wc -l)" -ge 8 ] || die "$label is too repetitive (use at least 8 different characters)."
}

number_in_range() {
  local label="$1" value="$2" low="$3" high="$4"
  [[ "$value" =~ ^[0-9]+$ ]] && [ "$value" -ge "$low" ] && [ "$value" -le "$high" ] || die "$label must be a number from $low to $high."
}

SPARTA_WEBHOOK_SECRET="$(secret SPARTA_WEBHOOK_SECRET)"
SIP_PASSWORD_6001="$(secret SIP_PASSWORD_6001)"
SIP_PASSWORD_6002="$(secret SIP_PASSWORD_6002)"
check_secret "SPARTA_WEBHOOK_SECRET" "$SPARTA_WEBHOOK_SECRET"
check_secret "SIP_PASSWORD_6001" "$SIP_PASSWORD_6001"
check_secret "SIP_PASSWORD_6002" "$SIP_PASSWORD_6002"
[ "$SIP_PASSWORD_6001" != "$SIP_PASSWORD_6002" ] || die "the two SIP passwords must differ."

# Non-secret settings, with safe defaults.
ASTERISK_MAX_CALLS="${ASTERISK_MAX_CALLS:-2}"
ASTERISK_MAX_CALL_SECONDS="${ASTERISK_MAX_CALL_SECONDS:-600}"
SPARTA_API_HOST="${SPARTA_API_HOST:-api}"
SPARTA_API_PORT="${SPARTA_API_PORT:-8000}"
SPARTA_MEDIA_PORT="${SPARTA_MEDIA_PORT:-8090}"
number_in_range ASTERISK_MAX_CALLS "$ASTERISK_MAX_CALLS" 1 8
number_in_range ASTERISK_MAX_CALL_SECONDS "$ASTERISK_MAX_CALL_SECONDS" 30 3600
number_in_range SPARTA_API_PORT "$SPARTA_API_PORT" 1 65535
number_in_range SPARTA_MEDIA_PORT "$SPARTA_MEDIA_PORT" 1 65535
[[ "$SPARTA_API_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]] || die "SPARTA_API_HOST must be a plain host name or address."

cidr_list() { # keep only well-formed IPv4 CIDRs from a comma-separated list, none wider than a /8
  local item prefix octet octets
  IFS=',' read -r -a items <<<"$1"
  for item in "${items[@]}"; do
    item="${item//[[:space:]]/}"
    [[ "$item" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]] || die "'$item' is not an IPv4 CIDR range (for example 192.168.1.0/24)."
    prefix="${item#*/}"
    { [ "$((10#$prefix))" -ge 8 ] && [ "$((10#$prefix))" -le 32 ]; } || die "'$item': the prefix must be from /8 to /32 (a wider range lets most of the Internet reach the SIP port)."
    IFS='.' read -r -a octets <<<"${item%/*}"
    for octet in "${octets[@]}"; do
      [ "$((10#$octet))" -le 255 ] || die "'$item' is not a valid IPv4 range."
    done
    printf '%s\n' "$item"
  done
}

# Who may talk SIP to this PBX before authenticating: private networks only, unless told otherwise.
ALLOWED="${ASTERISK_ALLOWED_NETS:-127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16}"
ALLOWED_LIST="$(cidr_list "$ALLOWED")" # an assignment, so a bad range stops the container (a process substitution would not)
ACL_LINES=""
while IFS= read -r cidr; do
  ACL_LINES+="permit = ${cidr}"$'\n'
done <<<"$ALLOWED_LIST"

# NAT: with a public/LAN address given, tell phones to send RTP there; `local_net` is the network Asterisk itself sits on
# (the Docker network), so addresses outside it get the external address in SIP/SDP.
NAT_LINES=""
if [ -n "${ASTERISK_EXTERNAL_IP:-}" ]; then
  [[ "$ASTERISK_EXTERNAL_IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "ASTERISK_EXTERNAL_IP must be an IPv4 address."
  NAT_LINES+="external_media_address = ${ASTERISK_EXTERNAL_IP}"$'\n'
  NAT_LINES+="external_signaling_address = ${ASTERISK_EXTERNAL_IP}"$'\n'
  if [ -n "${ASTERISK_LOCAL_NET:-}" ]; then
    LOCAL_NETS="$(cidr_list "$ASTERISK_LOCAL_NET")"
  else
    LOCAL_NETS="$(ip -4 -o route show scope link 2>/dev/null | awk '$1 ~ /\// {print $1}')"
  fi
  while IFS= read -r cidr; do
    [ -n "$cidr" ] && NAT_LINES+="local_net = ${cidr}"$'\n'
  done <<<"$LOCAL_NETS"
fi

[ -d "$ETC" ] && [ -w "$ETC" ] || die "$ETC is not writable (mount a tmpfs there when the root file system is read-only)."

for file in asterisk.conf extensions.conf rtp.conf modules.conf logger.conf http.conf manager.conf indications.conf; do
  cp -f "$SRC/$file" "$ETC/$file"
done
# Optional configuration files that Asterisk reads even for modules that are not loaded. Empty means "all defaults"; they
# exist only so Asterisk does not log an ERROR for each one at start-up. CDR and CEL (call records) are off.
for file in acl.conf ccss.conf features.conf pjproject.conf stasis.conf udptl.conf; do
  : >"$ETC/$file"
done
printf '[general]\nenable = no\n' >"$ETC/cdr.conf"
printf '[general]\nenable = no\n' >"$ETC/cel.conf"

render() {
  local line
  : >"$2"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line//@@SIP_PASSWORD_6001@@/$SIP_PASSWORD_6001}"
    line="${line//@@SIP_PASSWORD_6002@@/$SIP_PASSWORD_6002}"
    line="${line//@@ACL_PERMIT_LINES@@/${ACL_LINES%$'\n'}}"
    line="${line//@@NAT_LINES@@/${NAT_LINES%$'\n'}}"
    printf '%s\n' "$line" >>"$2"
  done <"$1"
}
render "$SRC/pjsip.conf.template" "$ETC/pjsip.conf"
chmod 0640 "$ETC/pjsip.conf"

# What the dialplan reads with ENV(): the callback secret and the non-secret settings.
export SPARTA_WEBHOOK_SECRET ASTERISK_MAX_CALLS ASTERISK_MAX_CALL_SECONDS SPARTA_API_HOST SPARTA_API_PORT SPARTA_MEDIA_PORT
# The SIP passwords are in pjsip.conf now; nothing else needs them.
unset SIP_PASSWORD_6001 SIP_PASSWORD_6002 SIP_PASSWORD_6001_FILE SIP_PASSWORD_6002_FILE SPARTA_WEBHOOK_SECRET_FILE

echo "sparta-asterisk: configuration ready (extensions 6000/6001/6002, $(printf '%s' "$ACL_LINES" | grep -c .) allowed networks, max ${ASTERISK_MAX_CALLS} calls of ${ASTERISK_MAX_CALL_SECONDS}s)"
exec "$@"
