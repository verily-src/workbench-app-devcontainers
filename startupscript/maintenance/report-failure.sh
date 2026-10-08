#!/bin/bash

{ set +o xtrace; } 2>/dev/null
set -o errexit
set -o nounset
set -o pipefail

[[ "${SERVICE_RESULT:-unknown}" != success ]] || exit 0
readonly STATE_DIR="${1:-/var/lib/workbench-maintenance}"
readonly CLOUD="${WORKBENCH_CLOUD:-}"
readonly METADATA_OPTIONS=(--disable --fail --silent --show-error --noproxy '*' --connect-timeout 1 --max-time 2)
version="$(jq -er '.active_version | strings | select(test("^[0-9]{1,32}$"))' \
  "$STATE_DIR/boot.json" 2>/dev/null)" || version=unknown
readonly MESSAGE="Host maintenance failed; release $version. App startup is blocked."

report_gcp() {
  local failed=0 key value
  for key in message status; do
    if [[ "$key" == message ]]; then value="$MESSAGE"; else value=ERROR; fi
    curl "${METADATA_OPTIONS[@]}" --request PUT --data-binary "$value" --output /dev/null \
      --header 'Metadata-Flavor: Google' \
      "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/startup_script/$key" \
      >/dev/null 2>&1 || failed=1
  done
  return "$failed"
}

report_aws() {
  local token document region instance role credentials access secret session
  token="$(curl "${METADATA_OPTIONS[@]}" --request PUT \
    --header 'X-aws-ec2-metadata-token-ttl-seconds: 60' \
    http://169.254.169.254/latest/api/token 2>/dev/null)" || return 1
  [[ "$token" =~ ^[A-Za-z0-9+/=._-]+$ ]] || return 1
  imds_get() {
    printf 'header = "X-aws-ec2-metadata-token: %s"\n' "$token" |
      curl "${METADATA_OPTIONS[@]}" --config - "http://169.254.169.254/latest/$1" 2>/dev/null
  }
  document="$(imds_get dynamic/instance-identity/document)" || return 1
  region="$(jq -er '.region | strings | select(test("^[a-z]{2}(-[a-z]+)+-[0-9]+$"))' <<< "$document" 2>/dev/null)" || return 1
  instance="$(jq -er '.instanceId | strings | select(test("^i-([a-f0-9]{8}|[a-f0-9]{17})$"))' <<< "$document" 2>/dev/null)" || return 1
  role="$(imds_get meta-data/iam/security-credentials/)" || return 1
  [[ "$role" =~ ^[A-Za-z0-9+=,.@_-]{1,64}$ ]] || return 1
  credentials="$(imds_get "meta-data/iam/security-credentials/$role")" || return 1
  access="$(jq -er 'select(.Code == "Success") | .AccessKeyId | strings | select(test("^[A-Za-z0-9]+$"))' <<< "$credentials" 2>/dev/null)" || return 1
  secret="$(jq -er '.SecretAccessKey | strings | select(test("^[A-Za-z0-9+/=]+$"))' <<< "$credentials" 2>/dev/null)" || return 1
  session="$(jq -er '.Token | strings | select(test("^[A-Za-z0-9+/=]+$"))' <<< "$credentials" 2>/dev/null)" || return 1
  printf 'user = "%s:%s"\nheader = "X-Amz-Security-Token: %s"\n' "$access" "$secret" "$session" |
    curl --disable --fail --silent --show-error --connect-timeout 2 --max-time 5 \
      --proto '=https' --config - --aws-sigv4 "aws:amz:$region:ec2" --output /dev/null \
      --data-urlencode 'Action=CreateTags' --data-urlencode 'Version=2016-11-15' \
      --data-urlencode "ResourceId.1=$instance" \
      --data-urlencode 'Tag.1.Key=vwbapp:startup_script/message' --data-urlencode "Tag.1.Value=$MESSAGE" \
      --data-urlencode 'Tag.2.Key=vwbapp:startup_script/status' --data-urlencode 'Tag.2.Value=ERROR' \
      "https://ec2.$region.amazonaws.com/" >/dev/null 2>&1
}

case "$CLOUD" in
  gcp) report_gcp && { echo 'Host maintenance failure reported'; exit 0; } ;;
  aws) report_aws && { echo 'Host maintenance failure reported'; exit 0; } ;;
esac
echo 'reporting_failed: host maintenance failure could not reach cloud status' >&2
exit 1
