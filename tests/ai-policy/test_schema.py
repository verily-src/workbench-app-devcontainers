"""ai_policy.py: the ai-policy.yaml schema the compiler follows, and what it refuses."""
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"
sys.path.insert(0, str(FEATURES / "ai-policy"))
import ai_policy  # noqa: E402

GROUPS = ai_policy.load_tool_groups(ai_policy.load_file(FEATURES / "agent-sandbox" / "tool-groups.yaml"))
SHIPPED = FEATURES / "agent-sandbox" / "config" / "ai-policy.yaml"


def read(text: str, groups=GROUPS):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as handle:
        handle.write(text)
        handle.flush()
        return ai_policy.read_policy(ai_policy.load_file(handle.name), groups)


class SchemaTests(unittest.TestCase):
    def test_the_shipped_file_is_valid(self):
        policy = ai_policy.read_policy(ai_policy.load_file(SHIPPED), GROUPS)
        self.assertIn("data read: workspace; data write: controlled; tools: all; denied: wb_execute",
                      ai_policy.describe(policy))

    def test_defaults_and_explicit_values(self):
        self.assertEqual(ai_policy.describe(read("version: 1\n")), "data read: workspace; data write: controlled; tools: all")
        self.assertEqual(ai_policy.describe(read("version: 1\ndata:\n  read: none\n  write: none\ntools:\n  allow: none\n")),
                         "data read: none; data write: none; tools: none")
        self.assertEqual(read("version: 1\ntools:\n  allow: [discovery]\n").tools, ["discovery"])

    def test_a_file_this_app_cannot_follow_is_refused_with_the_reason(self):
        for text, reason in (
            ("version: 2\n", "version"),
            ("version: 1\ndata:\n  read: all\n", "data.read"),
            ("version: 1\ndata:\n  write: referenced\n", "data.write"),
            ("version: 1\ndata:\n  read: none\n", "data.write: controlled needs data.read: workspace"),
            ("version: 1\ndata:\n  access: read\n", "does not know"),
            ("version: 1\nnetwork:\n  egress: none\n", "does not know"),
            ("version: 1\ndata:\n  read: none\n  read: workspace\n", "duplicate key"),
            ("version: 1\ntools:\n  allow: [no-such-group]\n", "no-such-group"),
            ("version: 1\ntools:\n  deny: [has space]\n", "tools.deny"),
            ("- a list\n", "mapping"),
        ):
            with self.assertRaises((ai_policy.InvalidPolicy, yaml.YAMLError), msg=text) as raised:
                read(text)
            self.assertIn(reason, str(raised.exception), text)


if __name__ == "__main__":
    unittest.main()
