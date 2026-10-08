#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
readonly SCRIPT_DIR
readonly CGROUP_ROOT="${MEMORY_CGROUP_ROOT:-/sys/fs/cgroup}"
readonly PROC_ROOT="${MEMORY_PROC_ROOT:-/proc}"

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
missing() { printf '%s\n' "$2" >> "$1/missing.txt"; }

host_samples() {
    local directory="$1" key value _unused total available timestamp
    while [[ ! -f "${directory}/stop" ]]; do
        total=0; available=0
        while read -r key value _unused; do
            case "${key}" in
                MemTotal:) total=$((value * 1024)) ;;
                MemAvailable:) available=$((value * 1024)) ;;
            esac
        done < "${PROC_ROOT}/meminfo"
        timestamp=$(date +%s%3N)
        if ((total <= 0 || available <= 0 || available > total)); then
            missing "${directory}" 'invalid host memory'; return 1
        fi
        printf '%s %s %s\n' "${timestamp}" "$((total - available))" "${total}" >> "${directory}/host.tsv"
        sleep 0.1
    done
}

gpu_samples() {
    local directory="$1" sample
    while [[ ! -f "${directory}/stop" ]]; do
        if ! sample=$(timeout 5 nvidia-smi --query-gpu=uuid,name,memory.used,memory.total --format=csv,noheader,nounits); then
            missing "${directory}" 'GPU memory query failed'; return 1
        fi
        printf '%s\n' "${sample}" | jq -Rc 'split(",") | map(gsub("^ +| +$"; "")) |
            {uuid:.[0],name:.[1],used_bytes:(.[2]|tonumber)*1048576,total_bytes:(.[3]|tonumber)*1048576}' >> "${directory}/gpu.jsonl"
        sleep 1
    done
}

capture_group() {
    local directory="$1" path="$2" id="$3" role="$4" started="$5" finished="$6" docker_oom="$7"
    local key file peak limit swap events oom killed current previous unlimited=false
    key=$(printf '%s' "${path}:${id}:${started}" | sha256sum | cut -d ' ' -f 1)
    file="${directory}/cgroups/${key}.json"
    if [[ ! -r "${CGROUP_ROOT}${path}/memory.peak" ]]; then
        if [[ -f "${file}" ]]; then
            jq '.final_capture = false' "${file}" > "${file}.tmp"; mv "${file}.tmp" "${file}"
        fi
        missing "${directory}" "missing cgroup peak: ${path}"
        return
    fi
    peak=$(cat "${CGROUP_ROOT}${path}/memory.peak")
    current=$(cat "${CGROUP_ROOT}${path}/memory.current")
    limit=$(cat "${CGROUP_ROOT}${path}/memory.max")
    events=$(cat "${CGROUP_ROOT}${path}/memory.events")
    oom=$(awk '$1 == "oom" {print $2}' <<< "${events}")
    killed=$(awk '$1 == "oom_kill" {print $2}' <<< "${events}")
    if [[ -r "${CGROUP_ROOT}${path}/memory.swap.peak" ]]; then
        swap=$(cat "${CGROUP_ROOT}${path}/memory.swap.peak")
    else
        missing "${directory}" "missing swap peak: ${path}"; swap=null
    fi
    if [[ "${limit}" == max ]]; then limit=null; unlimited=true; fi
    if [[ "${limit}" != null && ! "${limit}" =~ ^[0-9]+$ ]]; then missing "${directory}" "invalid cgroup limit: ${path}"; return; fi
    if [[ ! "${peak}" =~ ^[0-9]+$ || ! "${current}" =~ ^[0-9]+$ || ! "${oom}" =~ ^[0-9]+$ || ! "${killed}" =~ ^[0-9]+$ ]]; then
        missing "${directory}" "invalid cgroup counters: ${path}"; return
    fi
    previous='{}'
    [[ ! -f "${file}" ]] || previous=$(cat "${file}")
    jq -nc --arg path "${path}" --arg id "${id}" --arg role "${role}" --arg started "${started}" --arg finished "${finished}" \
        --argjson peak "${peak}" --argjson current "${current}" --argjson limit "${limit}" --argjson swap "${swap}" \
        --argjson oom "${oom}" --argjson killed "${killed}" --argjson docker_oom "${docker_oom}" --argjson previous "${previous}" --argjson unlimited "${unlimited}" '
        {path:$path,container_id:$id,role:$role,started_at:$started,finished_at:$finished,
         peak_bytes:([$peak,($previous.peak_bytes // 0)]|max),current_bytes:$current,limit_bytes:$limit,limit_unlimited:$unlimited,
         swap_peak_bytes:$swap,oom_delta:$oom,oom_kill_delta:([$killed,if $docker_oom then 1 else 0 end]|max),
         final_capture:true}' > "${file}.tmp"
    mv "${file}.tmp" "${file}"
}

measured_container() {
    case "$1:$2" in
        application-server:*|browser:*|playground:*|proxy-agent:*|fluent-bit:*|dependency-*:*) return 0 ;;
        app-[0-9]*:app|*:wondershaper|*:db) return 0 ;;
        *) return 1 ;;
    esac
}

