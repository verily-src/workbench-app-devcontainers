#!/bin/bash
# Compatibility shim for `apt-key`, removed in Debian trixie.
#
# MDV's base image is Debian 13; Verily Workbench provisioning and the
# google-cloud-cli devcontainer feature still call `apt-key`. Supports the two
# forms they use:
#   apt-key add -
#   apt-key --keyring <file> add -
# The key is written as a binary keyring (dearmored if ASCII-armored).
set -o pipefail

keyring="/etc/apt/trusted.gpg.d/imported-$(date +%s%N).gpg"
mode=""
src="-"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keyring) keyring="$2"; shift 2 ;;
    add) mode="add"; shift ;;
    -) src="-"; shift ;;
    *) src="$1"; shift ;;
  esac
done

# Non-add invocations (list, del, etc.) are no-ops for our purposes.
[[ "$mode" == "add" ]] || exit 0

mkdir -p "$(dirname "$keyring")"
tmp="$(mktemp)"
if [[ "$src" == "-" ]]; then cat > "$tmp"; else cat "$src" > "$tmp"; fi

if ! { gpg --dearmor < "$tmp" > "$keyring" 2>/dev/null && [[ -s "$keyring" ]]; }; then
  cp "$tmp" "$keyring"
fi
rm -f "$tmp"
exit 0
