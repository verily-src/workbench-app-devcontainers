import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("memory_compare", ROOT / "tests/common/memory-compare.py")
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
MIB = 1024 * 1024


def sample(index, peak=400 * MIB):
    return {
        "schema_version": 1, "run_id": "candidate", "app": "example", "cloud": "gcp", "profile": "cpu",
        "sample": index, "status": "pass", "started_at": "2026-10-08T18:00:00Z", "inputs_hash": "candidate",
        "provenance": {"cold_boot_id": str(index), "workload_sha256": "fixture-v1", "collector_sha256": "collector-v1",
                       "machine": {"type": "test-machine", "ram_bytes": 8 * 1024 * MIB, "gpu_type": "", "gpu_count": 0}},
        "workload": {"status": "pass", "execution_mode": "cloud"}, "host": {"peak_bytes": peak, "sample_interval_ms": 100}, "gpu": {},
        "cgroups": [{"path": "/app", "container_id": "app", "role": "app", "peak_bytes": peak,
                     "limit_bytes": 7 * 1024 * MIB, "swap_peak_bytes": 0, "oom_delta": 0,
                     "oom_kill_delta": 0, "final_capture": True}],
        "coverage": {"collector_exit_status": 0, "missing_metrics": [], "sampling_gaps": [],
                     "expected_containers": ["application-server"], "discovered_containers": ["application-server"]},
    }


