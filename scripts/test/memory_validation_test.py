import json
import subprocess
import unittest
from pathlib import Path

from memory_compare_test import GATE, MIB, sample

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "tests/common/memory-validate.jq"


def validation_sample():
    row = sample(1)
    row["host"].update(samples=10, ram_bytes=row["provenance"]["machine"]["ram_bytes"])
    return row


class GuestValidationTest(unittest.TestCase):
    def validate(self, row):
        result = subprocess.run(["jq", "-f", str(VALIDATOR)], input=json.dumps(row), text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_guest_sample_requires_headroom_even_without_baseline_comparison(self):
        row = validation_sample()
        self.assertEqual(self.validate(row)["status"], "pass")
        row["host"]["peak_bytes"] = 7 * 1024 * MIB
        self.assertEqual(self.validate(row)["status"], "fail")

    def test_unlimited_container_spike_uses_host_ram_as_headroom_limit(self):
        row = validation_sample()
        row["cgroups"][0].update(peak_bytes=7 * 1024 * MIB, limit_bytes=None, limit_unlimited=True)
        self.assertEqual(self.validate(row)["status"], "fail")
        self.assertIn("container has less than 25% headroom", GATE.problems(row))

    def test_guest_rejects_swap_missing_sidecar_and_missing_counters(self):
        changes = [
            lambda row: row["cgroups"][0].update(swap_peak_bytes=4096),
            lambda row: row["coverage"]["expected_containers"].append("browser"),
            lambda row: row["cgroups"][0].pop("oom_kill_delta"),
            lambda row: row["cgroups"][0].update(final_capture=False),
            lambda row: row["workload"].update(execution_mode="hosted"),
        ]
        for change in changes:
            row = validation_sample()
            change(row)
            self.assertEqual(self.validate(row)["status"], "fail")

    def test_gpu_needs_device_evidence_and_headroom(self):
        row = validation_sample()
        row["profile"] = "t4"
        row["gpu"] = {"allocated_count": 1, "samples": 0, "peak_bytes": None, "devices": []}
        self.assertEqual(self.validate(row)["status"], "fail")
        row["gpu"].update(samples=10, peak_bytes=15 * 1024 * MIB,
                          devices=[{"peak_bytes": 15 * 1024 * MIB, "total_bytes": 16 * 1024 * MIB}])
        self.assertEqual(self.validate(row)["status"], "fail")
        self.assertIn("GPU has less than 25% headroom", GATE.problems(row))

    def test_promoted_baseline_cannot_mix_effective_inputs(self):
        baseline = [sample(i) for i in range(3)]
        for i, row in enumerate(baseline):
            row["inputs_hash"] = "different-" + str(i)
        self.assertEqual(GATE.compare([sample(i) for i in range(3)], baseline)["status"], "fail")


if __name__ == "__main__":
    unittest.main()
