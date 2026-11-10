"""The sandbox image: what the harness files and the agent-sandbox feature expect of it."""
import re
import unittest
from pathlib import Path

import yaml

FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"
FEATURE = FEATURES / "opencode-harness"
DOCKERFILE = (FEATURE / "sandbox" / "Dockerfile").read_text()


class SandboxImageTests(unittest.TestCase):
    def test_everything_copied_into_the_image_ships_with_a_feature(self):
        # The build context is the app folder, where the platform puts features/src under .devcontainer/features.
        sources = re.findall(r"^COPY (\S+) (\S+)", DOCKERFILE, re.M)
        self.assertTrue(sources)
        for source, _ in sources:
            self.assertTrue(source.startswith(".devcontainer/features/"), source)
            self.assertTrue((FEATURES / source[len(".devcontainer/features/"):]).exists(), source)

    def test_the_agent_sandbox_files_land_where_agent_sandbox_and_the_hook_look(self):
        targets = {target for _, target in re.findall(r"^COPY (\S+) (\S+)", DOCKERFILE, re.M)}
        self.assertIn("/opt/agent-sandbox/instructions.md", targets)
        self.assertIn("/opt/agent-sandbox/data-probe.py", targets)
        hook = (FEATURE / "harnesses" / "opencode-config.sh").read_text()
        self.assertIn('"/opt/agent-sandbox/instructions.md"', hook)
        selftest = (FEATURES / "agent-sandbox" / "selftest.sh").read_text()
        self.assertIn("/opt/agent-sandbox/data-probe.py", selftest)

    def test_the_harnesses_name_programs_the_image_has(self):
        opencode = yaml.safe_load((FEATURE / "harnesses" / "opencode.yaml").read_text())
        self.assertEqual(opencode["binaries"], ["/opt/opencode/.opencode/bin/opencode"])
        self.assertIn("ln -s /opt/opencode/.opencode/bin/opencode /usr/local/bin/opencode", DOCKERFILE)
        # The data rules name the real interpreter this venv resolves to.
        self.assertIn("python3 -m venv /opt/venv", DOCKERFILE)

    def test_the_image_pins_opencode_and_runs_as_the_sandbox_user(self):
        self.assertRegex(DOCKERFILE, r"ARG OPENCODE_VERSION=\d+\.\d+\.\d+")
        self.assertIn("useradd --uid 1500", DOCKERFILE)
        self.assertIn("USER sandbox", DOCKERFILE)



class DataClientTests(unittest.TestCase):
    def test_the_sandbox_has_both_google_client_libraries_the_agent_is_told_about(self):
        dockerfile = (Path(__file__).resolve().parents[2] / "features" / "src" / "opencode-harness" / "sandbox" / "Dockerfile").read_text()
        for package in ("google-cloud-bigquery==", "google-cloud-storage=="):
            self.assertIn(package, dockerfile, package)
        self.assertIn("agent-sandbox/sandbox/wbstorage.py /opt/venv/lib/python3.11/site-packages/wbstorage.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
