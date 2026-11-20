"""Static checks for the audit log configuration (the gateway and the app mount)."""
import tomllib
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[2] / "src" / "opencode-nemotron-openshell"


class AuditConfigTests(unittest.TestCase):
    def test_gateway_writes_ocsf_jsonl_under_the_audit_folder(self):
        config = tomllib.loads((APP / "openshell" / "gateway.toml").read_text())
        log = config["openshell"]["gateway"]["ocsf_log"]
        self.assertTrue(log["path"].startswith("/var/lib/openshell/audit/"))
        self.assertEqual(log["rotation"], "daily")

    def test_app_mounts_only_the_audit_folder_read_only(self):
        compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())
        mounts = [v for v in compose["services"]["app"]["volumes"] if isinstance(v, dict)]
        audit = [m for m in mounts if m["target"] == "/var/lib/openshell-audit"]
        self.assertEqual(len(audit), 1)
        self.assertTrue(audit[0]["read_only"])
        self.assertEqual(audit[0]["source"], "/var/lib/openshell/audit")
        # The rest of /var/lib/openshell holds the gateway's signing keys.
        self.assertFalse([m for m in mounts if m["source"] == "/var/lib/openshell"])

    def test_gateway_still_mounts_its_data_but_the_app_does_not(self):
        compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())
        gateway = compose["services"]["openshell-gateway"]["volumes"]
        self.assertTrue(any(isinstance(v, dict) and v.get("source") == "/var/lib/openshell" for v in gateway))


if __name__ == "__main__":
    unittest.main()
