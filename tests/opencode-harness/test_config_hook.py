"""opencode-config.sh: OpenCode's sandbox configuration from the framework's environment."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "features" / "src" / "opencode-harness" / "harnesses" / "opencode-config.sh"
MCP_URL = "http://host.openshell.internal:9242"


class ConfigHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **env: str) -> dict:
        environment = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_") and k != "MODEL_BASE_URL"}
        environment.update({"AGENT_MODEL": "nvidia/model", "MODEL_BASE_URL": "http://host.openshell.internal:8000/v1",
                            "AGENT_CONTEXT_LENGTH": "65536"})
        environment.update(env)
        result = subprocess.run([str(HOOK)], capture_output=True, text=True, env=environment, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def summary(self, enabled: bool, denied=("wb_execute", "resource_credentials")) -> str:
        path = self.dir / "summary.json"
        path.write_text(json.dumps({"tools": {"enabled": enabled, "url": MCP_URL, "allowed": ["wb_status"],
                                              "denied": list(denied), "groups": {}}}))
        return str(path)

    def test_only_the_served_model_under_the_vllm_provider(self):
        config = self.config()
        self.assertEqual(config["model"], "vllm/nvidia/model")
        self.assertEqual(config["enabled_providers"], ["vllm"])
        self.assertEqual(list(config["provider"]["vllm"]["models"]), ["nvidia/model"])
        self.assertEqual(config["provider"]["vllm"]["models"]["nvidia/model"]["limit"]["context"], 65536)
        self.assertEqual(config["provider"]["vllm"]["options"]["baseURL"], "http://host.openshell.internal:8000/v1")
        self.assertFalse(config["autoupdate"])
        self.assertEqual(config["share"], "disabled")
        self.assertEqual(config["permission"], {"webfetch": "deny", "external_directory": "allow"})
        self.assertEqual(config["instructions"], ["/opt/agent-sandbox/instructions.md", "/sandbox/data-access.md"])

    def test_no_mcp_server_without_a_url_or_when_the_policy_allows_no_tool(self):
        self.assertEqual(self.config()["mcp"], {})
        self.assertEqual(self.config(AGENT_MCP_URL=MCP_URL)["mcp"], {}, "no summary: nothing is known to be allowed")
        self.assertEqual(self.config(AGENT_MCP_URL=MCP_URL, AGENT_POLICY_SUMMARY=self.summary(False))["mcp"], {})

    def test_the_mcp_server_is_registered_and_denied_tools_are_turned_off(self):
        config = self.config(AGENT_MCP_URL=MCP_URL, AGENT_POLICY_SUMMARY=self.summary(True))
        self.assertEqual(config["mcp"], {"wb": {"type": "remote", "url": MCP_URL, "enabled": True}})
        self.assertEqual(config["tools"], {"wb_wb_execute": False, "wb_resource_credentials": False})

    def test_a_display_name_is_optional(self):
        self.assertEqual(self.config()["provider"]["vllm"]["models"]["nvidia/model"]["name"], "nvidia/model")
        self.assertEqual(self.config(AGENT_MODEL_NAME="Nemotron")["provider"]["vllm"]["models"]["nvidia/model"]["name"], "Nemotron")


if __name__ == "__main__":
    unittest.main()
