"""Tests for harness.py and render-policy.py: harness binaries and data-access rules in the policy."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[2] / "src" / "opencode-nemotron-openshell"
OPENSHELL = APP / "openshell"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(OPENSHELL / script), *map(str, args)],
                          capture_output=True, text=True, check=False)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, data) -> Path:
        path = self.dir / name
        path.write_text(data if isinstance(data, str) else yaml.safe_dump(data))
        return path

    def render(self, data_access: dict, harness: Path = OPENSHELL / "harnesses" / "opencode.yaml"):
        result = run("render-policy.py", OPENSHELL / "policy.yaml", self.write("da.yaml", data_access), harness)
        self.assertEqual(result.returncode, 0, result.stderr)
        return yaml.safe_load(result.stdout)

    def test_shipped_harnesses_are_valid(self):
        for harness in (OPENSHELL / "harnesses").glob("*.yaml"):
            result = run("harness.py", harness)
            self.assertEqual(result.returncode, 0, f"{harness.name}: {result.stderr}")

    def test_local_models_binaries_come_from_the_harness(self):
        for name, binary in (("opencode", "/opt/opencode/.opencode/bin/opencode"), ("chat-once", "/usr/bin/python3.11")):
            policy = self.render({"enabled": False}, OPENSHELL / "harnesses" / f"{name}.yaml")
            paths = [b["path"] for b in policy["network_policies"]["local_models"]["binaries"]]
            self.assertEqual(paths, [binary, "/usr/bin/curl"])

    def test_a_new_harness_needs_only_a_config_file(self):
        harness = self.write("h.yaml", {"name": "mine", "image": "my-image:1", "binaries": ["/opt/mine/bin/agent"],
                                        "command": ["agent", "--serve"]})
        policy = self.render({"enabled": False}, harness)
        paths = [b["path"] for b in policy["network_policies"]["local_models"]["binaries"]]
        self.assertEqual(paths, ["/opt/mine/bin/agent", "/usr/bin/curl"])

    def test_data_access_off_adds_no_google_rules(self):
        policy = self.render({"enabled": False})
        self.assertEqual(set(policy["network_policies"]), {"local_models"})

    def test_data_access_on_allows_only_listed_things_and_binds_the_provider(self):
        policy = self.render({
            "enabled": True, "provider": "wb-gcp", "project_id": "my-project",
            "bigquery": {"datasets": [{"project": "my-project", "dataset": "demo"}]},
            "storage": {"buckets": ["my-bucket"]},
        })
        bq = policy["network_policies"]["data_bigquery"]["endpoints"][0]
        self.assertEqual(bq["credential_binding"], {"provider": "wb-gcp"})
        allowed = {(r["allow"]["method"], r["allow"]["path"]) for r in bq["rules"]}
        self.assertIn(("POST", "/bigquery/v2/projects/my-project/queries"), allowed)
        self.assertIn(("GET", "/bigquery/v2/projects/my-project/datasets/demo/**"), allowed)
        self.assertEqual({m for m, _ in allowed}, {"GET", "POST"})
        self.assertFalse(any(path.endswith("/datasets") for _, path in allowed), "datasets must not be listable")
        storage = policy["network_policies"]["data_storage"]["endpoints"][0]
        self.assertEqual({r["allow"]["method"] for r in storage["rules"]}, {"GET"})

    def test_unsafe_names_are_rejected(self):
        for config in (
            {"enabled": True, "project_id": "my-project", "storage": {"buckets": ["a/../b"]}},
            {"enabled": True, "project_id": "my-project", "bigquery": {"datasets": [{"project": "my-project", "dataset": "x/**"}]}},
            {"enabled": True, "project_id": "bad project"},
            {"enabled": True},
        ):
            result = run("render-policy.py", OPENSHELL / "policy.yaml", self.write("da.yaml", config),
                         OPENSHELL / "harnesses" / "opencode.yaml")
            self.assertNotEqual(result.returncode, 0, config)

    def test_bad_harness_is_rejected(self):
        for harness in (
            {"name": "Bad Name", "image": "i", "binaries": ["/a"], "command": ["a"]},
            {"name": "x", "image": "i", "binaries": ["relative/path"], "command": ["a"]},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": []},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": ["a"], "env": {"AGENT_MODEL": "x"}},
            {"name": "x", "image": "i", "binaries": ["/a"], "command": ["a"], "surprise": 1},
        ):
            result = run("harness.py", self.write("h.yaml", harness))
            self.assertNotEqual(result.returncode, 0, harness)

    def test_harness_json_is_what_the_wrapper_reads(self):
        result = run("harness.py", OPENSHELL / "harnesses" / "opencode.yaml")
        data = json.loads(result.stdout)
        self.assertEqual(data["command"], ["opencode"])
        self.assertEqual(data["config"]["env"], "OPENCODE_CONFIG_CONTENT")


if __name__ == "__main__":
    unittest.main()
