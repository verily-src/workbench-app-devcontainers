#!/bin/bash

# prefetch-oci-features.sh pre-downloads OCI devcontainer features to local
# directories, then rewrites devcontainer.json to use local paths. This avoids
# ghcr.io rate limits during devcontainer up.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

readonly CRANE_IMAGE="gcr.io/go-containerregistry/crane@sha256:d3a706262093746258f20107ab4e95536f9d6d45c8c3f3acf6b02b1801b440d6"

crane() {
  docker run --rm "${CRANE_IMAGE}" "$@"
}

readonly MAX_RETRIES=3
readonly RETRY_DELAY=5

retry() {
  local attempt
  for attempt in $(seq 1 "${MAX_RETRIES}"); do
    if "$@"; then
      return 0
    fi
    if [[ "${attempt}" -lt "${MAX_RETRIES}" ]]; then
      echo "Attempt ${attempt}/${MAX_RETRIES} failed, retrying in ${RETRY_DELAY}s..." >&2
      sleep "${RETRY_DELAY}"
    fi
  done
  return 1
}

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <path/to/devcontainer.json>" >&2
  exit 1
fi

readonly CONFIG_PATH="$1"

# Derive the project root from the config path.
# .devcontainer.json is at the project root; .devcontainer/devcontainer.json is one level down.
CONFIG_DIR="$(cd "$(dirname "${CONFIG_PATH}")" && pwd)"
if [[ "$(basename "${CONFIG_DIR}")" == ".devcontainer" ]]; then
  PROJECT_DIR="$(dirname "${CONFIG_DIR}")"
else
  PROJECT_DIR="${CONFIG_DIR}"
fi
readonly PROJECT_DIR
readonly FEATURES_DIR="${PROJECT_DIR}/.devcontainer/features"

# ref_to_dir_name converts an OCI feature reference to a namespaced directory
# name, avoiding collisions with local features (e.g., features/src/java).
#   ghcr.io/devcontainers/features/java@sha256:... -> devcontainers-features-java
#   ghcr.io/rocker-org/devcontainer-features/r-packages:1 -> rocker-org-devcontainer-features-r-packages
ref_to_dir_name() {
  local ref="$1"
  ref_to_resource "${ref}" \
    | sed 's|^[^/]*/||' \
    | tr '/' '-'
}

# ref_to_resource extracts the registry/path portion without the version or digest.
#   ghcr.io/devcontainers/features/java@sha256:... -> ghcr.io/devcontainers/features/java
#   ghcr.io/devcontainers/features/java:1          -> ghcr.io/devcontainers/features/java
ref_to_resource() {
  local ref="$1"
  echo "${ref}" | sed 's/@sha256:.*//' | sed 's/:[^/]*$//'
}

# Extract ghcr.io feature references that are JSON keys (followed by ":").
FEATURE_REFS=()
while IFS= read -r ref; do
  FEATURE_REFS+=("${ref}")
done < <(grep -o '"ghcr\.io/[^"]*"[[:space:]]*:' "${CONFIG_PATH}" | sed 's/[[:space:]]*:$//' | tr -d '"')

