#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

readonly VERSION_URL="${1:?Usage: update-flatcar.sh <version-url> <channel>}"
readonly CHANNEL_ARG="${2:?Usage: update-flatcar.sh <version-url> <channel>}"

if [[ "$CHANNEL_ARG" != stable && "$CHANNEL_ARG" != beta ]]; then
  echo "Unsupported Flatcar channel: $CHANNEL_ARG" >&2
  exit 1
fi

# /etc/flatcar/update.conf is overwritten by Ignition with only REBOOT_STRATEGY
# and SERVER, so the booted channel must come from Flatcar's own copy under
# /usr/share. The image family requested at VM creation and the update channel
# can disagree, so this is the source of truth, not the CLI argument.
GROUP="$(sed -n 's/^GROUP=//p' /usr/share/flatcar/update.conf)"
if [[ "$GROUP" != stable && "$GROUP" != beta ]]; then
  echo "Missing or invalid GROUP in /usr/share/flatcar/update.conf: '$GROUP'" >&2
  exit 1
fi
CHANNEL="$CHANNEL_ARG"
if [[ "$GROUP" != "$CHANNEL_ARG" ]]; then
  echo "Booted channel ($GROUP) disagrees with requested channel ($CHANNEL_ARG); using booted channel" >&2
  CHANNEL="$GROUP"
fi

# shellcheck source=/dev/null
source /usr/share/flatcar/os-release
# shellcheck source=/dev/null
source /home/core/metadata-utils.sh

exec 9>/run/lock/update-flatcar.lock
flock --nonblock 9 || exit 0

STATUS_OUTPUT="$(update_engine_client -status)"
CURRENT_OP="$(echo "$STATUS_OUTPUT" | sed -n 's/^CURRENT_OP=//p')"
NEW_VERSION="$(echo "$STATUS_OUTPUT" | sed -n 's/^NEW_VERSION=//p')"
case "$CURRENT_OP" in
  UPDATE_STATUS_IDLE|UPDATE_STATUS_UPDATED_NEED_REBOOT) ;;
  UPDATE_STATUS_CHECKING_FOR_UPDATE|UPDATE_STATUS_UPDATE_AVAILABLE|UPDATE_STATUS_DOWNLOADING|UPDATE_STATUS_VERIFYING|UPDATE_STATUS_FINALIZING|UPDATE_STATUS_REPORTING_ERROR_EVENT|UPDATE_STATUS_ATTEMPTING_ROLLBACK)
    exit 0
    ;;
  *) echo "Unexpected update engine status: $STATUS_OUTPUT" >&2; exit 1 ;;
esac

if [[ "$CURRENT_OP" == UPDATE_STATUS_IDLE ]]; then
  set_metadata "os_update/reboot_required" ""
  set_metadata "os_update/timestamp" ""
fi

TARGET_VERSION="$(curl --fail --silent --show-error --proto '=https' --proto-redir '=https' \
  --connect-timeout 10 --max-time 30 --retry 3 "$VERSION_URL" | \
  jq -er --arg key "flatcar_${CHANNEL}_version" '.[$key] | strings | select(test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))')"

if [[ ! "$VERSION_ID" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid running Flatcar version: $VERSION_ID" >&2
  exit 1
fi

# A release rollback must not downgrade a running VM.
if [[ "$(printf '%s\n' "$VERSION_ID" "$TARGET_VERSION" | sort -V | head -n 1)" == "$TARGET_VERSION" ]]; then
  if [[ "$CURRENT_OP" == UPDATE_STATUS_UPDATED_NEED_REBOOT ]]; then
    update_engine_client -reset_status
  fi
  set_metadata "os_update/reboot_required" ""
  set_metadata "os_update/timestamp" ""
  exit 0
fi

if [[ "$CURRENT_OP" == UPDATE_STATUS_UPDATED_NEED_REBOOT ]]; then
  if [[ "$NEW_VERSION" == "$TARGET_VERSION" ]]; then
    exit 0
  fi
  update_engine_client -reset_status
  set_metadata "os_update/reboot_required" ""
  set_metadata "os_update/timestamp" ""
fi

# flatcar-update can exit before restoring SERVER when a payload download fails.
disable_updates() {
  sed -i '/^SERVER=/d' /etc/flatcar/update.conf
  echo 'SERVER=disabled' >> /etc/flatcar/update.conf
}
trap disable_updates EXIT

flatcar-update --to-version "$TARGET_VERSION" --disable-afterwards
