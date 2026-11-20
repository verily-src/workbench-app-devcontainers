"""The Workbench tools rule: ai-policy.yaml's tools section and the tool catalog become an OpenShell mcp endpoint."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"
AI_POLICY = FEATURES / "ai-policy"
SANDBOX = FEATURES / "agent-sandbox"
CONFIG = SANDBOX / "config"
GROUPS = SANDBOX / "tool-groups.yaml"
HARNESS_PY = SANDBOX / "harness.py"
OPENCODE = FEATURES / "opencode-harness" / "harnesses" / "opencode.yaml"
MCP_SERVER = FEATURES / "wb-mcp-server" / "main.go"
MCP_URL = "http://host.openshell.internal:9242"


class ToolsRuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        harness = subprocess.run([sys.executable, str(HARNESS_PY), str(OPENCODE)], capture_output=True, text=True, check=True)
        self.harness = self.dir / "harness.json"
        self.harness.write_text(harness.stdout)
        self.groups = yaml.safe_load(GROUPS.read_text())["groups"]
        self.shipped = yaml.safe_load((CONFIG / "ai-policy.yaml").read_text())

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, ai=None, url=MCP_URL, groups=True):
        ai_path = self.dir / "ai.yaml"
        ai_path.write_text(yaml.safe_dump({"version": 1, "data": {"read": "none", "write": "none"}, **(ai or {})}))
        args = [sys.executable, str(AI_POLICY / "render-policy.py"), str(CONFIG / "policy.yaml"), str(ai_path),
                "--harness", str(self.harness), "--summary", str(self.dir / "summary.json")]
        if groups:
            args += ["--tools", str(GROUPS)]
        if url:
            args += ["--mcp-url", url]
        env = {k: v for k, v in os.environ.items() if k not in ("GOOGLE_CLOUD_PROJECT", "AGENT_DATA_CREDENTIAL")}
        return subprocess.run(args, capture_output=True, text=True, check=False, env=env)

    def rendered(self, **kwargs):
        result = self.render(**kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return yaml.safe_load(result.stdout), json.loads((self.dir / "summary.json").read_text())

    def test_the_shipped_policy_renders_an_mcp_rule_for_every_allowed_tool_but_the_denied(self):
        policy, summary = self.rendered(ai={"tools": self.shipped["tools"]})
        rule = policy["network_policies"]["workbench_tools"]
        endpoint = rule["endpoints"][0]
        self.assertEqual((endpoint["host"], endpoint["port"], endpoint["protocol"], endpoint["enforcement"]),
                         ("host.openshell.internal", 9242, "mcp", "enforce"))
        self.assertIn("2025-03-26", endpoint["mcp"]["versions"])
        methods = [r["allow"]["method"] for r in endpoint["rules"]]
        self.assertEqual(methods, ["initialize", "notifications/initialized", "notifications/cancelled", "ping", "tools/list", "tools/call"])
        allowed = endpoint["rules"][-1]["allow"]["tool"]["any"]
        in_groups = {t for g in self.shipped["tools"]["allow"] for t in self.groups[g]}
        deny = self.shipped["tools"]["deny"]
        self.assertEqual(set(allowed), in_groups - set(deny))
        for tool in deny:
            self.assertNotIn(tool, allowed)
        known = {t for tools in self.groups.values() for t in tools}
        self.assertEqual({d["tool"] for d in endpoint["deny_rules"]}, known - set(allowed))
        self.assertTrue(all(d["method"] == "tools/call" for d in endpoint["deny_rules"]))
        # The harness's program calls the tools; curl for the self-test.
        self.assertEqual(rule["binaries"], [{"path": "/opt/opencode/.opencode/bin/opencode"}, {"path": "/usr/bin/curl"}])
        self.assertTrue(summary["tools"]["enabled"])
        self.assertEqual(summary["tools"]["url"], MCP_URL)
        self.assertEqual(set(summary["tools"]["denied"]), known - set(allowed))
        self.assertEqual(set(summary["tools"]["groups"]), set(self.groups))

    def test_the_shipped_policy_allows_only_core_and_workflow_tools(self):
        self.assertEqual(self.shipped["tools"]["allow"], ["core", "workflows"])
        policy, _ = self.rendered(ai={"tools": self.shipped["tools"]})
        allowed = set(policy["network_policies"]["workbench_tools"]["endpoints"][0]["rules"][-1]["allow"]["tool"]["any"])
        permitted = set(self.groups["core"]) | set(self.groups["workflows"])
        for group in ("admin", "apps", "dataexplorer", "legacy"):
            for tool in self.groups[group]:
                if tool not in permitted:
                    self.assertNotIn(tool, allowed, f"{tool} ({group})")
        for tool in ("workspace_add_user", "workspace_delete"):
            self.assertNotIn(tool, allowed)
        self.assertLessEqual(allowed, permitted)

    def test_the_shipped_policy_denies_command_execution_credentials_and_sql_outside_the_sandbox(self):
        for tool in ("wb_execute", "gcloud_execute", "gsutil_execute", "git_execute", "bq_execute", "bq_query"):
            self.assertIn(tool, self.shipped["tools"]["deny"])

    def test_no_mcp_url_renders_no_rule(self):
        policy, summary = self.rendered(url=None)
        self.assertNotIn("workbench_tools", policy["network_policies"])
        self.assertFalse(summary["tools"]["enabled"])

    def test_no_catalog_renders_no_rule(self):
        policy, summary = self.rendered(groups=False)
        self.assertNotIn("workbench_tools", policy["network_policies"])
        self.assertFalse(summary["tools"]["enabled"])

    def test_tools_none_renders_no_rule(self):
        policy, _ = self.rendered(ai={"tools": {"allow": "none"}})
        self.assertNotIn("workbench_tools", policy["network_policies"])

    def test_allow_can_name_groups(self):
        policy, summary = self.rendered(ai={"tools": {"allow": ["core"]}})
        allowed = policy["network_policies"]["workbench_tools"]["endpoints"][0]["rules"][-1]["allow"]["tool"]["any"]
        self.assertEqual(set(allowed), set(self.groups["core"]))
        self.assertIn("underlay_list", summary["tools"]["denied"])

    def test_bad_files_are_refused(self):
        for ai in (
            {"tools": {"allow": ["no-such-group"]}},
            {"tools": {"allow": "core"}},
            {"tools": {"deny": "wb_execute"}},
        ):
            self.assertNotEqual(self.render(ai=ai).returncode, 0, ai)
        for url in ("host.openshell.internal:9242", "ftp://x.y:1", "http://localhost:9242"):
            self.assertNotEqual(self.render(url=url).returncode, 0, url)

    def test_the_shipped_catalog_asks_before_starting_registering_or_cancelling_a_workflow(self):
        _, summary = self.rendered(ai={"tools": self.shipped["tools"]})
        self.assertEqual(summary["tools"]["ask"], ["workflow_create", "workflow_job_run", "workflow_job_cancel"])

    def test_a_denied_tool_is_not_asked_about(self):
        _, summary = self.rendered(ai={"tools": {"allow": "all", "deny": ["workflow_job_run"]}})
        self.assertEqual(summary["tools"]["ask"], ["workflow_create", "workflow_job_cancel"])
        _, summary = self.rendered(ai={"tools": {"allow": ["core"]}})
        self.assertEqual(summary["tools"]["ask"], [], "tools outside the allowed groups are not asked about")

    def test_the_ask_list_is_checked(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("ai_policy", AI_POLICY / "ai_policy.py")
        ai_policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ai_policy)
        groups = {"core": ["a_tool", "b_tool"], "other": ["c_tool"]}
        self.assertEqual(ai_policy.load_tool_asks({"ask": ["b_tool", "c_tool", "b_tool"]}, groups), ["b_tool", "c_tool"])
        self.assertEqual(ai_policy.load_tool_asks({}, groups), [])
        with self.assertRaisesRegex(ValueError, "ask names nope_tool, which are in no group"):
            ai_policy.load_tool_asks({"ask": ["a_tool", "nope_tool"]}, groups)
        for bad in ("a_tool", {"a_tool": 1}, [1], ["Bad Name"]):
            with self.assertRaisesRegex(ValueError, "ask must be a list of tool names"):
                ai_policy.load_tool_asks({"ask": bad}, groups)

    def test_a_bad_ask_list_is_refused_by_the_renderer(self):
        bad = self.dir / "groups.yaml"
        bad.write_text("groups:\n  core: [wb_status]\nask: [not_a_tool]\n")
        ai_path = self.dir / "ai.yaml"
        ai_path.write_text(yaml.safe_dump({"version": 1, "data": {"read": "none", "write": "none"}}))
        result = subprocess.run([sys.executable, str(AI_POLICY / "render-policy.py"), str(CONFIG / "policy.yaml"), str(ai_path),
                                 "--harness", str(self.harness), "--tools", str(bad), "--mcp-url", MCP_URL],
                                capture_output=True, text=True, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("in no group", result.stderr)

    def test_the_catalog_covers_exactly_the_servers_tools(self):
        """tool-groups.yaml is this app's view of wb-mcp-server's tools: a tool in no group is not callable."""
        names = re.findall(r'^\s*Name:\s*"([^"]+)"', MCP_SERVER.read_text(), re.M)
        self.assertGreater(len(names), 50)
        grouped = {t for tools in self.groups.values() for t in tools}
        self.assertEqual(set(names) - grouped, set(), "server tools missing from tool-groups.yaml")
        self.assertEqual(grouped - set(names), set(), "tool-groups.yaml names tools the server does not have")
        self.assertLessEqual(set(self.shipped["tools"]["deny"]), set(names))


if __name__ == "__main__":
    unittest.main()
