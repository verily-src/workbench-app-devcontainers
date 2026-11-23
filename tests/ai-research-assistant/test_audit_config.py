"""Only the gateway sees the gateway's data (its signing keys among it)."""
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[2] / "src" / "ai-research-assistant"


class GatewayDataTests(unittest.TestCase):
    def test_only_the_gateway_mounts_its_data(self):
        services = yaml.safe_load((APP / "docker-compose.yaml").read_text())["services"]

        def mounts_gateway_data(name):
            return any(isinstance(v, dict) and str(v.get("source", "")).startswith("/var/lib/openshell")
                       for v in services[name].get("volumes", []))

        self.assertTrue(mounts_gateway_data("openshell-gateway"))
        for name in ("app", "sandbox-broker"):
            self.assertFalse(mounts_gateway_data(name), name)


if __name__ == "__main__":
    unittest.main()