verify_lifecycles() {
    local directory="$1" metadata="$2" file id started path
    while read -r id; do
        [[ -n "${id}" ]] || continue
        if ! jq -e --arg id "${id}" 'any(.[]; .Id==$id and .State.Running==true)' <<< "${metadata}" >/dev/null; then
            missing "${directory}" "observed container disappeared or stopped: ${id}"
        fi
    done < <(sort -u "${directory}/container-ids.txt")
    for file in "${directory}"/cgroups/*.json; do
        [[ -f "${file}" ]] || continue
        id=$(jq -r '.container_id' "${file}")
        started=$(jq -r '.started_at' "${file}")
        path=$(jq -r '.path' "${file}")
        if [[ ! -r "${CGROUP_ROOT}${path}/memory.peak" ]] ||
           { [[ -n "${id}" ]] && ! jq -e --arg id "${id}" --arg started "${started}" \
             'any(.[]; .Id==$id and .State.StartedAt==$started and .State.Running==true)' <<< "${metadata}" >/dev/null; }; then
            jq '.final_capture=false' "${file}" > "${file}.tmp"; mv "${file}.tmp" "${file}"
            missing "${directory}" "lost observed cgroup lifecycle: ${path}:${id}:${started}"
        fi
    done
}

container_samples() {
    local directory="$1" ids metadata row id name pid path started finished oom role service seen=0
    local cursor until events event_id
    cursor=$(jq -r '.started_at' "${directory}/context.json")
    while :; do
        metadata='[]'
        : > "${directory}/current-containers.txt"
        for path in /system.slice /user.slice /init.scope; do
            [[ ! -d "${CGROUP_ROOT}${path}" ]] || capture_group "${directory}" "${path}" '' host-service '' '' false
        done
        if ids=$(timeout 5 docker ps -aq --no-trunc) && [[ -n "${ids}" ]]; then
            # Docker IDs are validated before word splitting.
            if [[ "${ids//[$'\n'0-9a-f]/}" != '' ]]; then
                missing "${directory}" 'invalid Docker IDs'; return 1
            fi
            # shellcheck disable=SC2086
            if ! metadata=$(timeout 5 docker inspect ${ids}); then
                missing "${directory}" 'Docker inspect failed'; return 1
            fi
            while IFS= read -r row; do
                id=$(jq -r '.Id' <<< "${row}")
                name=$(jq -r '.Name | ltrimstr("/")' <<< "${row}")
                service=$(jq -r '.Config.Labels["com.docker.compose.service"] // ""' <<< "${row}")
                measured_container "${name}" "${service}" || continue
                if [[ $(jq -r '.State.Running' <<< "${row}") == true ]]; then
                    printf '%s\n' "${name}" >> "${directory}/current-containers.txt"
                fi
                pid=$(jq -r '.State.Pid' <<< "${row}")
                started=$(jq -r '.State.StartedAt' <<< "${row}")
                finished=$(jq -r '.State.FinishedAt' <<< "${row}")
                oom=$(jq -r '.State.OOMKilled' <<< "${row}")
                printf '%s\n' "${name}" >> "${directory}/containers.txt"
                printf '%s\n' "${id}" >> "${directory}/container-ids.txt"
                if [[ ! -r "${PROC_ROOT}/${pid}/cgroup" ]]; then
                    missing "${directory}" "container exited before final capture: ${name}:${id}"
                    continue
                fi
                path=$(awk -F: '$1 == "0" {print $3}' "${PROC_ROOT}/${pid}/cgroup")
                [[ "${path}" == /* && "${path}" != / && "${path}" != *'..'* ]] || {
                    missing "${directory}" "invalid cgroup path: ${name}"; continue;
                }
                role=app
                case "${name}" in proxy-agent|fluent-bit) role=host-container ;; esac
                capture_group "${directory}" "${path}" "${id}" "${role}" "${started}" "${finished}" "${oom}"
            done < <(jq -c '.[]' <<< "${metadata}")
            until=$(date +%s.%N)
            if events=$(timeout 5 docker events --since "${cursor}" --until "${until}" --filter type=container --filter event=start --format '{{json .}}'); then
                while IFS= read -r row; do
                    [[ -n "${row}" ]] || continue
                    name=$(jq -r '.Actor.Attributes.name // ""' <<< "${row}")
                    service=$(jq -r '.Actor.Attributes["com.docker.compose.service"] // ""' <<< "${row}")
                    measured_container "${name}" "${service}" || continue
                    event_id=$(jq -r '.Actor.ID' <<< "${row}")
                    printf '%s\n' "${event_id}" >> "${directory}/event-container-ids.txt"
                done <<< "${events}"
                cursor="${until}"
            else
                missing "${directory}" 'container lifecycle events unavailable'
            fi
            seen=1
        elif ((seen)); then
            missing "${directory}" 'Docker collection became unavailable'
        fi
        verify_lifecycles "${directory}" "${metadata}"
        [[ ! -f "${directory}/stop" ]] || break
        sleep 1
    done
    while read -r event_id; do
        grep -qx "${event_id}" "${directory}/container-ids.txt" || missing "${directory}" "container lifecycle missed between samples: ${event_id}"
    done < <(sort -u "${directory}/event-container-ids.txt")
    [[ "${seen}" == 1 ]] || missing "${directory}" 'no containers observed'
}

collect() {
    local directory="$1" host_pid gpu_pid='' status=0
    trap 'printf "1\n" > "${directory}/collector.exit"' EXIT
    host_samples "${directory}" & host_pid=$!
    if [[ $(jq -r '.profile' "${directory}/context.json") != cpu ]]; then
        gpu_samples "${directory}" & gpu_pid=$!
    fi
    container_samples "${directory}" || status=1
    touch "${directory}/stop"
    wait "${host_pid}" || status=1
    if [[ -n "${gpu_pid}" ]]; then wait "${gpu_pid}" || status=1; fi
    printf '%s\n' "${status}" > "${directory}/collector.exit"
    trap - EXIT
}

start() {
    local context="$1" directory="$2" ram boot
    jq -e '.schema_version == 1 and (.run_id|type=="string" and length>0) and
      (.app|type=="string") and (.cloud=="gcp" or .cloud=="aws") and
      (.profile=="cpu" or .profile=="t4" or .profile=="a100-80gb") and
      (.sample|type=="number" and .>=1) and (.inputs_hash|type=="string" and length>0) and
      (.source_sha|test("^[a-f0-9]{40}$")) and (.machine.type|type=="string" and length>0) and
      (.machine.gpu_count|type=="number")' "${context}" >/dev/null
    jq -e --arg app "$(jq -r '.app' "${context}")" '.apps | has($app)' "${SCRIPT_DIR}/profiles.json" >/dev/null
    [[ -r "${CGROUP_ROOT}/cgroup.controllers" && -r "${CGROUP_ROOT}/system.slice/memory.peak" && ! -e "${directory}/context.json" ]]
    mkdir -p "${directory}/cgroups"
    directory=$(cd "${directory}" && pwd)
    ram=$(awk '/^MemTotal:/ {printf "%.0f", $2 * 1024}' "${PROC_ROOT}/meminfo")
    boot=$(cat "${PROC_ROOT}/sys/kernel/random/boot_id")
    jq --arg start "$(now)" --arg boot "${boot}" --argjson ram "${ram}" \
        --arg collector "$(cat "${SCRIPT_DIR}/memory-collect.sh" "${SCRIPT_DIR}/memory-validate.jq" | sha256sum | cut -d ' ' -f 1)" \
        '. + {started_at:$start,cold_boot_id:$boot,collector_sha256:$collector} | .machine.ram_bytes=$ram' \
        "${context}" > "${directory}/context.json"
    touch "${directory}/host.tsv" "${directory}/gpu.jsonl" "${directory}/missing.txt" "${directory}/containers.txt" "${directory}/container-ids.txt" "${directory}/event-container-ids.txt" "${directory}/current-containers.txt"
    nohup bash "${SCRIPT_DIR}/memory-collect.sh" _collect "${directory}" > "${directory}/collector.log" 2>&1 < /dev/null &
    echo $! > "${directory}/collector.pid"
    for _ in {1..50}; do
        [[ ! -s "${directory}/host.tsv" ]] || return 0
        [[ ! -f "${directory}/collector.exit" ]] || return 1
        sleep 0.1
    done
    return 1
}

finish() {
    local directory="$1" workload="$2" status=1
    touch "${directory}/stop"
    for _ in {1..150}; do
        [[ ! -f "${directory}/collector.exit" ]] || break
        sleep 0.1
    done
    [[ ! -f "${directory}/collector.exit" ]] || status=$(cat "${directory}/collector.exit")
    [[ "${status}" == 0 ]] || missing "${directory}" 'collector did not finish successfully'
    [[ -s "${workload}" ]] || { missing "${directory}" 'missing workload report'; printf '{"status":"blocked","reason":"missing workload report"}\n' > "${directory}/missing-workload.json"; workload="${directory}/missing-workload.json"; }
    grep -qx application-server "${directory}/containers.txt" || missing "${directory}" 'expected container missing: application-server'
    jq -s '.' "${directory}"/cgroups/*.json > "${directory}/cgroups.json" 2>/dev/null || printf '[]\n' > "${directory}/cgroups.json"
    jq -Rn '[inputs | split(" ") | map(tonumber)] |
      {peak_bytes:([.[][1]]|max),ram_bytes:([.[][2]]|max),samples:length,sample_interval_ms:100,
       sampling_gaps:([range(1;length) as $i | select(.[ $i ][0] - .[$i-1][0] > 1000) | .[$i][0]- .[$i-1][0]])}' \
        < "${directory}/host.tsv" > "${directory}/host.json"
    jq -s '{samples:length,peak_bytes:([.[].used_bytes]|max),devices:(group_by(.uuid)|map({uuid:.[0].uuid,name:.[0].name,peak_bytes:([.[].used_bytes]|max),total_bytes:.[0].total_bytes}))}' \
        "${directory}/gpu.jsonl" > "${directory}/gpu.json"
    jq -Rn '[inputs] | unique' < "${directory}/missing.txt" > "${directory}/missing.json"
    jq -Rn '[inputs] | unique' < "${directory}/current-containers.txt" > "${directory}/containers.json"
    jq -n --slurpfile context "${directory}/context.json" --slurpfile workload "${workload}" \
      --slurpfile host "${directory}/host.json" --slurpfile gpu "${directory}/gpu.json" \
      --slurpfile groups "${directory}/cgroups.json" --slurpfile missing "${directory}/missing.json" \
      --slurpfile containers "${directory}/containers.json" --arg finished "$(now)" --argjson exit_status "${status}" '
      $context[0] as $c | $host[0] as $h | $groups[0] as $g |
      {schema_version:1,run_id:$c.run_id,app:$c.app,cloud:$c.cloud,profile:$c.profile,sample:$c.sample,
       inputs_hash:$c.inputs_hash,source_sha:$c.source_sha,started_at:$c.started_at,finished_at:$finished,
       provenance:{machine:$c.machine,cold_boot_id:$c.cold_boot_id,collector_sha256:$c.collector_sha256,
                   workload_sha256:($workload[0].workload_sha256 // "")},
       workload:$workload[0],host:$h,cgroups:$g,gpu:($gpu[0]+{allocated_type:$c.machine.gpu_type,allocated_count:$c.machine.gpu_count}),
       coverage:{expected_containers:($workload[0].expected_containers // ["application-server"]),discovered_containers:$containers[0],
                 missing_metrics:$missing[0],sampling_gaps:$h.sampling_gaps,collector_exit_status:$exit_status},
       status:(if $exit_status==0 and ($missing[0]|length)==0 and ($g|length)>0 and ($h.samples>0) and
                  ($h.sampling_gaps|length)==0 and $workload[0].status=="pass" and
                  all($g[]; .final_capture and .oom_delta==0 and .oom_kill_delta==0) then "pass" else "fail" end),
       reason:"See workload and coverage for failures; headroom and baseline decisions are in memory-compare.py"}' > "${directory}/memory.json"
    jq -f "${SCRIPT_DIR}/memory-validate.jq" "${directory}/memory.json" > "${directory}/memory.validated.json"
    mv "${directory}/memory.validated.json" "${directory}/memory.json"
    jq -e '.status=="pass"' "${directory}/memory.json" >/dev/null
}

case "${1:-}" in
    start) [[ $# == 3 ]]; start "$2" "$3" ;;
    finish) [[ $# == 3 ]]; finish "$2" "$3" ;;
    _collect) [[ $# == 2 ]]; collect "$2" ;;
    *) echo "Usage: $0 start CONTEXT_JSON OUTPUT_DIR | finish OUTPUT_DIR WORKLOAD_JSON" >&2; exit 2 ;;
esac
