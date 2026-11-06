#!/bin/bash

# vm-metadata.sh

# Queries a single piece of VM metadata from IMDS
function _get_compute_metadata() {
  curl --retry 5 -s -f --noproxy "*" -H "Metadata:true" "http://169.254.169.254/metadata/instance/compute${1}"
}

# Retrieves a read-only vwbusr: instance attribute on the VM.
function get_metadata_value() {
  if [[ -z "$1" ]]; then
    echo "usage: get_metadata_value <key>"
    exit 1
  fi

  _get_compute_metadata "/tagsList?api-version=2025-04-07" |
    jq -r --arg key "vwbusr:${1}" 'map(select(.name == $key))[0].value // ""'
}
readonly -f get_metadata_value

# Sets metadata on the Azure VM with the given key and value.
# Metadata Table storage keys set from the instance are prefixed with vwbapp:
function set_metadata() (
  { set +o xtrace; } 2>/dev/null

  # RowKey cannot contain /, so we replace every / with .
  local row_key="vwbapp:${1//\//.}"
  local value="${2}"

  local vm_name
  vm_name=$(_get_compute_metadata "/name?api-version=2025-04-07&format=text")

  local resource_id
  resource_id="$(get_metadata_value "wb-resource-id" "")"

  local request_uri
  request_uri=$(
    ${RUN_AS_LOGIN_USER} "/usr/bin/wb resource credentials --name ${vm_name} --duration 3600 --format json" |
      jq -er --arg entity "(PartitionKey='${resource_id}',RowKey='${row_key}')" \
        '.metadata | (.resourceUri // empty) + $entity + "?" + (.sasToken // empty)')

  local payload
  payload=$(jq -n \
    --arg PartitionKey "${resource_id}" \
    --arg RowKey "${row_key}" \
    --arg Value "${value}" '$ARGS.named')

  curl --retry 5 -s -f -H 'Accept: application/json;odata=nometadata' -H 'Content-Type: application/json' \
    -X PUT --data "${payload}" "${request_uri}"
)
readonly -f set_metadata
