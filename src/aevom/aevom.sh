#!/bin/bash

# `aevom`: manage the Aevom stack from the code-server terminal.
#
#   aevom key nv|nvinf|anthropic|openai   store an LLM API key (prompted, not echoed)
#   aevom keys                            list configured providers
#   aevom status                          health of the API and tool services
#   aevom url                             how to open the UI
#
# Keys live in ~/.aevom (a volume shared read-only with the aevom-api
# container). The API waits for the first key before it starts and reads keys
# per request, so adding or changing one needs no restart.

set -o errexit
set -o nounset
set -o pipefail

readonly KEY_DIR="${HOME}/.aevom"
readonly API="http://localhost:8000"

usage() {
  sed -n '3,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
}

key_file() {
  case "$1" in
    nv) echo "${KEY_DIR}/API_KEY_NV" ;;
    nvinf) echo "${KEY_DIR}/API_KEY_NVINF" ;;
    anthropic) echo "${KEY_DIR}/API_KEY_ANTHROPIC" ;;
    openai) echo "${KEY_DIR}/API_KEY_OPENAI" ;;
    *) echo "Unknown provider '$1'. Use nv, nvinf, anthropic or openai." >&2; exit 1 ;;
  esac
}

cmd_key() {
  local provider="${1:?aevom key <nv|nvinf|anthropic|openai>}"
  local file
  file="$(key_file "${provider}")"
  mkdir -p "${KEY_DIR}" && chmod 700 "${KEY_DIR}"
  local key
  if [[ -t 0 ]]; then
    read -r -s -p "Paste the ${provider} API key: " key; echo
  else
    key="$(cat)"
  fi
  key="$(tr -d '[:space:]' <<< "${key}")"
  [[ -n "${key}" ]] || { echo "Empty key, nothing written." >&2; exit 1; }
  (umask 077; printf '%s' "${key}" > "${file}")
  echo "Wrote ${file}. Aevom picks it up on its next request (or finishes starting if it was waiting)."
}

cmd_keys() {
  local p f
  for p in nv nvinf anthropic openai; do
    f="$(key_file "${p}")"
    if [[ -s "${f}" ]]; then echo "  ${p}: configured (${f})"; else echo "  ${p}: -"; fi
  done
}

probe() {
  local name="$1" url="$2" code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${url}" || true)"
  printf '  %-10s %s  %s\n' "${name}" "${code:-000}" "${url}"
}

cmd_status() {
  echo "Aevom services (all on localhost inside this app):"
  probe api "${API}/api/health"
  probe rdkit http://localhost:8001/health
  probe pyexec http://localhost:8002/health
  probe vina http://localhost:8003/health
  probe admet http://localhost:8004/ready
  probe plip http://localhost:8005/health
  probe phoenix http://localhost:6006/
  echo
  echo "Models the API currently offers:"
  curl -s --max-time 5 "${API}/api/models" | python3 -c 'import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print("  (API not ready; if no key is configured yet, run: aevom key nv)"); sys.exit(0)
ms=d.get("models",d) if isinstance(d,dict) else d
for m in ms:
    print("  -", m.get("id",m) if isinstance(m,dict) else m)' 2>/dev/null || true
}

cmd_url() {
  cat <<MSG
Open the Aevom UI through code-server's port proxy: take this app's URL in the
browser, which ends in /proxy/8443/, and append  proxy/8000/  so it ends in
  .../proxy/8443/proxy/8000/
API docs are at .../proxy/8443/proxy/8000/docs
MSG
}

case "${1:-}" in
  key) shift; cmd_key "$@" ;;
  keys) cmd_keys ;;
  status) cmd_status ;;
  url) cmd_url ;;
  *) usage ;;
esac
