"""No workspace's project id, and no developer's name, in the AI Research Assistant's text files."""
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FEATURES = ["ai-policy", "agent-sandbox", "cohort-designer", "kumo-forecast", "opencode-harness",
            "vertex-model", "vllm-model", "wb-mcp-server"]
ROOTS = ["src/ai-research-assistant", "tests/ai-research-assistant"] + [
    f"{kind}/{feature}" for feature in FEATURES for kind in ("features/src", "tests")]
# Built from pieces so that this file does not match itself.
PROJECT_ID = "wb-" + "[a-z]+" + "-" + "[a-z]+" + "-" + "[0-9]{4}"
NAME = "sa" + "mh"
PATTERN = re.compile(rf"{PROJECT_ID}|\b{NAME}\b")
SKIP_DIRS = {"__pycache__", "node_modules", ".git"}
# The cohort designer's release is one fixed place for every workspace (its README, "The
# binary"), not the workspace's own project.
RELEASE = json.loads((REPO / "features/src/cohort-designer/devcontainer-feature.json").read_text())[
    "options"]["release"]["default"]


def text_files():
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*")):
            if not path.is_file() or path.name == "uv.lock" or SKIP_DIRS & set(path.parts):
                continue
            try:
                yield path, path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary


class NoProjectIdTests(unittest.TestCase):
    def test_no_workspace_project_id_or_developer_name(self):
        found = [f"{path.relative_to(REPO)}:{number}: {line.strip()[:100]}"
                 for path, text in text_files()
                 for number, line in enumerate(text.splitlines(), 1) if PATTERN.search(line.replace(RELEASE, ""))]
        self.assertEqual(found, [], "\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
