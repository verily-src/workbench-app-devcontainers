"""opencode-launch.sh: the agent always starts in the sandbox, with no off switch."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

FEATURE = Path(__file__).resolve().parents[2] / "features" / "src" / "opencode-harness"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.record = self.dir / "sandbox-args"
        # Stand-ins for the commands the launcher hands off to.
        self.stub("agent-sandbox", f'printf "%s\\n" "$@" > "{self.record}"')
        self.stub("model-command", 'echo "${STUB_MODEL:-nvidia/test}"')

    def tearDown(self):
        self.tmp.cleanup()

    def stub(self, name: str, body: str):
        path = self.bin / name
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(0o755)

    def launch(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        environment = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
                       "AGENT_MODEL_COMMAND": str(self.bin / "model-command")}
        environment.pop("AGENT_MODEL", None)
        environment.update(env)
        return subprocess.run([str(FEATURE / "opencode-launch.sh"), *args], capture_output=True, text=True,
                              env=environment, check=False)

    def test_runs_in_the_sandbox(self):
        result = self.launch("--model", "x")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.record.read_text().split(), ["run", "--model", "x"])

    def test_version_and_help_go_to_the_sandbox_too(self):
        self.launch("--version")
        self.assertEqual(self.record.read_text().split(), ["run", "--version"])

    def test_environment_variable_cannot_turn_the_sandbox_off(self):
        self.assertEqual(self.launch(OPENCODE_SANDBOX="off").returncode, 0)
        self.assertTrue(self.record.exists())

    def test_the_launcher_runs_nothing_but_the_sandbox_command(self):
        """The model is the app's choice (VLLM_MODEL); no picker, no prompt, nothing interactive."""
        self.assertEqual(self.launch(AGENT_MODEL="nvidia/fixed").returncode, 0)
        self.assertEqual(self.record.read_text().split(), ["run"])

    def test_the_feature_installs_no_unsandboxed_opencode(self):
        install = (FEATURE / "install.sh").read_text()
        self.assertNotIn("opencode.ai/install", install)
        self.assertIn("/usr/local/bin/opencode", install)


if __name__ == "__main__":
    unittest.main()
