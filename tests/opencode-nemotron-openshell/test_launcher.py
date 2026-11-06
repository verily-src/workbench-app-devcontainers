"""Tests for opencode-launch.sh: the agent always starts in the sandbox, with no off switch."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "src" / "opencode-nemotron-openshell"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.record = self.dir / "sandbox-args"
        shutil.copy(APP / "opencode-launch.sh", self.dir / "opencode-launch.sh")
        # Stand-ins for the scripts the launcher hands off to.
        self.stub("agent-sandbox.sh", f'printf "%s\\n" "$@" > "{self.record}"')
        self.stub("resolve-model.sh", 'echo "${STUB_MODEL:-nemotron:test}"')
        self.stub("opencode-model.sh", f'touch "{self.dir}/picker-ran"')

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self, name: str, body: str):
        path = self.dir / name
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(0o755)

    def launch(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        environment = {**os.environ, "OPENCODE_HOME": str(self.home), **env}
        return subprocess.run([str(self.dir / "opencode-launch.sh"), *args], capture_output=True,
                              text=True, env=environment, check=False)

    def test_runs_in_the_sandbox(self):
        self.assertEqual(self.launch("--model", "x").returncode, 0)
        self.assertEqual(self.record.read_text().split(), ["run", "--model", "x"])

    def test_environment_variable_cannot_turn_the_sandbox_off(self):
        self.assertEqual(self.launch(OPENCODE_SANDBOX="off").returncode, 0)
        self.assertTrue(self.record.exists())

    def test_mode_file_cannot_turn_the_sandbox_off(self):
        (self.home / ".opencode-sandbox").write_text("off\n")
        self.assertEqual(self.launch().returncode, 0)
        self.assertTrue(self.record.exists())

    def test_picker_runs_only_when_no_model_is_chosen(self):
        self.launch()
        self.assertFalse((self.dir / "picker-ran").exists())
        self.launch(STUB_MODEL="prompt")
        self.assertTrue((self.dir / "picker-ran").exists())

    def test_no_host_side_opencode_config_or_mcp(self):
        self.assertFalse((APP / "configure-opencode.sh").exists())
        for name in ("opencode-launch.sh", "start-services.sh", "opencode-model.sh", "Dockerfile"):
            self.assertNotIn("configure-opencode", (APP / name).read_text(), name)
        self.assertNotIn("OPENCODE_SANDBOX", (APP / "docker-compose.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
