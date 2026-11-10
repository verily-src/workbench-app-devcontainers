"""Static checks on the agent-sandbox feature: what its scripts reference exists, and the broker
exposes only the fixed command set."""
import re
import subprocess
import unittest
from pathlib import Path

FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"
SANDBOX = FEATURES / "agent-sandbox"
INSTALL_DIR = "/opt/agent-sandbox"


class ScriptTests(unittest.TestCase):
    def test_scripts_parse(self):
        for script in [*SANDBOX.glob("*.sh"), *(SANDBOX / "broker").glob("*.sh")]:
            result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, f"{script}: {result.stderr}")

    def test_everything_agent_sandbox_reads_from_its_folder_ships_with_the_feature(self):
        text = (SANDBOX / "agent-sandbox.sh").read_text()
        for match in re.finditer(r"\$\{SCRIPT_DIR\}/([A-Za-z0-9_./-]+)", text):
            if match.group(1) == "harnesses":
                continue  # filled by harness features at install time
            self.assertTrue((SANDBOX / match.group(1)).exists(), match.group(1))
        # The config folder's files, by the names the script uses.
        for name in ("policy.yaml", "ai-policy.yaml", "google-cloud-profile.yaml"):
            self.assertIn(f'"${{CONFIG_DIR}}/{name}"', text)
            self.assertTrue((SANDBOX / "config" / name).exists(), name)
        self.assertEqual({p.name for p in (SANDBOX / "config").iterdir()}, {"policy.yaml", "ai-policy.yaml", "google-cloud-profile.yaml"})
        for name in ("tool-groups.yaml", "selftest.sh"):
            self.assertIn(name, (SANDBOX / "install.sh").read_text(), name)
        self.assertIn('source "${SCRIPT_DIR}/selftest.sh"', text)
        self.assertIn("run_selftest() {", (SANDBOX / "selftest.sh").read_text())

    def test_the_broker_files_name_the_installed_paths(self):
        sshd = (SANDBOX / "broker" / "sshd_config").read_text()
        for key in ("AuthorizedKeysCommand", "ForceCommand"):
            path = re.search(rf"^{key} ({INSTALL_DIR}/\S+)", sshd, re.M).group(1)
            self.assertTrue((SANDBOX / Path(path).relative_to(INSTALL_DIR)).exists(), path)
        entrypoint = (SANDBOX / "broker" / "entrypoint.sh").read_text()
        for path in re.findall(rf"{INSTALL_DIR}/[A-Za-z0-9_./-]+", entrypoint):
            self.assertTrue((SANDBOX / Path(path).relative_to(INSTALL_DIR)).exists(), path)

    def test_the_broker_allows_only_the_sandbox_commands(self):
        command = (SANDBOX / "broker" / "command.sh").read_text()
        allow = re.search(r"^\s*(run\|[^)]*)\)", command, re.M).group(1).split("|")
        for name in ("run", "shell", "exec", "upload", "download", "status", "web", "policy", "logs",
                     "reset", "selftest", "credential"):
            self.assertIn(name, allow)
        # No way to widen the policy from the app: no rule approval, no harness switching.
        for name in ("own", "approve", "reject", "rules", "harness"):
            self.assertNotIn(name, allow)
        # The client cannot choose the policy files or the model command.
        self.assertIn("unset AGENT_SANDBOX_CONFIG AGENT_MODEL AGENT_MODEL_COMMAND", command)

    def test_python_loads_no_code_from_the_users_home(self):
        """The broker runs with the user's home as HOME and working directory; the app can write both."""
        script = (SANDBOX / "agent-sandbox.sh").read_text()
        self.assertIn("export PYTHONNOUSERSITE=1", script)
        inline = [line for line in script.splitlines() if "python3 -c" in line and not line.lstrip().startswith("#")]
        self.assertTrue(inline)
        for line in inline:
            self.assertIn("(cd / && python3 -c", line)

    def test_the_gateway_gets_the_renders_own_policy_file(self):
        """Never the copy in the user's home, which the app could swap before the gateway reads it."""
        script = (SANDBOX / "agent-sandbox.sh").read_text()
        self.assertIn('RENDER_DIR="$(mktemp -d)"', script)
        self.assertIn('chmod -R a-w "${RENDER_DIR}"', script)
        self.assertEqual(script.count('--policy "${RENDERED_POLICY}"'), 2)
        self.assertNotIn('--policy "${EFFECTIVE_POLICY}"', script)

    def test_the_sandbox_contract_is_documented_in_the_script_header(self):
        header = (SANDBOX / "agent-sandbox.sh").read_text().split("set -o errexit")[0]
        for name in ("APP_USER_HOME", "AGENT_BROKER", "AGENT_MODEL_URL", "AGENT_MODEL", "AGENT_CONTEXT_LENGTH",
                     "AGENT_MCP_URL", "AGENT_SANDBOX_CONFIG"):
            self.assertIn(name, header)


if __name__ == "__main__":
    unittest.main()
