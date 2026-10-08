#!/usr/bin/env python3
"""Compare measured app memory with the promoted cold-run baseline."""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

MIB = 1024 * 1024


def identity(sample):
    provenance = sample["provenance"]
    machine = provenance["machine"]
    return (
        sample["app"], sample["cloud"], sample["profile"],
        machine["type"], machine["gpu_type"], machine["gpu_count"],
        provenance["workload_sha256"], provenance["collector_sha256"],
    )


def problems(sample):
    issues = []
    if sample.get("schema_version") != 1 or sample.get("status") != "pass":
        issues.append("sample did not pass")
    coverage = sample.get("coverage", {})
    if coverage.get("collector_exit_status") != 0 or coverage.get("missing_metrics"):
        issues.append("incomplete collection")
    if coverage.get("sampling_gaps"):
        issues.append("host sampling gaps")
    expected = coverage.get("expected_containers", [])
    discovered = coverage.get("discovered_containers", [])
    if not expected or not set(expected).issubset(discovered):
        issues.append("missing expected containers")
    if sample.get("workload", {}).get("execution_mode") != "cloud":
        issues.append("hosted fixtures are not cloud evidence")
    if not sample.get("workload", {}).get("status") == "pass":
        issues.append("workload did not pass")
    host = sample.get("host", {})
    ram = sample.get("provenance", {}).get("machine", {}).get("ram_bytes", 0)
    if not isinstance(host.get("peak_bytes"), int) or host["peak_bytes"] <= 0 or ram <= 0:
        issues.append("missing host peak or RAM")
    elif host["peak_bytes"] * 5 > ram * 4:
        issues.append("host has less than 25% headroom")
    cgroups = sample.get("cgroups", [])
    if not cgroups:
        issues.append("missing cgroups")
    for group in cgroups:
        if not group.get("final_capture"):
            issues.append("missing final cgroup capture")
        if not all(isinstance(group.get(field), int) for field in ("oom_delta", "oom_kill_delta")):
            issues.append("missing OOM counters")
        if group.get("oom_delta") or group.get("oom_kill_delta"):
            issues.append("cgroup OOM")
        if "limit_bytes" not in group or (group["limit_bytes"] is None and not group.get("limit_unlimited")):
            issues.append("missing cgroup limit")
        if not isinstance(group.get("peak_bytes"), int) or group["peak_bytes"] < 0:
            issues.append("missing cgroup peak")
        elif ram > 0 and group["peak_bytes"] * 5 > min(group.get("limit_bytes") or ram, ram) * 4:
            issues.append("container has less than 25% headroom")
        if not isinstance(group.get("swap_peak_bytes"), int):
            issues.append("missing swap peak")
        elif group["swap_peak_bytes"]:
            issues.append("swap was used")
    if sample.get("profile") != "cpu":
        gpu = sample.get("gpu", {})
        if not gpu.get("samples") or not isinstance(gpu.get("peak_bytes"), int) or not gpu.get("devices"):
            issues.append("missing GPU memory samples")
        for device in gpu.get("devices", []):
            if not isinstance(device.get("peak_bytes"), int) or not isinstance(device.get("total_bytes"), int) or device["total_bytes"] <= 0:
                issues.append("invalid GPU memory counters")
            elif device["peak_bytes"] * 5 > device["total_bytes"] * 4:
                issues.append("GPU has less than 25% headroom")
    return sorted(set(issues))


def metrics(samples):
    values = defaultdict(list)
    for sample in samples:
        values["host"].append(sample["host"]["peak_bytes"])
        # Roles combine sibling containers without calling their summed peaks simultaneous use.
        roles = defaultdict(int)
        for group in sample["cgroups"]:
            roles[group["role"]] += group["peak_bytes"]
        for role, peak in roles.items():
            values["cgroup_bound:" + role].append(peak)
        if sample["profile"] != "cpu":
            values["gpu"].append(sample["gpu"]["peak_bytes"])
    return values