if [[ ${#FEATURE_REFS[@]} -eq 0 ]]; then
  echo "No OCI feature references found in ${CONFIG_PATH}"
  exit 0
fi

mkdir -p "${FEATURES_DIR}"

# Track which OCI refs were successfully prefetched, for installsAfter rewriting.
declare -A PREFETCHED_REFS  # OCI resource -> local path

for FEATURE_REF in "${FEATURE_REFS[@]}"; do
  DIR_NAME="$(ref_to_dir_name "${FEATURE_REF}")"
  LOCAL_DIR="${FEATURES_DIR}/${DIR_NAME}"
  RESOURCE="$(ref_to_resource "${FEATURE_REF}")"

  if [[ -d "${LOCAL_DIR}" ]] && [[ -f "${LOCAL_DIR}/devcontainer-feature.json" ]]; then
    echo "Already exists: ${LOCAL_DIR}, skipping download"
    PREFETCHED_REFS["${RESOURCE}"]="./.devcontainer/features/${DIR_NAME}"
    continue
  fi

  echo "Prefetching ${FEATURE_REF} -> ${LOCAL_DIR}"

  # For tag-based refs (no @sha256:), resolve to a digest first.
  RESOLVED_REF="${FEATURE_REF}"
  if [[ "${FEATURE_REF}" != *"@sha256:"* ]]; then
    DIGEST="$(retry crane digest "${FEATURE_REF}")" || {
      echo "WARNING: Failed to resolve digest for ${FEATURE_REF}, skipping" >&2
      continue
    }
    RESOLVED_REF="${RESOURCE}@${DIGEST}"
  fi

  MANIFEST="$(retry crane manifest "${RESOLVED_REF}")" || {
    echo "WARNING: Failed to fetch manifest for ${RESOLVED_REF}, skipping" >&2
    continue
  }

  LAYER_DIGEST="$(echo "${MANIFEST}" | jq -r '.layers[0].digest')"
  if [[ -z "${LAYER_DIGEST}" ]] || [[ "${LAYER_DIGEST}" == "null" ]]; then
    echo "WARNING: No layer found in manifest for ${RESOLVED_REF}, skipping" >&2
    continue
  fi

  BLOB_TAR="$(mktemp)"
  download_blob() {
    crane blob "${RESOURCE}@${LAYER_DIGEST}" > "${BLOB_TAR}"
  }
  retry download_blob || {
    echo "WARNING: Failed to download blob for ${RESOLVED_REF}, skipping" >&2
    rm -f "${BLOB_TAR}"
    continue
  }

  mkdir -p "${LOCAL_DIR}"
  tar -xf "${BLOB_TAR}" -C "${LOCAL_DIR}" || {
    echo "WARNING: Failed to extract blob for ${RESOLVED_REF}, skipping" >&2
    rm -f "${BLOB_TAR}"
    rm -rf "${LOCAL_DIR}"
    continue
  }
  rm -f "${BLOB_TAR}"

  if [[ ! -f "${LOCAL_DIR}/devcontainer-feature.json" ]]; then
    echo "WARNING: Downloaded feature missing devcontainer-feature.json, skipping" >&2
    rm -rf "${LOCAL_DIR}"
    continue
  fi

  PREFETCHED_REFS["${RESOURCE}"]="./.devcontainer/features/${DIR_NAME}"
  echo "Prefetched ${FEATURE_REF} -> ${LOCAL_DIR}"
done

if [[ ${#PREFETCHED_REFS[@]} -eq 0 ]]; then
  echo "No features were prefetched"
  exit 0
fi

# Rewrite devcontainer.json: replace OCI refs with local paths.
for FEATURE_REF in "${FEATURE_REFS[@]}"; do
  RESOURCE="$(ref_to_resource "${FEATURE_REF}")"
  LOCAL_PATH="${PREFETCHED_REFS[${RESOURCE}]:-}"
  if [[ -z "${LOCAL_PATH}" ]]; then
    continue
  fi

  # shellcheck disable=SC2016 # backslash-ampersand is intentional sed replacement syntax
  ESCAPED_REF="$(printf '%s' "${FEATURE_REF}" | sed 's/[[\.*^$()+?{|]/\\&/g')"
  sed -i "s|\"${ESCAPED_REF}\"|\"${LOCAL_PATH}\"|g" "${CONFIG_PATH}"
done

# Rewrite installsAfter in all features, not just prefetched ones. Local features
# like workbench-tools may reference OCI features we've prefetched.
for FEATURE_JSON in "${FEATURES_DIR}"/*/devcontainer-feature.json; do
  if [[ ! -f "${FEATURE_JSON}" ]]; then
    continue
  fi

  for INSTALL_AFTER_RESOURCE in "${!PREFETCHED_REFS[@]}"; do
    INSTALL_AFTER_LOCAL="${PREFETCHED_REFS[${INSTALL_AFTER_RESOURCE}]}"
    sed -i "s|\"${INSTALL_AFTER_RESOURCE}\"|\"${INSTALL_AFTER_LOCAL}\"|g" "${FEATURE_JSON}"
  done
done

echo "Prefetched ${#PREFETCHED_REFS[@]} of ${#FEATURE_REFS[@]} OCI features"
