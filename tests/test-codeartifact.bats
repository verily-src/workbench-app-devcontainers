#!/usr/bin/env bats

# Run on Linux: bats tests/test-codeartifact.bats. AWS and package managers are
# stubbed; file permissions, subprocesses and flock use the real OS behavior.
setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/.." && pwd)"
  export TEST_CODEARTIFACT_DIR="${BATS_TEST_TMPDIR}"
  export TEST_APP_HOME="${BATS_TEST_TMPDIR}/app home"
  export TEST_REFRESH_SCRIPT="${BATS_TEST_TMPDIR}/refresh.sh"
  export XDG_CONFIG_HOME="${TEST_APP_HOME}/.config"
  mkdir -p "${TEST_APP_HOME}" "${BATS_TEST_TMPDIR}/bin"
  touch "${BATS_TEST_TMPDIR}/calls" "${BATS_TEST_TMPDIR}/sleeps" "${BATS_TEST_TMPDIR}/pids"
  touch "${BATS_TEST_TMPDIR}/worker-pids"
  printf 'CODEARTIFACT_DOMAIN=mirror\nCODEARTIFACT_OWNER=123456789012\nCODEARTIFACT_REGION=us-east-1\nCODEARTIFACT_USER_HOME=%q\n' \
    "${TEST_APP_HOME}" > "${BATS_TEST_TMPDIR}/config"
  sed "s|source /etc/workbench-codeartifact.conf|source '${BATS_TEST_TMPDIR}/config'|" \
    "${REPO_ROOT}/startupscript/aws/refresh-codeartifact-login.sh" > "${TEST_REFRESH_SCRIPT}"
  chmod +x "${TEST_REFRESH_SCRIPT}"

  cat > "${BATS_TEST_TMPDIR}/bin/aws" <<'EOF'
#!/bin/bash
set -eu
for variable in AWS_PROFILE AWS_DEFAULT_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY \
  AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_ROLE_ARN AWS_ROLE_SESSION_NAME AWS_WEB_IDENTITY_TOKEN_FILE \
  AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_CONTAINER_CREDENTIALS_FULL_URI \
  AWS_CONTAINER_AUTHORIZATION_TOKEN AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE; do
  if [[ -v "${variable}" ]]; then
    echo "Unexpected credential source: ${variable}" >&2
    exit 99
  fi
