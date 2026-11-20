"""agent-sandbox's access gate (check_access): no sandbox for a person the app's access state does
not admit. The function is run alone, out of the script."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "features" / "src" / "agent-sandbox" / "agent-sandbox.sh"


def function(text, name):
    return re.search(rf"^{name}\(\) {{\n.*?^}}\n", text, re.M | re.S).group(0)


class AccessGateTests(unittest.TestCase):
    def run_gate(self, state):
        text = SCRIPT.read_text()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "access.json"
            if state is not None:
                path.write_text(state if isinstance(state, str) else json.dumps(state))
            program = (f'ACCESS_STATE={path if state != "unset" else ""}\n' + function(text, "die")
                       + function(text, "check_access") + "check_access && echo admitted\n")
            return subprocess.run(["bash", "-c", program], capture_output=True, text=True, check=False)

    def test_an_admitted_person_passes(self):
        result = self.run_gate({"status": "ok", "tier": "beta"})
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "admitted"), result.stderr)

    def test_no_state_configured_means_no_gate(self):
        self.assertEqual(self.run_gate("unset").returncode, 0)

    def test_everyone_else_is_stopped_with_the_reason(self):
        for state, reason in ((None, "has not checked your access"),
                              ({"status": "ok", "tier": None, "message": "is in beta"}, "is in beta"),
                              ({"status": "error", "tier": None, "message": "couldn't verify", "error": "timeout"}, "timeout"),
                              ("not json", "not an access state"),
                              ({"status": "other"}, "not an access state")):
            with self.subTest(reason):
                result = self.run_gate(state)
                self.assertEqual(result.returncode, 1)
                self.assertIn(reason, result.stderr)
                self.assertNotIn("admitted", result.stdout)


if __name__ == "__main__":
    unittest.main()