class MemoryGateTest(unittest.TestCase):
    def test_regression_requests_baseline_confirmation(self):
        baseline = [sample(i) for i in range(3)]
        candidate = [sample(i, 900 * MIB) for i in range(3)]
        report = GATE.compare(candidate, baseline)
        self.assertEqual(report["status"], "fail")
        self.assertTrue(report["decisions"][0]["needs_baseline_confirmation"])
        self.assertFalse(report["smallest_tested_passing_machine"])

    def test_changed_smoke_regression_requests_baseline_confirmation(self):
        candidate = sample(4, 900 * MIB)
        candidate["inputs_hash"] = "changed"
        report = GATE.compare([candidate], [sample(i) for i in range(3)], smoke=True)
        decision = report["decisions"][0]
        self.assertEqual(report["status"], "fail")
        self.assertEqual(decision["baseline_status"], "valid")
        self.assertEqual(decision["regression_status"], "fail")
        self.assertTrue(decision["needs_baseline_confirmation"])
        self.assertEqual({row["metric"] for row in decision["regressions"]}, {"host", "cgroup_bound:app"})
        self.assertFalse(report["smallest_tested_passing_machine"])

    def test_changed_smoke_within_threshold_passes_without_recommendation(self):
        candidate = sample(4, 500 * MIB)
        candidate["inputs_hash"] = "changed"
        baseline = [sample(i) for i in range(3)]
        report = GATE.compare([candidate], baseline, smoke=True)
        decision = report["decisions"][0]
        self.assertEqual(report["status"], "pass")
        self.assertEqual(decision["required_samples"], 1)
        self.assertEqual(decision["baseline_status"], "valid")
        self.assertEqual(decision["regression_status"], "pass")
        self.assertEqual(decision["baseline_started_at"], [row["started_at"] for row in baseline])
        self.assertFalse(report["smallest_tested_passing_machine"])

    def test_smoke_without_baseline_passes_measurement_with_unverified_comparison(self):
        report = GATE.compare([sample(4)], [], smoke=True)
        decision = report["decisions"][0]
        self.assertEqual(report["status"], "pass")
        self.assertEqual(decision["baseline_status"], "unavailable")
        self.assertEqual(decision["regression_status"], "unverified")
        self.assertFalse(decision["baseline_started_at"])
        self.assertFalse(report["smallest_tested_passing_machine"])

    def test_cli_smoke_flag_allows_one_sample_without_recommending_a_size(self):
        with tempfile.TemporaryDirectory(prefix="memory-compare-") as tmp:
            candidate = Path(tmp) / "candidate.json"
            candidate.write_text(json.dumps(sample(4)))
            output = Path(tmp) / "decision.json"
            command = [sys.executable, str(ROOT / "tests/common/memory-compare.py"),
                       "--candidate", str(candidate), "--output", str(output)]
            for flags, expected_status in (([], "fail"), (["--smoke"], "pass")):
                result = subprocess.run(command + flags, text=True, capture_output=True)
                self.assertEqual(result.returncode, int(expected_status == "fail"), result.stderr)
                report = json.loads(output.read_text())
                self.assertEqual(report["status"], expected_status)
                self.assertEqual(report["decisions"][0]["baseline_status"], "unavailable")
                self.assertEqual(report["decisions"][0]["regression_status"], "unverified")
                self.assertFalse(report["smallest_tested_passing_machine"])

    def test_smoke_without_baseline_still_requires_complete_measurements_and_headroom(self):
        for mutation in (lambda row: row["host"].update(peak_bytes=7 * 1024 * MIB),
                         lambda row: row["workload"].update(status="fail"),
                         lambda row: row["cgroups"][0].update(oom_kill_delta=1),
                         lambda row: row["cgroups"][0].pop("peak_bytes"),
                         lambda row: row["provenance"].update(cold_boot_id="")):
            candidate = sample(4)
            mutation(candidate)
            report = GATE.compare([candidate], [], smoke=True)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["decisions"][0]["regression_status"], "unverified")
            self.assertFalse(report["smallest_tested_passing_machine"])

    def test_smoke_with_incomplete_or_incompatible_baseline_stays_blocked(self):
        for mutation in (lambda rows: rows.pop(),
                         lambda rows: rows[0]["provenance"].update(cold_boot_id=rows[1]["provenance"]["cold_boot_id"]),
                         lambda rows: rows[0]["cgroups"][0].update(oom_kill_delta=1),
                         lambda rows: rows[0].update(inputs_hash="different"),
                         lambda rows: rows[0]["provenance"].update(workload_sha256="different"),
                         lambda rows: rows[0]["provenance"].update(collector_sha256="different"),
                         lambda rows: rows[0]["provenance"]["machine"].update(type="different"),
                         lambda rows: rows[0].update(profile="different"),
                         lambda rows: rows[0].update(app="different"),
                         lambda rows: rows[0].update(cloud="aws")):
            baseline = [sample(i) for i in range(3)]
            mutation(baseline)
            report = GATE.compare([sample(4)], baseline, smoke=True)
            decision = report["decisions"][0]
            self.assertEqual(report["status"], "fail")
            self.assertEqual(decision["status"], "blocked")
            self.assertEqual(decision["baseline_status"], "invalid")
            self.assertEqual(decision["regression_status"], "blocked")

    def test_changed_weekly_measurement_still_requires_three_cold_samples(self):
        baseline = [sample(i) for i in range(3)]
        candidate = [sample(i + 4) for i in range(3)]
        for row in candidate:
            row["inputs_hash"] = "changed"
        for count in (1, 2):
            report = GATE.compare(candidate[:count], baseline)
            self.assertEqual(report["status"], "fail")
            self.assertEqual(report["decisions"][0]["required_samples"], 3)
            self.assertFalse(report["smallest_tested_passing_machine"])
        report = GATE.compare(candidate, baseline)
        self.assertEqual(report["status"], "pass")
        self.assertIn("example/gcp/cpu", report["smallest_tested_passing_machine"])

    def test_child_oom_fails_even_if_parent_survives(self):
        candidate = [sample(i) for i in range(3)]
        candidate[1]["cgroups"][0]["oom_kill_delta"] = 1
        self.assertEqual(GATE.compare(candidate, [sample(i) for i in range(3)])["status"], "fail")

    def test_missing_counters_never_become_zero(self):
        for field in ("peak_bytes", "limit_bytes", "swap_peak_bytes", "oom_delta", "oom_kill_delta", "final_capture"):
            with self.subTest(field=field):
                candidate = [sample(i) for i in range(3)]
                del candidate[0]["cgroups"][0][field]
                self.assertEqual(GATE.compare(candidate, [])["status"], "fail")

    def test_unlimited_is_distinct_from_missing_limit(self):
        candidate = [sample(i) for i in range(3)]
        for row in candidate:
            row["cgroups"][0]["limit_bytes"] = None
        self.assertEqual(GATE.compare(candidate, [])["status"], "fail")
        for row in candidate:
            row["cgroups"][0]["limit_unlimited"] = True
        self.assertEqual(GATE.compare(candidate, [])["status"], "pass")

    def test_missing_sidecar_and_sampling_gap_fail(self):
        for mutation in (lambda row: row["coverage"]["expected_containers"].append("browser"),
                         lambda row: row["coverage"]["sampling_gaps"].append(2000),
                         lambda row: row["coverage"].update(collector_exit_status=137)):
            candidate = [sample(i) for i in range(3)]
            mutation(candidate[0])
            self.assertEqual(GATE.compare(candidate, [])["status"], "fail")

    def test_same_boot_is_not_a_cold_repeat(self):
        self.assertEqual(GATE.compare([sample(1)] * 3, [])["status"], "fail")

    def test_unchanged_smoke_reuses_dated_baseline(self):
        baseline = [sample(i) for i in range(3)]
        report = GATE.compare([sample(4)], baseline, unchanged=True)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["decisions"][0]["baseline_started_at"], [row["started_at"] for row in baseline])
        self.assertIn("example/gcp/cpu", report["smallest_tested_passing_machine"])
        for row in baseline:
            row["inputs_hash"] = "other"
        for smoke in (False, True):
            self.assertEqual(GATE.compare([sample(4)], baseline, unchanged=True, smoke=smoke)["status"], "fail")
        self.assertEqual(GATE.compare([sample(4)], [], unchanged=True)["status"], "fail")

    def test_profiles_and_workloads_cannot_be_interchanged(self):
        baseline = [sample(i) for i in range(3)]
        for mutation in (lambda row: row.update(profile="t4"),
                         lambda row: row["provenance"].update(workload_sha256="new-fixture"),
                         lambda row: row["provenance"]["machine"].update(type="other-machine")):
            candidate = [sample(i) for i in range(3)]
            for row in candidate:
                mutation(row)
            self.assertEqual(GATE.compare(candidate, baseline)["status"], "fail")

    def test_kernel_reserved_ram_difference_does_not_change_machine_identity(self):
        baseline = [sample(i) for i in range(3)]
        candidate = copy.deepcopy(baseline)
        for row in candidate:
            row["provenance"]["machine"]["ram_bytes"] -= 8 * MIB
        self.assertEqual(GATE.compare(candidate, baseline)["status"], "pass")

    def test_headroom_is_measured_on_each_machine(self):
        candidate = [sample(i, 7 * 1024 * MIB) for i in range(3)]
        self.assertEqual(GATE.compare(candidate, [])["status"], "fail")
        candidate = [sample(i) for i in range(3)]
        recommendation = GATE.compare(candidate, [])["smallest_tested_passing_machine"]
        self.assertEqual(recommendation["example/gcp/cpu"]["type"], "test-machine")

    def test_catalog_covers_every_app_directory_once(self):
        profiles = json.loads((ROOT / "tests/common/profiles.json").read_text())["apps"]
        apps = {path.parent.name for path in (ROOT / "src").glob("*/devcontainer-template.json")}
        self.assertEqual(set(profiles), apps)
        self.assertEqual(len(profiles), 24)
        self.assertEqual(set(profiles["playground"]["services"]), {"app", "db", "playground"})
        self.assertIn("browser", profiles["virtual-browser-jupyter"]["services"])


if __name__ == "__main__":
    unittest.main()
