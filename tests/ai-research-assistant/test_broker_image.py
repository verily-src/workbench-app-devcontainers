"""The template's wiring of the features: the broker image, the sandbox image, the compose
environment the features read, and the devcontainer's feature list."""
import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "ai-research-assistant"
FEATURES = ROOT / "features" / "src"


class TemplateWiringTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())
        self.devcontainer = json.loads((APP / ".devcontainer.json").read_text())

    def test_the_devcontainer_installs_the_four_features_and_opens_the_mcp_server(self):
        features = self.devcontainer["features"]
        for name in ("vllm-model", "ai-policy", "agent-sandbox", "opencode-harness", "wb-mcp-server", "llm-context"):
            self.assertIn(f"./.devcontainer/features/{name}", features, name)
            self.assertTrue((FEATURES / name / "install.sh").exists(), name)
        for name in ("vllm-model", "agent-sandbox", "opencode-harness"):
            self.assertEqual(features[f"./.devcontainer/features/{name}"], {"username": "abc", "userHomeDir": "/config"})
        self.assertEqual(features["./.devcontainer/features/wb-mcp-server"]["bindAddress"], "0.0.0.0")

    def test_the_broker_image_is_built_from_the_features(self):
        dockerfile = (APP / "broker" / "Dockerfile").read_text()
        for name in ("ai-policy", "agent-sandbox", "opencode-harness"):
            self.assertIn(f"COPY .devcontainer/features/{name} /tmp/features/{name}", dockerfile)
            self.assertIn(f"/tmp/features/{name}/install.sh", dockerfile)
        self.assertIn("ROLE=broker", dockerfile)
        self.assertIn("INSTALLLAUNCHER=false", dockerfile)
        self.assertIn('ENTRYPOINT ["/opt/agent-sandbox/broker/entrypoint.sh"]', dockerfile)
        self.assertEqual(self.compose["services"]["sandbox-broker"]["build"]["dockerfile"], "broker/Dockerfile")

    def test_the_sandbox_image_is_the_harness_features(self):
        build = self.compose["services"]["sandbox-image"]["build"]
        self.assertEqual(build["context"], ".")
        self.assertTrue((FEATURES / build["dockerfile"][len(".devcontainer/features/"):]).exists(), build["dockerfile"])
        harness = yaml.safe_load((FEATURES / "opencode-harness" / "harnesses" / "opencode.yaml").read_text())
        self.assertEqual(self.compose["services"]["sandbox-image"]["image"], harness["image"])

    def test_the_sandbox_reaches_the_model_and_the_tools_on_the_published_loopback_ports(self):
        app = self.compose["services"]["app"]
        broker = self.compose["services"]["sandbox-broker"]
        published = {str(p) for p in app["ports"]}
        for env in (app["environment"], broker["environment"]):
            model_port = re.search(r"host\.openshell\.internal:(\d+)/v1$", env["AGENT_MODEL_URL"]).group(1)
            mcp_port = re.search(r"host\.openshell\.internal:(\d+)$", env["AGENT_MCP_URL"]).group(1)
            self.assertIn(f"127.0.0.1:{model_port}:{app['environment']['VLLM_PORT']}", published)
            self.assertIn(f"127.0.0.1:{mcp_port}:{mcp_port}", published)
        self.assertEqual(str(broker["environment"]["AGENT_CONTEXT_LENGTH"]), str(app["environment"]["VLLM_CONTEXT_LENGTH"]))
        self.assertEqual(app["environment"]["AGENT_BROKER"], "sandbox-broker")
        self.assertEqual(app["environment"]["AGENT_MODEL_COMMAND"], "/opt/vllm-model/resolve-model.sh")
        self.assertNotIn("AGENT_BROKER", broker["environment"], "the broker runs the commands itself")

    def test_start_services_runs_what_the_features_install(self):
        start = (APP / "start-services.sh").read_text()
        for path in ("/opt/wb-mcp-server/start-server.sh", "/opt/llm-context/run-context-generator.sh", "/opt/vllm-model/start-vllm.sh"):
            self.assertIn(path, start)
        self.assertIn("agent-sandbox web", start)
        self.assertIn("AGENT_MODEL_COMMAND", start, "the model command must survive sudo")
        for stale in ("OPENCODE_HOME", "/opt/opencode-workbench", "AGENT_POLICY_SOURCE"):
            self.assertNotIn(stale, start)
        # Every VLLM_* setting in compose reaches start-vllm.sh through --preserve-env.
        preserved = set(re.search(r"--preserve-env=(APP_USER_HOME[A-Z_,]+)", start).group(1).split(","))
        for name in self.compose["services"]["app"]["environment"]:
            if name.startswith("VLLM_"):
                self.assertIn(name, preserved, name)

    def test_the_app_image_has_no_framework_of_its_own(self):
        dockerfile = (APP / "Dockerfile").read_text()
        for stale in ("opencode.ai/install", "/opt/opencode-workbench", "openshell.tar.gz", "vllm[runai]", "/opt/vllm", "COPY "):
            self.assertNotIn(stale, dockerfile, stale)
        for folder in ("openshell/harnesses", "sandbox-image", "broker/command.sh", "agent-sandbox.sh", "start-vllm.sh"):
            self.assertFalse((APP / folder).exists(), folder)


if __name__ == "__main__":
    unittest.main()