done
[[ "${AWS_CONFIG_FILE}" == /dev/null && "${AWS_SHARED_CREDENTIALS_FILE}" == /dev/null ]]
[[ "${BOTO_CONFIG}" == /dev/null && "${AWS_EC2_METADATA_DISABLED}" == false ]]
[[ "${AWS_EC2_METADATA_SERVICE_ENDPOINT}" == http://169.254.169.254 ]]
[[ "${PIP_USER}" == true && ! -v PIP_SITE && ! -v PIP_GLOBAL && ! -v PIP_CONFIG_FILE ]]
echo "$*" >> "${TEST_CODEARTIFACT_DIR}/calls"
tool="${4}"
if [[ -e "${TEST_CODEARTIFACT_DIR}/fail-${tool}" ]]; then
  exit 1
fi
if [[ "${tool}" == npm ]]; then
  config="${NPM_CONFIG_USERCONFIG}"
else
  config="${XDG_CONFIG_HOME}/pip/pip.conf"
fi
echo fake-token > "${config}"
# Simulate a client rewriting the file with permissive defaults.
chmod 644 "${config}"
EOF

  cat > "${BATS_TEST_TMPDIR}/bin/sleep" <<'EOF'
#!/bin/bash
echo "$1" >> "${TEST_CODEARTIFACT_DIR}/sleeps"
[[ "$1" == 5 ]] && exit 0
echo "$$" >> "${TEST_CODEARTIFACT_DIR}/pids"
# Tests explicitly advance the six-hour/five-minute clock.
while [[ ! -e "${TEST_CODEARTIFACT_DIR}/advance-clock" ]]; do
  /bin/sleep 0.02
done
rm "${TEST_CODEARTIFACT_DIR}/advance-clock"
EOF

  cat > "${BATS_TEST_TMPDIR}/bin/nohup" <<'EOF'
#!/bin/bash
echo "$$" >> "${TEST_CODEARTIFACT_DIR}/worker-pids"
echo "$$" >> "${TEST_CODEARTIFACT_DIR}/pids"
exec /usr/bin/nohup "$@"
EOF
  chmod +x "${BATS_TEST_TMPDIR}/bin/"*
  export PATH="${BATS_TEST_TMPDIR}/bin:${PATH}"
}

teardown() {
  # Kill only processes launched by this test, including simulated sleeps.
  while read -r pid; do
    kill "${pid}" 2>/dev/null || true
  done < "${BATS_TEST_TMPDIR}/pids"
}

wait_for_count() {
  local file="$1" pattern="$2" expected="$3" attempt
  for ((attempt = 0; attempt < 200; attempt++)); do
    if [[ "$(grep -c -- "${pattern}" "${file}" || true)" == "${expected}" ]]; then
      return 0
    fi
    /bin/sleep 0.02
  done
  echo "Timed out waiting for ${expected} occurrences of ${pattern} in ${file}" >&2
  cat "${file}" >&2
  return 1
}

@test "refresh uses instance credentials without changing the caller's profile" {
  export AWS_PROFILE=workspace-bucket AWS_DEFAULT_PROFILE=workspace-bucket
  export AWS_ACCESS_KEY_ID=fake AWS_SECRET_ACCESS_KEY=fake AWS_SESSION_TOKEN=fake AWS_SECURITY_TOKEN=fake
  export AWS_ROLE_ARN=fake AWS_ROLE_SESSION_NAME=fake AWS_WEB_IDENTITY_TOKEN_FILE=/missing
  export AWS_CONTAINER_CREDENTIALS_RELATIVE_URI=/fake AWS_CONTAINER_CREDENTIALS_FULL_URI=http://invalid
  export AWS_CONTAINER_AUTHORIZATION_TOKEN=fake AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE=/missing
  export AWS_CONFIG_FILE=/missing AWS_SHARED_CREDENTIALS_FILE=/missing BOTO_CONFIG=/missing
  export AWS_EC2_METADATA_DISABLED=true AWS_EC2_METADATA_SERVICE_ENDPOINT=http://invalid
  export PIP_CONFIG_FILE=/missing PIP_SITE=true PIP_GLOBAL=true npm_config_userconfig=/missing

  run "${TEST_REFRESH_SCRIPT}"
  [ "$status" -eq 0 ]
  [ "${AWS_PROFILE}" = workspace-bucket ]
  [ "${AWS_CONFIG_FILE}" = /missing ]
  [ "$(wc -l < "${BATS_TEST_TMPDIR}/calls")" -eq 2 ]
  grep -q -- '--tool npm .*--repository npm-mirror .*--duration-seconds 43200' "${BATS_TEST_TMPDIR}/calls"
  grep -q -- '--tool pip .*--repository pypi-mirror .*--duration-seconds 43200' "${BATS_TEST_TMPDIR}/calls"
}

@test "both token files are private" {
  run "${TEST_REFRESH_SCRIPT}"
  [ "$status" -eq 0 ]
  [ "$(stat -c '%a' "${TEST_APP_HOME}/.npmrc")" = 600 ]
  [ "$(stat -c '%a' "${XDG_CONFIG_HOME}/pip/pip.conf")" = 600 ]
  [[ "$output" != *fake-token* ]]
}

@test "npm failure still refreshes pip and returns failure" {
  touch "${BATS_TEST_TMPDIR}/fail-npm"
  run "${TEST_REFRESH_SCRIPT}"
  [ "$status" -eq 1 ]
  [ "$(grep -c -- '--tool npm' "${BATS_TEST_TMPDIR}/calls")" -eq 5 ]
  [ "$(grep -c -- '--tool pip' "${BATS_TEST_TMPDIR}/calls")" -eq 1 ]
  [ "$(cat "${XDG_CONFIG_HOME}/pip/pip.conf")" = fake-token ]
}

@test "repeated starts refresh immediately but keep a single periodic worker" {
  run "${TEST_REFRESH_SCRIPT}" --start
  [ "$status" -eq 0 ]
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^21600$' 1
  run "${TEST_REFRESH_SCRIPT}" --start
  [ "$status" -eq 0 ]
  wait_for_count "${BATS_TEST_TMPDIR}/worker-pids" '^[0-9]' 2
  duplicate_pid="$(tail -n 1 "${BATS_TEST_TMPDIR}/worker-pids")"
  for ((attempt = 0; attempt < 200; attempt++)); do
    kill -0 "${duplicate_pid}" 2>/dev/null || break
    /bin/sleep 0.02
  done
  [ "$(grep -c '^21600$' "${BATS_TEST_TMPDIR}/sleeps")" -eq 1 ]
  [ "$(grep -c -- '--tool npm' "${BATS_TEST_TMPDIR}/calls")" -eq 2 ]
  touch "${BATS_TEST_TMPDIR}/advance-clock"
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^21600$' 2
  [ "$(grep -c -- '--tool pip' "${BATS_TEST_TMPDIR}/calls")" -eq 3 ]
}

@test "periodic failure retries after five minutes and recovers to six hours" {
  run "${TEST_REFRESH_SCRIPT}" --start
  [ "$status" -eq 0 ]
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^21600$' 1
  touch "${BATS_TEST_TMPDIR}/fail-npm" "${BATS_TEST_TMPDIR}/advance-clock"
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^300$' 1
  rm "${BATS_TEST_TMPDIR}/fail-npm"
  touch "${BATS_TEST_TMPDIR}/advance-clock"
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^21600$' 2
  [ "$(grep -c -- '--tool pip' "${BATS_TEST_TMPDIR}/calls")" -eq 3 ]
}

@test "a failed startup still starts the worker for recovery" {
  touch "${BATS_TEST_TMPDIR}/fail-pip"
  run "${TEST_REFRESH_SCRIPT}" --start
  [ "$status" -eq 1 ]
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^300$' 1
  rm "${BATS_TEST_TMPDIR}/fail-pip"
  touch "${BATS_TEST_TMPDIR}/advance-clock"
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^21600$' 1
}

@test "a stopped worker can restart even while its old sleep is alive" {
  run "${TEST_REFRESH_SCRIPT}" --start
  [ "$status" -eq 0 ]
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^21600$' 1
  kill "$(head -n 1 "${BATS_TEST_TMPDIR}/worker-pids")"
  run "${TEST_REFRESH_SCRIPT}" --start
  [ "$status" -eq 0 ]
  wait_for_count "${BATS_TEST_TMPDIR}/sleeps" '^21600$' 2
}

@test "configuration skips instances without a CodeArtifact tag" {
  export TEST_SETUP_SCRIPT="${REPO_ROOT}/startupscript/aws/configure-codeartifact.sh"
  run bash -c 'set -euo pipefail; get_metadata_value() { echo None; }; emit() { :; }; source "$TEST_SETUP_SCRIPT"'
  [ "$status" -eq 0 ]
  [ ! -s "${BATS_TEST_TMPDIR}/calls" ]
  [ ! -s "${BATS_TEST_TMPDIR}/worker-pids" ]
}
