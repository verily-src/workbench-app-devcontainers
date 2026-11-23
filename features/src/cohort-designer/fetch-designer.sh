#!/bin/bash
# fetch-designer.sh <release> <sha256> <dest>: downloads the cohort designer's binary and installs
# it at <dest> only if its sha256 matches. <release> is gs://bucket/object, read with the VM's
# service account from the metadata server (or gcloud, where that is not reachable), or an
# https:// URL. Exits 0 at once when <dest> already has that sha256.

set -o errexit
set -o nounset
set -o pipefail

readonly RELEASE="${1:?Usage: fetch-designer.sh <release> <sha256> <dest>}"
readonly SHA256="${2:?Usage: fetch-designer.sh <release> <sha256> <dest>}"
readonly DEST="${3:?Usage: fetch-designer.sh <release> <sha256> <dest>}"
# A download that stalls must not hold the app's start: the binary is tens of MB.
readonly TRANSFER=(--connect-timeout 10 --max-time 900)
readonly METADATA="http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"

if [[ -f "${DEST}" ]] && sha256sum "${DEST}" | grep -q "^${SHA256} "; then
  exit 0
fi
mkdir -p "$(dirname "${DEST}")"
tmp="$(mktemp "${DEST}.XXXXXX")"
trap 'rm -f "${tmp}"' EXIT

case "${RELEASE}" in
  gs://*)
    path="${RELEASE#gs://}"
    bucket="${path%%/*}"
    object="$(jq -rn --arg o "${path#*/}" '$o | @uri')"
    { set +x; } 2> /dev/null  # the token stays out of an xtrace
    token="$(curl -fsS -m 10 -H "Metadata-Flavor: Google" "${METADATA}" 2> /dev/null | jq -r '.access_token // empty' || true)"
    if [[ -n "${token}" ]]; then
      # The header goes in on stdin (curl -K -), not in argv, which ps shows.
      printf 'header = "Authorization: Bearer %s"\n' "${token}" |
        curl -fsSL --retry 3 "${TRANSFER[@]}" -K - -o "${tmp}" \
          "https://storage.googleapis.com/storage/v1/b/${bucket}/o/${object}?alt=media"
    elif command -v gcloud > /dev/null; then
      timeout 900 gcloud storage cp "${RELEASE}" "${tmp}"
    else
      echo "fetch-designer.sh: no credentials to read ${RELEASE} (no metadata server, no gcloud)." >&2
      exit 1
    fi
    ;;
  https://*)
    curl -fsSL --retry 3 "${TRANSFER[@]}" -o "${tmp}" "${RELEASE}"
    ;;
  *)
    echo "fetch-designer.sh: the release must be gs:// or https://, got '${RELEASE}'." >&2
    exit 1
    ;;
esac

actual="$(sha256sum "${tmp}" | cut -d' ' -f1)"
if [[ "${actual}" != "${SHA256}" ]]; then
  echo "fetch-designer.sh: ${RELEASE} has sha256 ${actual}, not ${SHA256}; not installed." >&2
  exit 1
fi
chmod 755 "${tmp}"
mv -f "${tmp}" "${DEST}"
trap - EXIT
echo "fetch-designer.sh: installed ${RELEASE} at ${DEST}."
