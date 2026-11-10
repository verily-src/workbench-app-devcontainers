"""render-policy.py: the harness's binaries and the workspace's data in the policy, as ai-policy.yaml allows."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"
AI_POLICY = FEATURES / "ai-policy"
CONFIG = FEATURES / "agent-sandbox" / "config"
HARNESS_PY = FEATURES / "agent-sandbox" / "harness.py"
HARNESSES = FEATURES / "opencode-harness" / "harnesses"
BQ = "/bigquery/v2/projects"

WORKSPACE = {
    "workspace": "demo", "project": "ws-project", "unavailable": False, "errors": [],
    "resources": [
        {"name": "admin", "type": "bigquery", "project": "bhs-project", "dataset": "admin", "stewardship": "referenced"},
        {"name": "mine", "type": "bigquery", "project": "ws-project", "dataset": "synthetic", "stewardship": "controlled"},
        {"name": "uploads", "type": "storage", "bucket": "uploads-ws", "stewardship": "controlled"},
        {"name": "shared", "type": "storage", "bucket": "shared-bucket", "stewardship": "referenced"},
    ],
}


def harness_json(directory: Path, harness: Path) -> Path:
    """The harness as agent-sandbox hands it to the compiler: harness.py's JSON."""
    result = subprocess.run([sys.executable, str(HARNESS_PY), str(harness)], capture_output=True, text=True, check=True)
    path = directory / f"{harness.stem}.json"
    path.write_text(result.stdout)
    return path


def run_render(*args: str, project: str | None = None, credential: str | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("GOOGLE_CLOUD_PROJECT", "AGENT_DATA_CREDENTIAL")}
    if project is not None:
        env["GOOGLE_CLOUD_PROJECT"] = project
    if credential is not None:
        env["AGENT_DATA_CREDENTIAL"] = credential
    return subprocess.run([sys.executable, str(AI_POLICY / "render-policy.py"), *map(str, args)],
                          capture_output=True, text=True, check=False, env=env)


class RenderPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, data) -> Path:
        path = self.dir / name
        path.write_text(data if isinstance(data, str) else (json.dumps(data) if name.endswith(".json") else yaml.safe_dump(data)))
        return path

    def render(self, ai: dict | None = None, workspace: dict | None = WORKSPACE, harness: Path = HARNESSES / "opencode.yaml",
               policy: Path = CONFIG / "policy.yaml", summary: bool = False, **env):
        args = [policy, self.write("ai.yaml", {"version": 1, **(ai or {})}), "--harness", harness_json(self.dir, harness)]
        if workspace is not None:
            args += ["--workspace", self.write("ws.json", workspace)]
        if summary:
            args += ["--summary", self.dir / "summary.json"]
        result = run_render(*args, **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = yaml.safe_load(result.stdout)
        if summary:
            return rendered, json.loads((self.dir / "summary.json").read_text())
        return rendered

    def rules(self, policy, name):
        return {(r["allow"]["method"], r["allow"]["path"]) for r in policy["network_policies"][name]["endpoints"][0]["rules"]}

    def test_local_models_binaries_come_from_the_harness(self):
        policy = self.render(workspace=None)
        paths = [b["path"] for b in policy["network_policies"]["local_models"]["binaries"]]
        self.assertEqual(paths, ["/opt/opencode/.opencode/bin/opencode", "/usr/bin/curl"])

    def test_a_new_harness_needs_only_a_config_file(self):
        harness = self.write("h.yaml", {"name": "mine", "image": "my-image:1", "binaries": ["/opt/mine/bin/agent"],
                                        "command": ["agent", "--serve"]})
        policy = self.render(workspace=None, harness=harness)
        paths = [b["path"] for b in policy["network_policies"]["local_models"]["binaries"]]
        self.assertEqual(paths, ["/opt/mine/bin/agent", "/usr/bin/curl"])

    def test_data_read_none_adds_no_google_rules(self):
        policy = self.render({"data": {"read": "none", "write": "none"}})
        self.assertEqual(set(policy["network_policies"]), {"local_models"})

    def test_the_default_reads_the_workspace_and_writes_to_what_it_owns(self):
        policy, summary = self.render(summary=True)
        bq = self.rules(policy, "data_bigquery")
        # Jobs in the workspace's project, listing in both projects, lookups everywhere.
        self.assertIn(("POST", f"{BQ}/ws-project/jobs"), bq)
        self.assertIn(("GET", f"{BQ}/ws-project/datasets"), bq)
        self.assertIn(("GET", f"{BQ}/bhs-project/datasets"), bq)
        self.assertIn(("GET", f"{BQ}/bhs-project/datasets/admin/**"), bq)
        self.assertIn(("GET", f"{BQ}/ws-project/datasets/synthetic/**"), bq)
        # Changes only in the owned dataset.
        self.assertIn(("DELETE", f"{BQ}/ws-project/datasets/synthetic/**"), bq)
        self.assertNotIn(("DELETE", f"{BQ}/bhs-project/datasets/admin/**"), bq)
        self.assertEqual({m for m, p in bq if "bhs-project" in p}, {"GET"})
        gcs = self.rules(policy, "data_storage")
        self.assertIn(("GET", "/storage/v1/b/shared-bucket/o/**"), gcs)
        self.assertIn(("POST", "/upload/storage/v1/b/uploads-ws/o"), gcs)
        self.assertIn(("DELETE", "/uploads-ws/**"), gcs)
        # No write on the JSON object paths: copyTo and rewriteTo there name a second bucket.
        self.assertEqual({m for m, p in gcs if p.startswith("/storage/v1/")}, {"GET"})
        self.assertEqual({m for m, p in gcs if "shared-bucket" in p}, {"GET"})
        for name in ("data_bigquery", "data_storage"):
            endpoint = policy["network_policies"][name]["endpoints"][0]
            self.assertEqual(endpoint["credential_binding"], {"provider": "wb-gcp"})
            self.assertEqual(endpoint["enforcement"], "enforce")
            self.assertEqual(policy["network_policies"][name]["binaries"], [{"path": "/usr/bin/python3.11"}])
        self.assertTrue(summary["data"]["write"])
        self.assertEqual(summary["data"]["project"], "ws-project")
        self.assertEqual([d["write"] for d in summary["data"]["datasets"]], [False, True])
        self.assertEqual([b["write"] for b in summary["data"]["buckets"]], [True, False])

    def test_an_unreadable_workbench_renders_no_data_rules_and_a_policy_that_still_parses(self):
        unavailable = {"unavailable": True, "errors": ["wb failed: line one\nCaused by: line two"], "resources": []}
        policy, summary = self.render(workspace=unavailable, summary=True)
        self.assertEqual(set(policy), {"version", "filesystem_policy", "landlock", "network_policies"})
        self.assertNotIn("data_bigquery", policy["network_policies"])
        self.assertTrue(summary["data"]["unavailable"])

    def test_write_none_keeps_everything_read_only(self):
        policy, summary = self.render({"data": {"write": "none"}}, summary=True)
        self.assertEqual({m for m, _ in self.rules(policy, "data_bigquery")}, {"GET", "POST"})
        self.assertFalse(any(p.endswith("/jobs") is False and m == "POST" and "datasets" in p for m, p in self.rules(policy, "data_bigquery")))
        self.assertEqual({m for m, _ in self.rules(policy, "data_storage")}, {"GET"})
        self.assertFalse(summary["data"]["write"])
        self.assertFalse(any(d["write"] for d in summary["data"]["datasets"]))

    def test_the_workspace_project_falls_back_to_the_environment(self):
        workspace = {**WORKSPACE, "project": None}
        policy = self.render(workspace=workspace, project="env-project")
        self.assertIn(("POST", f"{BQ}/env-project/jobs"), self.rules(policy, "data_bigquery"))

    def test_workbench_unavailable_renders_no_data_rules(self):
        policy, summary = self.render(workspace={"unavailable": True, "errors": ["GET resources: HTTP 503"], "resources": []},
                                      summary=True, project="ws-project")
        self.assertEqual(set(policy["network_policies"]), {"local_models"})
        self.assertTrue(summary["data"]["unavailable"])
        self.assertFalse(summary["data"]["enabled"])
        self.assertTrue(any("could not be read" in n for n in summary["notes"]))

    def test_no_credential_renders_no_data_rules(self):
        # OpenShell refuses a policy that binds a provider the sandbox does not have.
        policy, summary = self.render(summary=True, credential="missing")
        self.assertEqual(set(policy["network_policies"]), {"local_models"})
        self.assertTrue(any("no Google credential" in n for n in summary["notes"]))

    def test_unsafe_names_are_rejected(self):
        for resource in (
            {"type": "storage", "bucket": "a/../b", "stewardship": "controlled"},
            {"type": "bigquery", "project": "ws-project", "dataset": "x/**", "stewardship": "referenced"},
            {"type": "bigquery", "project": "bad project", "dataset": "x", "stewardship": "referenced"},
        ):
            workspace = {**WORKSPACE, "resources": [resource]}
            result = run_render(CONFIG / "policy.yaml", self.write("ai.yaml", {"version": 1}),
                                "--harness", harness_json(self.dir, HARNESSES / "opencode.yaml"),
                                "--workspace", self.write("ws.json", workspace))
            self.assertNotEqual(result.returncode, 0, resource)

    def test_an_invalid_ai_policy_is_refused(self):
        for ai in ({"version": 2}, {"version": 1, "data": {"access": "read"}}, {"version": 1, "network": {"egress": "none"}}):
            result = run_render(CONFIG / "policy.yaml", self.write("ai.yaml", ai),
                                "--harness", harness_json(self.dir, HARNESSES / "opencode.yaml"))
            self.assertNotEqual(result.returncode, 0, ai)
            self.assertIn("ai.yaml", result.stderr)

    def test_a_base_policy_that_defines_a_generated_rule_is_refused(self):
        policy = yaml.safe_load((CONFIG / "policy.yaml").read_text())
        policy["network_policies"]["workbench_tools"] = {"name": "workbench_tools", "endpoints": []}
        result = run_render(self.write("p.yaml", policy), self.write("ai.yaml", {"version": 1}),
                            "--harness", harness_json(self.dir, HARNESSES / "opencode.yaml"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("generated", result.stderr)

    def test_every_endpoint_enforces(self):
        policy = yaml.safe_load((CONFIG / "policy.yaml").read_text())
        policy["network_policies"]["pypi"] = {"name": "pypi", "endpoints": [
            {"host": "pypi.org", "port": 443, "protocol": "rest", "access": "read-only"}], "binaries": [{"path": "/usr/bin/python3.11"}]}
        result = run_render(self.write("p.yaml", policy), self.write("ai.yaml", {"version": 1}),
                            "--harness", harness_json(self.dir, HARNESSES / "opencode.yaml"))
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = yaml.safe_load(result.stdout)
        for rule in rendered["network_policies"].values():
            for endpoint in rule["endpoints"]:
                self.assertEqual(endpoint["enforcement"], "enforce", rule["name"])
        self.assertIn("set enforcement: enforce on rule pypi", result.stdout)

    def test_the_header_says_what_was_decided(self):
        result = run_render(CONFIG / "policy.yaml", CONFIG / "ai-policy.yaml",
                            "--harness", harness_json(self.dir, HARNESSES / "opencode.yaml"),
                            "--workspace", self.write("ws.json", WORKSPACE))
        self.assertEqual(result.returncode, 0, result.stderr)
        head = result.stdout.split("version:")[0]
        self.assertIn("data read: workspace; data write: controlled", head)
        self.assertIn("read 2 datasets and 2 buckets of workspace demo; write to the 2 it owns", head)


if __name__ == "__main__":
    unittest.main()
