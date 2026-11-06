#!/bin/bash

# account-change.sh
#
# Sourced in the app container by post-startup.sh and remount-on-restart.sh.
# Turning sharing on for an existing VM switches its service account to the
# workspace's shared-apps reader or writer account. The home directory outlives
# that switch, so credentials cached there still belong to the VM's owner.
#
# check_service_account compares the VM's service account with the one recorded
# at the last start and, if it changed, deletes the cached git, SSH and gcloud
# credentials. The caller then logs the Workbench CLI out and in again, and
# calls record_service_account once that has succeeded.
#
# Expects USER_NAME, WORK_DIRECTORY, USER_WORKBENCH_CONFIG_DIR and CLOUD.

SERVICE_ACCOUNT_EMAIL=""
export ACCOUNT_CHANGED=false
# Readers' account can't write to buckets, so resource-mount.sh mounts them read-only.
export SHARED_APPS_READER=false
readonly SERVICE_ACCOUNT_RECORD="${USER_WORKBENCH_CONFIG_DIR}/service-account"

function is_shared_apps_account() {
  [[ "$1" == shared-apps-reader@* || "$1" == shared-apps-writer@* ]]
}
readonly -f is_shared_apps_account

function clear_cached_credentials() {
  local gcloud_dir="${WORK_DIRECTORY}/.config/gcloud"
  # As the user, so links in the home directory can't point the deletions elsewhere.
  sudo -u "${USER_NAME}" rm -rf -- \
    "${WORK_DIRECTORY}/.git-credentials" \
    "${WORK_DIRECTORY}/.config/git/credentials" \
    "${WORK_DIRECTORY}/.cache/git/credential" \
    "${gcloud_dir}/credentials.db" \
    "${gcloud_dir}/access_tokens.db" \
    "${gcloud_dir}/legacy_credentials" \
    "${gcloud_dir}/application_default_credentials.json"
  # SSH identities, including the owner's key that git-setup.sh fetched.
  if [[ -d "${WORK_DIRECTORY}/.ssh" ]]; then
    sudo -u "${USER_NAME}" find "${WORK_DIRECTORY}/.ssh" -maxdepth 1 -name 'id_*' -type f -delete
  fi
  # Without an account property, gcloud uses the VM's service account.
  if [[ -d "${gcloud_dir}/configurations" ]]; then
    sudo -u "${USER_NAME}" find "${gcloud_dir}/configurations" -maxdepth 1 -name 'config_*' -type f \
      -exec sed -i '/^account[[:space:]]*=/d' {} +
  fi
}
readonly -f clear_cached_credentials

function check_service_account() {
  if [[ "${CLOUD}" != "gcp" ]]; then
    return 0
  fi
  if ! SERVICE_ACCOUNT_EMAIL="$(curl --retry 5 -s -f -H "Metadata-Flavor: Google" \
      "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email")" \
      || [[ -z "${SERVICE_ACCOUNT_EMAIL}" ]]; then
    SERVICE_ACCOUNT_EMAIL=""
    echo "WARNING: could not read the VM's service account; not checking for an account change." >&2
    return 0
  fi
  if [[ "${SERVICE_ACCOUNT_EMAIL}" == shared-apps-reader@* ]]; then
    SHARED_APPS_READER=true
  fi

  local previous
  if [[ -f "${SERVICE_ACCOUNT_RECORD}" ]]; then
    previous="$(cat "${SERVICE_ACCOUNT_RECORD}")"
  elif is_shared_apps_account "${SERVICE_ACCOUNT_EMAIL}"; then
    # No record: the home directory may predate these scripts, so assume a change.
    previous=""
  else
    previous="${SERVICE_ACCOUNT_EMAIL}"
  fi
  if [[ "${previous}" != "${SERVICE_ACCOUNT_EMAIL}" ]]; then
    emit "The VM's service account changed to ${SERVICE_ACCOUNT_EMAIL}; clearing cached credentials."
    ACCOUNT_CHANGED=true
    clear_cached_credentials
  fi
}
readonly -f check_service_account

function record_service_account() {
  if [[ -n "${SERVICE_ACCOUNT_EMAIL}" ]]; then
    printf '%s\n' "${SERVICE_ACCOUNT_EMAIL}" | sudo -u "${USER_NAME}" tee "${SERVICE_ACCOUNT_RECORD}" > /dev/null
  fi
}
readonly -f record_service_account
