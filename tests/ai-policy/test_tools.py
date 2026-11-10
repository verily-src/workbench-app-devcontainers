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

    def test_the_shipped_policy_renders_an_mcp_rule_for_every_tool_but_the_denied(self):
        policy, summary = self.rendered(ai={"tools": self.shipped["tools"]})
        rule = policy["network_policies"]["workbench_tools"]
        endpoint = rule["endpoints"][0]
        self.assertEqual((endpoint["host"], endpoint["port"], endpoint["protocol"], endpoint["enforcement"]),
                         ("host.openshell.internal", 9242, "mcp", "enforce"))
        self.assertIn("2025-03-26", endpoint["mcp"]["versions"])
        methods = [r["allow"]["method"] for r in endpoint["rules"]]
        self.assertEqual(methods, ["initialize", "notifications/initialized", "notifications/cancelled", "ping", "tools/list", "tools/call"])
        allowed = endpoint["rules"][-1]["allow"]["tool"]["any"]
        known = {t for tools in self.groups.values() for t in tools}
        deny = self.shipped["tools"]["deny"]
        self.assertEqual(set(allowed) | set(deny), known)
        for tool in deny:
            self.assertNotIn(tool, allowed)
        self.assertEqual({d["tool"] for d in endpoint["deny_rules"]}, set(deny))
        self.assertTrue(all(d["method"] == "tools/call" for d in endpoint["deny_rules"]))
        # The harness's program calls the tools; curl for the self-test.
        self.assertEqual(rule["binaries"], [{"path": "/opt/opencode/.opencode/bin/opencode"}, {"path": "/usr/bin/curl"}])
        self.assertTrue(summary["tools"]["enabled"])
        self.assertEqual(summary["tools"]["url"], MCP_URL)
        self.assertEqual(set(summary["tools"]["denied"]), set(deny))
        self.assertEqual(set(summary["tools"]["groups"]), set(self.groups))

    def test_the_shipped_policy_denies_command_execution_credentials_and_sql_outside_the_sandbox(self):
        for tool in ("wb_execute", "gcloud_execute", "gsutil_execute", "git_execute", "resource_credentials", "bq_execute"):
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
        policy, summary = self.rendered(ai={"tools": {"allow": ["discovery"]}})
        allowed = policy["network_policies"]["workbench_tools"]["endpoints"][0]["rules"][-1]["allow"]["tool"]["any"]
        self.assertEqual(set(allowed), set(self.groups["discovery"]))
        self.assertIn("underlay_list", summary["tools"]["denied"])

    def test_bad_files_are_refused(self):
        for ai in (
            {"tools": {"allow": ["no-such-group"]}},
            {"tools": {"allow": "discovery"}},
            {"tools": {"deny": "wb_execute"}},
        ):
            self.assertNotEqual(self.render(ai=ai).returncode, 0, ai)
        for url in ("host.openshell.internal:9242", "ftp://x.y:1", "http://localhost:9242"):
            self.assertNotEqual(self.render(url=url).returncode, 0, url)

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