def compare(candidates, baselines, unchanged=False):
    grouped = defaultdict(list)
    baseline_groups = defaultdict(list)
    for sample in candidates:
        grouped[identity(sample)].append(sample)
    for sample in baselines:
        baseline_groups[identity(sample)].append(sample)
    decisions = []
    for key, samples in grouped.items():
        reasons = sorted({issue for sample in samples for issue in problems(sample)})
        status = "fail" if reasons else "pass"
        boots = [sample["provenance"].get("cold_boot_id") for sample in samples]
        required = 1 if unchanged else 3
        if len(samples) < required or None in boots or "" in boots or len(set(boots)) != len(boots):
            reasons.append("need distinct cold boots: smoke plus two repeats for changed inputs")
            status = "blocked" if status == "pass" else status
        if len({sample["inputs_hash"] for sample in samples}) != 1:
            reasons.append("candidate samples have different effective inputs")
            status = "blocked" if status == "pass" else status
        baseline = baseline_groups.get(key, [])
        baseline_valid = len(baseline) >= 3 and not any(problems(sample) for sample in baseline)
        baseline_boots = [sample["provenance"].get("cold_boot_id") for sample in baseline]
        baseline_valid = baseline_valid and all(baseline_boots) and len(set(baseline_boots)) == len(baseline_boots)
        baseline_valid = baseline_valid and len({sample["inputs_hash"] for sample in baseline}) == 1
        if unchanged and (not baseline_valid or any(sample["inputs_hash"] != samples[0]["inputs_hash"] for sample in baseline)):
            reasons.append("unchanged smoke requires a complete matching promoted baseline")
            status = "blocked" if status == "pass" else status
        deltas = []
        if baselines and not baseline_valid:
            reasons.append("promoted baseline does not match this profile or is incomplete")
            status = "blocked" if status == "pass" else status
        if status == "pass" and baseline_valid:
            old = metrics(baseline)
            new = metrics(samples)
            if old.keys() != new.keys():
                status = "blocked"
                reasons.append("measured cgroup roles changed")
            else:
                for name, values in new.items():
                    median = statistics.median(old[name])
                    mad = statistics.median(abs(value - median) for value in old[name])
                    tolerance = max(median * 0.10, 256 * MIB, 3 * mad)
                    growth = max(values) - max(old[name])
                    if growth > tolerance:
                        status = "fail"
                        reasons.append("memory regression: " + name)
                        deltas.append({"metric": name, "growth_bytes": growth, "tolerance_bytes": int(tolerance)})
        decisions.append({
            "app": key[0], "cloud": key[1], "profile": key[2], "machine": samples[0]["provenance"]["machine"],
            "status": status, "reasons": reasons, "samples": len(samples), "required_samples": required,
            "needs_baseline_confirmation": bool(deltas), "regressions": deltas,
            "peak_bytes": max(sample["host"].get("peak_bytes", 0) or 0 for sample in samples),
            "baseline_started_at": [sample["started_at"] for sample in baseline],
        })
    recommendations = {}
    for decision in decisions:
        if decision["status"] != "pass":
            continue
        key = "/".join(decision[field] for field in ("app", "cloud", "profile"))
        previous = recommendations.get(key)
        if previous is None or decision["machine"]["ram_bytes"] < previous["ram_bytes"]:
            recommendations[key] = decision["machine"]
    return {
        "schema_version": 1,
        "status": "pass" if decisions and all(row["status"] == "pass" for row in decisions) else "fail",
        "decisions": decisions,
        "smallest_tested_passing_machine": recommendations,
        "headroom_percent": 25,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", nargs="+", required=True, type=Path)
    parser.add_argument("--baseline", nargs="*", default=[], type=Path)
    parser.add_argument("--unchanged", action="store_true")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = compare([json.loads(path.read_text()) for path in args.candidate],
                         [json.loads(path.read_text()) for path in args.baseline], args.unchanged)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {"schema_version": 1, "status": "fail", "reason": "invalid measurement: " + str(error)}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
