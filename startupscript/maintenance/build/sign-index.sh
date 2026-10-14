#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

readonly INDEX="${1:?Usage: sign-index.sh SHA256SUMS SIGNING_KEY_ID}"
readonly KEY_ID="${2:?Usage: sign-index.sh SHA256SUMS SIGNING_KEY_ID}"
: "${GNUPGHOME:?Use an explicit private signing directory}"
[[ -f "$INDEX" && ! -e "$INDEX.gpg" ]]
[[ "$KEY_ID" =~ ^[0-9A-Fa-f]{40}$ ]]
# The signer stays outside CI; only the index, signature and public key are handed to the publisher.
gpg --batch --no-tty --homedir "$GNUPGHOME" --local-user "$KEY_ID" \
    --output "$INDEX.gpg" --detach-sign "$INDEX"
