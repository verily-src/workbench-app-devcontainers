#!/bin/bash

# metadata-utils.sh defines functions for gcp instance attributes and guest attributes. This script is intended to be sourced from other scripts
# to retrieve or modify instance attributes. It is run on the VM host.

# Retrieves an instance attributes set on the VM. If the attribute is not set, it returns the default value.
function get_metadata_value() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_metadata_value <tag> <default-value>"
    exit 1
  fi
  local metadata_path="${1}"
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata/computeMetadata/v1/instance/attributes/${metadata_path}" || echo "${2}"
}
readonly -f get_metadata_value 

# Retrieves instance guest attributes on GCE VM. If the attribute is not set, it returns the default value.
function get_guest_attribute() {
  if [[ $# -lt 2 ]]; then
    echo "usage: get_guest_attribute <key> <default-value>"
    exit 1
  fi
  local key="${1}"
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}" || echo "${2}"
}
readonly -f get_guest_attribute

# Sets guest attributes on the GCE VM.
function set_metadata() {
  local key="$1"  
  local value="$2" 
  echo "Setting guest attributes ${key} to ${value}"
  curl -s -X PUT --data "${value}" \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/guest-attributes/${key}"
}
readonly -f set_metadata


# Returns 0 if the VM carries the share-enabled-app network tag, which WSM sets
# on VMs whose apps can be shared, and 1 if it doesn't. If the tags can't be
# read, logs a warning and returns 2.
function is_share_enabled_vm() {
  local tags shared
  # Compare jq's output, not its exit status: jq 1.6 exits 0 on empty input.
  if ! tags="$(curl --retry 5 -s -f \
      -H "Metadata-Flavor: Google" \
      "http://metadata.google.internal/computeMetadata/v1/instance/tags")" \
      || ! shared="$(jq -r 'if type == "array" then any(.[]; . == "share-enabled-app") else error end' \
        <<< "${tags}" 2>/dev/null)" \
      || [[ "${shared}" != true && "${shared}" != false ]]; then
    echo "WARNING: could not read the VM's network tags." >&2
    return 2
  fi
  [[ "${shared}" == true ]]
}
readonly -f is_share_enabled_vm

# Returns 0 if the VM's service account differs from the one in <record-file>,
# which record_service_account writes once the caller has acted on the change.
# Turning sharing on for an existing VM switches its service account. Without a
# record, only the shared-apps accounts count as a change, since the VM may
# predate the record. Returns 1 if unchanged, or if the account can't be read.
function service_account_changed() {
  local record="$1" current previous
  if ! current="$(get_service_account_email)" || [[ -z "${current}" ]]; then
    echo "WARNING: could not read the VM's service account." >&2
    return 1
  fi
  if [[ -f "${record}" ]]; then
    previous="$(cat "${record}")"
  elif [[ "${current}" == shared-apps-reader@* || "${current}" == shared-apps-writer@* ]]; then
    previous=""
  else
    previous="${current}"
  fi
  [[ "${current}" != "${previous}" ]]
}
readonly -f service_account_changed

function get_service_account_email() {
  curl --retry 5 -s -f \
    -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"
}
readonly -f get_service_account_email

function record_service_account() {
  local email
  if email="$(get_service_account_email)" && [[ -n "${email}" ]]; then
    printf '%s\n' "${email}" > "$1"
  fi
}
readonly -f record_service_account

# Reports in the startup_script/account_change guest attribute whether this VM
# handles a service-account change, which WSM checks before turning sharing on.
# This host's scripts do; the app container does if its copies of the startup
# scripts in <startupscript-dir> run the check. Otherwise clears the attribute.
function report_account_change_support() {
  local dir="$1" value=""
  if grep -qs check_service_account "${dir}/post-startup.sh" \
      && grep -qs check_service_account "${dir}/remount-on-restart.sh"; then
    value="supported"
  fi
  set_metadata "startup_script/account_change" "${value}"
}
readonly -f report_account_change_support
