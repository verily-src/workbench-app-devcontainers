#!/bin/bash
# Verifies the fluent-bit log pipeline used on workspace VMs: that Docker log
# lines are parsed, labelled with the container that produced them and given a
# severity derived from the line itself.
#
# The test feeds synthetic Docker log files to the real fluent-bit image and
# checks the records it emits, so it needs Docker and network access.
#
# Usage: tests/test-fluent-bit-logging.sh

set -o errexit
set -o nounset
set -o pipefail

readonly BUTANE_DIR="startupscript/butane"
readonly FLUENT_BIT_IMAGE="${FLUENT_BIT_IMAGE:-cr.fluentbit.io/fluent/fluent-bit:2.0-debug}"

# Two containers: one whose log lines carry the Docker log driver's name tag
# (the daemon default on workspace VMs), and one without it, which has to be
# resolved from the container's config file instead.
readonly TAGGED_ID="1111111111111111111111111111111111111111111111111111111111111111"
readonly UNTAGGED_ID="2222222222222222222222222222222222222222222222222222222222222222"

WORK_DIR="$(mktemp -d)"
readonly WORK_DIR
trap 'rm -rf "${WORK_DIR}"' EXIT

function write_container_fixture {
  local container_id="$1"
  local container_name="$2"
  local container_dir="${WORK_DIR}/containers/${container_id}"

  mkdir -p "${container_dir}"
  # A trimmed down config.v2.json. "MountPoints" is included because it holds a
  # "Name" key of its own, which the container name lookup must not pick up.
  cat > "${container_dir}/config.v2.json" <<EOF
{"ID":"${container_id}","Name":"/${container_name}","MountPoints":{"/data":{"Name":"some-volume"}}}
EOF
}

function docker_log_line {
  local message="$1"
  local timestamp="$2"
  local attrs="$3"

  printf '{"log":"%s\\n","stream":"stderr",%s"time":"%s"}\n' \
    "${message}" "${attrs}" "${timestamp}"
}

# Builds a copy of the AWS config that reads the fixtures and prints records to
# stdout instead of shipping them to CloudWatch. The journal inputs are dropped
# because this test only covers container logs.
function write_test_config {
  awk '
    BEGIN { RS = ""; ORS = "\n\n" }
    /Name systemd/ { next }
    /cloudwatch_logs/ {
      print "[OUTPUT]\n    Name stdout\n    Match vm.*\n    Format json_lines"
      next
    }
    { print }
  ' "${BUTANE_DIR}/aws/fluent-bit.conf" \
    | sed -e "s|/var/lib/fluent-bit/flb_docker.db|${WORK_DIR}/flb_docker.db|" \
      > "${WORK_DIR}/fluent-bit.conf"
}

function run_fluent_bit {
  timeout 30 docker run --rm \
    -v "${WORK_DIR}/fluent-bit.conf:/fluent-bit/etc/fluent-bit.conf:ro" \
    -v "${PWD}/${BUTANE_DIR}/severity.lua:/fluent-bit/scripts/severity.lua:ro" \
    -v "${PWD}/${BUTANE_DIR}/container-name.lua:/fluent-bit/scripts/container-name.lua:ro" \
    -v "${WORK_DIR}/containers:/var/lib/docker/containers:ro" \
    -v "${WORK_DIR}:${WORK_DIR}" \
    "${FLUENT_BIT_IMAGE}" 2>&1 | grep '^{' || true
}

function assert_record {
  local description="$1"
  local expected="$2"

  if ! grep -qF -- "${expected}" "${WORK_DIR}/records.json"; then
    echo "FAIL: ${description}"
    echo "  expected a record containing: ${expected}"
    exit 1
  fi
  echo "PASS: ${description}"
}

if [[ ! -d "${BUTANE_DIR}" ]]; then
  echo "ERROR: run this script from the repository root"
  exit 1
fi

write_container_fixture "${TAGGED_ID}" "jupyterlab"
write_container_fixture "${UNTAGGED_ID}" "proxy-agent"

{
  docker_log_line \
    "[I 2026-01-01 10:00:00.000 ServerApp] 200 GET /api/contents/notebook.ipynb (user@10.0.0.1) 1.23ms" \
    "2026-01-01T10:00:00.000000001Z" '"attrs":{"tag":"jupyterlab"},'
  docker_log_line \
    "[E 2026-01-01 10:00:01.000 ServerApp] Uncaught exception GET /api/contents" \
    "2026-01-01T10:00:01.000000001Z" '"attrs":{"tag":"jupyterlab"},'
  docker_log_line \
    "printing the word ERROR mid line is not a level marker" \
    "2026-01-01T10:00:02.000000001Z" '"attrs":{"tag":"jupyterlab"},'
} > "${WORK_DIR}/containers/${TAGGED_ID}/${TAGGED_ID}-json.log"

docker_log_line "2026/01/01 10:00:03 Forwarded request to backend" \
  "2026-01-01T10:00:03.000000001Z" "" \
  > "${WORK_DIR}/containers/${UNTAGGED_ID}/${UNTAGGED_ID}-json.log"

write_test_config
run_fluent_bit > "${WORK_DIR}/records.json"

if [[ ! -s "${WORK_DIR}/records.json" ]]; then
  echo "FAIL: fluent-bit emitted no records"
  exit 1
fi

# The docker parser must be registered, otherwise the whole Docker JSON line is
# forwarded as one opaque string instead of a message plus fields.
assert_record "docker log lines are parsed" \
  '"log":"[I 2026-01-01 10:00:00.000 ServerApp] 200 GET /api/contents/notebook.ipynb (user@10.0.0.1) 1.23ms'
assert_record "name comes from the docker log tag" '"container_name":"jupyterlab"'
assert_record "name falls back to the container config" '"container_name":"proxy-agent"'
assert_record "short container id is added" "\"container_id\":\"${UNTAGGED_ID:0:12}\""
assert_record "jupyter error lines are ERROR" '"severity":"ERROR"'
assert_record "jupyter info lines are INFO" '"severity":"INFO"'

if [[ "$(grep -cF '"severity":"ERROR"' "${WORK_DIR}/records.json")" != "1" ]]; then
  echo "FAIL: a level word mid message should not change the severity"
  exit 1
fi
echo "PASS: level words mid message are ignored"

echo "All fluent-bit logging checks passed"
