"""The front door: Workbench's proxy reaches the first published port, which Caddy owns."""
import re
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[2] / "src" / "ai-research-assistant"
FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"


class FrontDoorTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())
        self.caddyfile = (APP / "caddy" / "Caddyfile").read_text()

    def test_caddy_owns_the_first_published_port_of_the_app(self):
        first = str(self.compose["services"]["app"]["ports"][0])
        self.assertEqual(first, "8080:8080")
        self.assertIn(":8080 {", self.caddyfile)
        web = self.compose["services"]["opencode-web"]
        self.assertEqual(web["network_mode"], "service:app")
        self.assertIn("./caddy:/etc/caddy:ro", web["volumes"])
        # code-server's own port is reached only through Caddy.
        self.assertFalse([p for p in self.compose["services"]["app"]["ports"] if "8443" in str(p)])

    def test_port_guard_guards_the_published_port(self):
        guard = self.compose["services"]["port-guard"]["environment"]["GUARDED_PORT"]
        self.assertEqual(str(guard), "8080")

    def test_broker_allows_the_web_command(self):
        allow = re.search(r"^\s*(run\|[^)]*)\)", (FEATURES / "agent-sandbox" / "broker" / "command.sh").read_text(), re.M).group(1)
        self.assertIn("web", allow.split("|"))


if __name__ == "__main__":
    unittest.main()
