def integer: type == "number" and floor == .;
def positive: integer and . > 0;
. as $s |
[
  if .coverage.collector_exit_status != 0 then "collector did not finish successfully" else empty end,
  if (.coverage.missing_metrics | length) > 0 then "incomplete cgroup collection" else empty end,
  if (.coverage.sampling_gaps | length) > 0 then "host sampling gaps" else empty end,
  if .workload.status != "pass" then "workload did not pass" else empty end,
  if .workload.execution_mode != "cloud" then "hosted fixtures are not cloud evidence" else empty end,
  if (.coverage.expected_containers | length) == 0 or
     ((.coverage.expected_containers - .coverage.discovered_containers) | length) > 0
    then "missing required containers at final capture" else empty end,
  if (.host.peak_bytes | positive | not) or (.host.ram_bytes | positive | not) or (.host.samples | positive | not)
    then "missing host memory" elif .host.peak_bytes * 5 > .host.ram_bytes * 4
    then "host has less than 25% headroom" else empty end,
  if (.cgroups | length) == 0 then "missing cgroups" else empty end,
  (.cgroups[] |
    if .final_capture != true then "missing final cgroup capture: " + .path else empty end,
    if (.peak_bytes | integer | not) or .peak_bytes < 0 then "missing cgroup peak: " + .path else empty end,
    if (.oom_delta | integer | not) or (.oom_kill_delta | integer | not)
      then "missing OOM counters: " + .path elif .oom_delta > 0 or .oom_kill_delta > 0
      then "cgroup OOM: " + .path else empty end,
    if (.swap_peak_bytes | integer | not) then "missing swap peak: " + .path
      elif .swap_peak_bytes > 0 then "swap was used: " + .path else empty end,
    if ((.limit_bytes | positive) or (.limit_bytes == null and .limit_unlimited == true)) | not
      then "missing cgroup limit: " + .path
      elif (.peak_bytes | integer) and ($s.host.ram_bytes | positive) and
        .peak_bytes * 5 > ([.limit_bytes // $s.host.ram_bytes, $s.host.ram_bytes] | min) * 4
      then "cgroup has less than 25% headroom: " + .path else empty end),
  if .profile != "cpu" then
    if (.gpu.samples | positive | not) or (.gpu.peak_bytes | integer | not) or
       (.gpu.devices | length) != .gpu.allocated_count or .gpu.allocated_count < 1
      then "missing GPU memory samples" else empty end,
    (.gpu.devices[] |
      if (.peak_bytes | integer | not) or (.total_bytes | positive | not)
        then "invalid GPU memory counters" elif .peak_bytes * 5 > .total_bytes * 4
        then "GPU has less than 25% headroom" else empty end)
    else empty end
] | unique as $errors |
$s + {status:(if ($errors|length)==0 then "pass" else "fail" end), validation_errors:$errors,
      reason:($errors|join("; "))}
