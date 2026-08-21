#!/usr/bin/env bats
# Unit tests for startupscript/butane/probe-user-access.sh.
#
# The script is driven end to end against fixtures: a stub PATH (docker, date,
# sleep, pgrep), a stub metadata-utils.sh, a fake /proc tree and a fake cgroup
# tree. The stubbed clock makes the sampling arithmetic exact, so the tests can
# assert precise CPU percentages and threshold boundaries.

setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
}

setup() {
    DIR="$(cd "$(dirname "${BATS_TEST_FILENAME}")" >/dev/null 2>&1 && pwd)"
    REPO_ROOT="$(cd "${DIR}/.." && pwd)"
    SCRIPT="${REPO_ROOT}/startupscript/butane/probe-user-access.sh"

    # BATS_TEST_TMPDIR needs bats >= 1.4; fall back for older packages.
    TMP="${BATS_TEST_TMPDIR:-$(mktemp -d)}"
    STUB_BIN="${TMP}/bin"
    PROC="${TMP}/proc"
    CGROUP="${TMP}/cgroup"
    STATE="${TMP}/state"
    METADATA_LOG="${TMP}/metadata.log"
    CLOCK_QUEUE="${TMP}/clock"
    mkdir -p "${STUB_BIN}" "${PROC}" "${CGROUP}" "${STATE}"
    : > "${METADATA_LOG}"
    : > "${CLOCK_QUEUE}"

    # An idle VM load average, so any fallback to /proc/loadavg reads as idle
    # unless a test overrides it.
    echo "0.00 0.01 0.02 1/234 5678" > "${PROC}/loadavg"

    # ---- stub: docker -------------------------------------------------------
    # Only knows about one container, named by STUB_TARGET_CONTAINER. Anything
    # else is reported as unknown, exactly like a missing container.
    cat > "${STUB_BIN}/docker" <<'EOF'
#!/bin/bash
if [[ "$*" == "container inspect -f {{.State.Running}} proxy-agent" ]]; then
    echo "${STUB_PROXY_RUNNING:-false}"
    exit 0
fi
if [[ "$1" == "inspect" && "$2" == "--format" ]]; then
    requested="${!#}"
    if [[ "${requested}" == "${STUB_TARGET_CONTAINER:-}" ]]; then
        echo "${STUB_TARGET_INSPECT}"
        exit 0
    fi
    echo "Error: No such object: ${requested}" >&2
    exit 1
fi
exit 1
EOF

    # ---- stub: date ---------------------------------------------------------
    # `date +%s%N` pops the next value off a queue so elapsed time is exact.
    # Every other invocation falls through to the real date.
    cat > "${STUB_BIN}/date" <<'EOF'
#!/bin/bash
if [[ "${1:-}" == "+%s%N" ]]; then
    if [[ -s "${STUB_CLOCK_QUEUE}" ]]; then
        head -n 1 "${STUB_CLOCK_QUEUE}"
        tail -n +2 "${STUB_CLOCK_QUEUE}" > "${STUB_CLOCK_QUEUE}.next"
        mv "${STUB_CLOCK_QUEUE}.next" "${STUB_CLOCK_QUEUE}"
    else
        echo 0
    fi
    exit 0
fi
for candidate in /bin/date /usr/bin/date; do
    [[ -x "${candidate}" ]] && exec "${candidate}" "$@"
done
echo "no real date found" >&2
exit 1
EOF

    # ---- stub: sleep --------------------------------------------------------
    # Instant, but runs STUB_SLEEP_HOOK so a test can advance the fake
    # container's CPU counter "while" the script is sampling.
    cat > "${STUB_BIN}/sleep" <<'EOF'
#!/bin/bash
if [[ -n "${STUB_SLEEP_HOOK:-}" ]]; then
    eval "${STUB_SLEEP_HOOK}"
fi
exit 0
EOF

    # ---- stub: pgrep --------------------------------------------------------
    cat > "${STUB_BIN}/pgrep" <<'EOF'
#!/bin/bash
[[ "${STUB_SSH_ACTIVE:-false}" == "true" ]] || exit 1
echo "12345 sshd-session: user@pts/0"
EOF

    chmod +x "${STUB_BIN}"/*

    # ---- stub: metadata-utils.sh -------------------------------------------
    cat > "${TMP}/metadata-utils.sh" <<'EOF'
#!/bin/bash
function get_metadata_value() {
    if [[ "$1" == "idle-cpu-container-name" && -n "${STUB_CONTAINER_NAME_METADATA:-}" ]]; then
        echo "${STUB_CONTAINER_NAME_METADATA}"
    else
        echo "$2"
    fi
}
function get_guest_attribute() { echo "$2"; }
function set_metadata() { echo "$1 $2" >> "${STUB_METADATA_LOG}"; }
EOF

    export STUB_METADATA_LOG="${METADATA_LOG}"
    export STUB_CLOCK_QUEUE="${CLOCK_QUEUE}"
    export METADATA_UTILS="${TMP}/metadata-utils.sh"
    export CGROUP_ROOT="${CGROUP}"
    export PROC_ROOT="${PROC}"
    export STATE_DIR="${STATE}"
    export PATH="${STUB_BIN}:${PATH}"

    # Timestamps in nanoseconds: a 60 second gap between probe runs.
    BEFORE_NSEC=1000000000000
    NOW_NSEC=1060000000000
    # Over 60s, 1% of one core is 600000 microseconds of CPU time.
    USEC_PER_PERCENT=600000
    BASE_USEC=10000000
    CONTAINER_ID="abc123def456"
}

# Creates the fake /proc and cgroup v2 entries for a running container.
# usage: given_cgroup_v2 <pid> <container_id> <usage_usec>
given_cgroup_v2() {
    local pid="$1" id="$2" usage="$3"
    mkdir -p "${PROC}/${pid}"
    echo "0::/system.slice/docker-${id}.scope" > "${PROC}/${pid}/cgroup"
    CPU_STAT_FILE="${CGROUP}/system.slice/docker-${id}.scope/cpu.stat"
    mkdir -p "$(dirname "${CPU_STAT_FILE}")"
    printf 'usage_usec %s\nuser_usec 1\nsystem_usec 1\n' "${usage}" > "${CPU_STAT_FILE}"
    export STUB_TARGET_INSPECT="${id} ${pid}"
}

# usage: given_cgroup_v1 <pid> <container_id> <usage_usec>
given_cgroup_v1() {
    local pid="$1" id="$2" usage="$3"
    mkdir -p "${PROC}/${pid}"
    echo "4:cpu,cpuacct:/docker/${id}" > "${PROC}/${pid}/cgroup"
    local file="${CGROUP}/cpuacct/docker/${id}/cpuacct.usage"
    mkdir -p "$(dirname "${file}")"
    # cgroup v1 counts nanoseconds.
    echo "$(( usage * 1000 ))" > "${file}"
    export STUB_TARGET_INSPECT="${id} ${pid}"
}

# Seeds the previous probe's sample so the script diffs against it.
# usage: given_previous_sample <container_id> <usage_usec>
given_previous_sample() {
    echo "$1 $2 ${BEFORE_NSEC}" > "${STATE}/app-cpu-sample"
    echo "${NOW_NSEC}" > "${CLOCK_QUEUE}"
}

assert_metadata() {
    grep -q "^$1 " "${METADATA_LOG}"
}

# Negative assertions must be wrapped in a function: in a bats test body a bare
# `!` is exempt from errexit unless it is the very last command, so `! foo`
# would silently pass mid-test.
refute_metadata() {
    ! grep -q "^$1 " "${METADATA_LOG}"
}

###############################################################################

@test "container CPU below threshold does not count as activity" {
    export STUB_TARGET_CONTAINER="application-server"
    # 2% of one core.
    given_cgroup_v2 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 2 * USEC_PER_PERCENT ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"CPU usage is 2.00% of one core"* ]]
    refute_metadata 'last-active/cpu'
}

@test "container CPU above threshold counts as activity" {
    export STUB_TARGET_CONTAINER="application-server"
    # 100% of one core.
    given_cgroup_v2 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 100 * USEC_PER_PERCENT ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"CPU usage is 100.00% of one core"* ]]
    assert_metadata 'last-active/cpu'
}

@test "CPU exactly at the threshold counts as activity" {
    export STUB_TARGET_CONTAINER="application-server"
    # Exactly 5.00%, the default threshold. Idle requires strictly less.
    given_cgroup_v2 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 5 * USEC_PER_PERCENT ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"CPU usage is 5.00% of one core"* ]]
    assert_metadata 'last-active/cpu'
}

@test "CPU just below the threshold is idle" {
    export STUB_TARGET_CONTAINER="application-server"
    given_cgroup_v2 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 4 * USEC_PER_PERCENT + 100 ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    refute_metadata 'last-active/cpu'
}

@test "usage above one core is reported and counts as activity" {
    export STUB_TARGET_CONTAINER="application-server"
    # 250% of one core: a multi-vCPU workload. Not normalized by core count.
    given_cgroup_v2 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 250 * USEC_PER_PERCENT ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [[ "$output" == *"CPU usage is 250.00% of one core"* ]]
    assert_metadata 'last-active/cpu'
}

@test "explicit container CPU threshold argument is honoured" {
    export STUB_TARGET_CONTAINER="application-server"
    # 20% of one core: active at the default 5%, idle at a 50% threshold.
    given_cgroup_v2 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 20 * USEC_PER_PERCENT ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}" 0.1 50
    [ "$status" -eq 0 ]
    refute_metadata 'last-active/cpu'
}

@test "cgroup v1 cpuacct accounting is supported" {
    export STUB_TARGET_CONTAINER="application-server"
    given_cgroup_v1 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 30 * USEC_PER_PERCENT ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"CPU usage is 30.00% of one core"* ]]
    assert_metadata 'last-active/cpu'
}

@test "the measured container can be overridden by instance metadata" {
    # application-server exists but is not the workload container; the workload
    # runs in "jupyterlab", which is what metadata points at.
    export STUB_TARGET_CONTAINER="jupyterlab"
    export STUB_CONTAINER_NAME_METADATA="jupyterlab"
    given_cgroup_v2 777 "${CONTAINER_ID}" "$(( BASE_USEC + 80 * USEC_PER_PERCENT ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"Container jupyterlab CPU usage is 80.00%"* ]]
    assert_metadata 'last-active/cpu'
}

@test "without the override the default container name is measured" {
    export STUB_TARGET_CONTAINER="application-server"
    given_cgroup_v2 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 80 * USEC_PER_PERCENT ))"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [[ "$output" == *"Container application-server CPU usage is"* ]]
}

@test "missing container falls back to whole-VM load average" {
    # No container at all: docker reports no such object.
    export STUB_TARGET_CONTAINER="nothing-here"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"falling back to whole-VM load average"* ]]
    # The fixture load average (0.02) is under the 0.1 fallback threshold.
    refute_metadata 'last-active/cpu'
}

@test "fallback load average above the threshold counts as activity" {
    export STUB_TARGET_CONTAINER="nothing-here"
    echo "1.50 1.40 1.30 1/234 5678" > "${PROC}/loadavg"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"falling back to whole-VM load average"* ]]
    assert_metadata 'last-active/cpu'
}

@test "the load-average argument still controls the fallback threshold" {
    export STUB_TARGET_CONTAINER="nothing-here"
    echo "0.50 0.50 0.50 1/234 5678" > "${PROC}/loadavg"

    # Active at the default 0.1, idle at a 2.0 load threshold.
    run bash "${SCRIPT}" 2.0
    [ "$status" -eq 0 ]
    refute_metadata 'last-active/cpu'
}

@test "stopped container falls back to whole-VM load average" {
    export STUB_TARGET_CONTAINER="application-server"
    # A stopped container reports pid 0.
    export STUB_TARGET_INSPECT="${CONTAINER_ID} 0"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"falling back to whole-VM load average"* ]]
}

@test "missing cgroup accounting falls back to whole-VM load average" {
    export STUB_TARGET_CONTAINER="application-server"
    # A live pid whose cgroup file does not exist.
    export STUB_TARGET_INSPECT="${CONTAINER_ID} 9999"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"falling back to whole-VM load average"* ]]
}

@test "no previous sample takes a short in-place sample" {
    export STUB_TARGET_CONTAINER="application-server"
    given_cgroup_v2 4242 "${CONTAINER_ID}" "${BASE_USEC}"
    # No state file. The clock supplies both ends of the in-place sample: a
    # 3 second window, during which the counter advances by 3s of CPU time.
    printf '%s\n%s\n' "${BEFORE_NSEC}" "$(( BEFORE_NSEC + 3000000000 ))" > "${CLOCK_QUEUE}"
    export STUB_SLEEP_HOOK="printf 'usage_usec %s\n' $(( BASE_USEC + 3000000 )) > '${CPU_STAT_FILE}'"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"No usable previous CPU sample"* ]]
    [[ "$output" == *"CPU usage is 100.00% of one core"* ]]
    assert_metadata 'last-active/cpu'
}

@test "a restarted container ignores the stale sample from the old container" {
    export STUB_TARGET_CONTAINER="application-server"
    given_cgroup_v2 4242 "new-container-id" "${BASE_USEC}"
    # State recorded against a different container id.
    echo "old-container-id 999999999 ${BEFORE_NSEC}" > "${STATE}/app-cpu-sample"
    printf '%s\n%s\n' "${BEFORE_NSEC}" "$(( BEFORE_NSEC + 3000000000 ))" > "${CLOCK_QUEUE}"
    export STUB_SLEEP_HOOK="printf 'usage_usec %s\n' ${BASE_USEC} > '${CPU_STAT_FILE}'"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"No usable previous CPU sample"* ]]
    # An idle container, and no crash from the negative counter difference.
    refute_metadata 'last-active/cpu'
}

@test "the current sample is persisted for the next probe run" {
    export STUB_TARGET_CONTAINER="application-server"
    local usage=$(( BASE_USEC + 2 * USEC_PER_PERCENT ))
    given_cgroup_v2 4242 "${CONTAINER_ID}" "${usage}"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [ "$(cat "${STATE}/app-cpu-sample")" = "${CONTAINER_ID} ${usage} ${NOW_NSEC}" ]
}

@test "a sub-second gap between probes is not trusted as a sample" {
    export STUB_TARGET_CONTAINER="application-server"
    given_cgroup_v2 4242 "${CONTAINER_ID}" "$(( BASE_USEC + 100 ))"
    # Previous sample only 0.5s old: too short to be a meaningful average.
    echo "${CONTAINER_ID} ${BASE_USEC} ${BEFORE_NSEC}" > "${STATE}/app-cpu-sample"
    printf '%s\n%s\n' "$(( BEFORE_NSEC + 500000000 ))" "$(( BEFORE_NSEC + 3500000000 ))" > "${CLOCK_QUEUE}"
    export STUB_SLEEP_HOOK=":"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    [[ "$output" == *"No usable previous CPU sample"* ]]
}

@test "ssh activity is still recorded independently of the CPU signal" {
    export STUB_TARGET_CONTAINER="application-server"
    export STUB_SSH_ACTIVE="true"
    # An idle container, so only the ssh signal should fire.
    given_cgroup_v2 4242 "${CONTAINER_ID}" "${BASE_USEC}"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    refute_metadata 'last-active/cpu'
    assert_metadata 'last-active/ssh'
}

@test "proxy activity is still recorded independently of the CPU signal" {
    export STUB_TARGET_CONTAINER="application-server"
    given_cgroup_v2 4242 "${CONTAINER_ID}" "${BASE_USEC}"
    given_previous_sample "${CONTAINER_ID}" "${BASE_USEC}"

    run bash "${SCRIPT}"
    [ "$status" -eq 0 ]
    # The proxy container is not running in this fixture, so no proxy signal,
    # and crucially the CPU change did not disturb the proxy code path.
    refute_metadata 'last-active/proxy'
    refute_metadata 'last-active/cpu'
}
