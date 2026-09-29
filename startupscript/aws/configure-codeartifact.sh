#!/bin/bash

# Sourced by the AWS post-startup hook for virtual-browser apps. Requires emit,
# get_metadata_value, RUN_AS_LOGIN_USER, CLOUD_SCRIPT_DIR and WORK_DIRECTORY.

readonly CODEARTIFACT_REFRESH_SCRIPT="/usr/local/bin/refresh-codeartifact-login.sh"
readonly CODEARTIFACT_CONFIG="/etc/workbench-codeartifact.conf"

CODEARTIFACT_DOMAIN="$(get_metadata_value codeartifact-domain-name)"
readonly CODEARTIFACT_DOMAIN

if [[ -z "${CODEARTIFACT_DOMAIN}" || "${CODEARTIFACT_DOMAIN}" == "None" ]]; then
  emit "No codeartifact-domain-name tag set, skipping CodeArtifact configuration"
  return 0
fi

# Use the instance's own account and region, not the workspace profile's.
# Keep the IMDS token out of xtrace. wget retries itself because retry's
# messages go to stdout and would be captured.
{ set +o xtrace; } 2>/dev/null
imds_token="$(wget --tries=5 --waitretry=5 --retry-connrefused --method=PUT --header "X-aws-ec2-metadata-token-ttl-seconds:600" -q -O - http://169.254.169.254/latest/api/token)"
identity_document="$(wget --tries=5 --waitretry=5 --retry-connrefused --header "X-aws-ec2-metadata-token: ${imds_token}" -q -O - http://169.254.169.254/latest/dynamic/instance-identity/document)"
unset imds_token
set -o xtrace
CODEARTIFACT_OWNER="$(jq -er '.accountId' <<< "${identity_document}")"
readonly CODEARTIFACT_OWNER
CODEARTIFACT_REGION="$(jq -er '.region' <<< "${identity_document}")"
readonly CODEARTIFACT_REGION

emit "Configuring pip and npm to use CodeArtifact domain ${CODEARTIFACT_DOMAIN} in ${CODEARTIFACT_REGION}"

# Settings only, no credentials. %q keeps paths with spaces intact.
printf 'CODEARTIFACT_DOMAIN=%q\nCODEARTIFACT_OWNER=%q\nCODEARTIFACT_REGION=%q\nCODEARTIFACT_USER_HOME=%q\n' \
  "${CODEARTIFACT_DOMAIN}" "${CODEARTIFACT_OWNER}" "${CODEARTIFACT_REGION}" "${WORK_DIRECTORY}" \
  > "${CODEARTIFACT_CONFIG}"
chmod 644 "${CODEARTIFACT_CONFIG}"
install -m 755 "${CLOUD_SCRIPT_DIR}/refresh-codeartifact-login.sh" "${CODEARTIFACT_REFRESH_SCRIPT}"

# Don't fail app creation; the worker retries every five minutes.
if ! ${RUN_AS_LOGIN_USER} "'${CODEARTIFACT_REFRESH_SCRIPT}' --start"; then
  emit "WARNING: could not configure CodeArtifact tokens; the worker will retry"
fi
