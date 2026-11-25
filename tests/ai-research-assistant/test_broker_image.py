"""The template's wiring of the features: the broker image, the sandbox image, the compose
environment the features read, and the devcontainer's feature list."""
import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "src" / "ai-research-assistant"
FEATURES = ROOT / "features" / "src"


class TemplateWiringTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())
        self.devcontainer = json.loads((APP / ".devcontainer.json").read_text())

    def test_the_devcontainer_installs_the_four_features_and_opens_the_mcp_server(self):
        features = self.devcontainer["features"]
        for name in ("vllm-model", "ai-policy", "agent-sandbox", "opencode-harness", "wb-mcp-server"):
            self.assertIn(f"./.devcontainer/features/{name}", features, name)
            self.assertTrue((FEATURES / name / "install.sh").exists(), name)
        for name in ("vllm-model", "agent-sandbox", "opencode-harness"):
            self.assertEqual(features[f"./.devcontainer/features/{name}"], {"username": "abc", "userHomeDir": "/config"})
        self.assertEqual(features["./.devcontainer/features/wb-mcp-server"]["bindAddress"], "0.0.0.0")
        self.assertEqual(features["./.devcontainer/features/wb-mcp-server"]["toolsets"], "core,workflows,docs",
                         "the agent is offered the workflow and documentation tools")

    def test_the_broker_image_is_built_from_the_features(self):
        dockerfile = (APP / "broker" / "Dockerfile").read_text()
        for name in ("ai-policy", "agent-sandbox", "opencode-harness"):
            self.assertIn(f"COPY .devcontainer/features/{name} /tmp/features/{name}", dockerfile)
            self.assertIn(f"/tmp/features/{name}/install.sh", dockerfile)
        self.assertIn("ROLE=broker", dockerfile)
        self.assertIn("INSTALLLAUNCHER=false", dockerfile)
        self.assertIn('ENTRYPOINT ["/opt/agent-sandbox/broker/entrypoint.sh"]', dockerfile)
        self.assertEqual(self.compose["services"]["sandbox-broker"]["build"]["dockerfile"], "broker/Dockerfile")

    def test_the_broker_entrypoint_writes_nothing_in_the_shared_home_as_root(self):
        """/config belongs to the app's user: a link planted there must not make root write or chown
        another file. What the entrypoint puts there, abc writes."""
        entrypoint = (FEATURES / "agent-sandbox" / "broker" / "entrypoint.sh").read_text()
        for number, line in enumerate(entrypoint.splitlines(), 1):
            code = line
            if line.lstrip().startswith("#") or ("/config" not in code and "${status" not in code):
                continue
            as_abc = "su -s /bin/sh abc -c" in code
            if re.search(r"\bchown\b(?!\s+-\S*h)", code):
                self.fail(f"entrypoint.sh:{number}: chown without -h on a /config path: {line}")
            if not as_abc and re.search(r"(>>?|\btee\b)\s*\"?(/config|\$\{status)", code):
                self.fail(f"entrypoint.sh:{number}: root writes into /config: {line}")
        self.assertIn("su -s /bin/sh abc -c 'mkdir -p /config/openshell && rm -f /config/openshell/broker-status.txt", entrypoint)

    def test_the_sandbox_image_is_the_harness_features(self):
        build = self.compose["services"]["sandbox-image"]["build"]
        self.assertEqual(build["context"], ".")
        self.assertTrue((FEATURES / build["dockerfile"][len(".devcontainer/features/"):]).exists(), build["dockerfile"])
        harness = yaml.safe_load((FEATURES / "opencode-harness" / "harnesses" / "opencode.yaml").read_text())
        self.assertEqual(self.compose["services"]["sandbox-image"]["image"], harness["image"])

    def test_the_sandbox_reaches_the_model_and_the_tools_on_the_published_loopback_ports(self):
        app = self.compose["services"]["app"]
        broker = self.compose["services"]["sandbox-broker"]
        published = {str(p) for p in app["ports"]}
        for env in (app["environment"], broker["environment"]):
            model_port = re.search(r"host\.openshell\.internal:(\d+)/v1$", env["AGENT_MODEL_URL"]).group(1)
            mcp_port = re.search(r"host\.openshell\.internal:(\d+)$", env["AGENT_MCP_URL"]).group(1)
            self.assertIn(f"127.0.0.1:{model_port}:{app['environment']['VLLM_PORT']}", published)
            self.assertIn(f"127.0.0.1:{mcp_port}:{mcp_port}", published)
        self.assertEqual(str(broker["environment"]["AGENT_CONTEXT_LENGTH"]), str(app["environment"]["VLLM_CONTEXT_LENGTH"]))
        self.assertEqual(app["environment"]["AGENT_BROKER"], "sandbox-broker")
        self.assertEqual(app["environment"]["AGENT_MODEL_COMMAND"], "/opt/ai-policy/access.py model-name --state /config/.ara/access.json")
        self.assertNotIn("AGENT_BROKER", broker["environment"], "the broker runs the commands itself")

    def test_the_endpoint_is_looked_up_only_for_a_person_with_the_vertex_model_feature(self):
        """Beta runs only on the app's own GPUs: no Vertex AI call is made for them at all."""
        start = (APP / "start-services.sh").read_text()
        lookup = start.index("python3 /opt/vertex-model/proxy.py find-endpoint")
        guard = start.rindex("if [[", 0, lookup)
        self.assertIn("feature_on vertex_model; then", start[guard:lookup])

    def test_no_coding_assistant_cli_is_installed(self):
        """The app's agent is the sandboxed one; an unsandboxed coding CLI beside it is not offered."""
        features = " ".join(self.devcontainer["features"])
        for name in ("claude-code", "gemini-cli", "llm-context"):
            self.assertNotIn(name, features)

    def test_start_services_runs_what_the_features_install(self):
        start = (APP / "start-services.sh").read_text()
        for path in ("/opt/wb-mcp-server/start-server.sh", "/opt/vllm-model/start-vllm.sh"):
            self.assertIn(path, start)
        self.assertIn("agent-sandbox web", start)
        self.assertIn("AGENT_MODEL_COMMAND", start, "the model command must survive sudo")
        for stale in ("OPENCODE_HOME", "/opt/opencode-workbench", "AGENT_POLICY_SOURCE"):
            self.assertNotIn(stale, start)
        # Every VLLM_* setting in compose reaches start-vllm.sh through --preserve-env.
        preserved = set(re.search(r"--preserve-env=(APP_USER_HOME[A-Z_,]+)", start).group(1).split(","))
        for name in self.compose["services"]["app"]["environment"]:
            if name.startswith("VLLM_"):
                self.assertIn(name, preserved, name)

    def test_the_app_image_has_no_framework_of_its_own(self):
        dockerfile = (APP / "Dockerfile").read_text()
        for stale in ("opencode.ai/install", "/opt/opencode-workbench", "openshell.tar.gz", "vllm[runai]", "/opt/vllm", "COPY "):
            self.assertNotIn(stale, dockerfile, stale)
        for folder in ("openshell/harnesses", "sandbox-image", "broker/command.sh", "agent-sandbox.sh", "start-vllm.sh"):
            self.assertFalse((APP / folder).exists(), folder)



class AccessWiringTests(unittest.TestCase):
    """The access state: written in the app, read by the broker and the assistant UI."""

    compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())

    def test_the_app_writes_the_state_and_the_broker_reads_it(self):
        app = self.compose["services"]["app"]
        broker = self.compose["services"]["sandbox-broker"]
        self.assertIn("ara-access:/config/.ara", app["volumes"])
        self.assertIn("ara-access:/config/.ara:ro", broker["volumes"])
        self.assertIn("ara-access", self.compose["volumes"])
        for env in (app["environment"], broker["environment"]):
            self.assertEqual(env["AGENT_ACCESS_STATE"], "/config/.ara/access.json")
        self.assertNotIn("ARA_ALPHA_GROUP", app["environment"])
        self.assertNotIn("ARA_BETA_GROUP", app["environment"])
        entrypoint = (FEATURES / "agent-sandbox" / "broker" / "entrypoint.sh").read_text()
        self.assertIn("AGENT_ACCESS_STATE", entrypoint, "sshd sessions get the broker's environment only through this list")

    def test_start_services_checks_access_before_starting_the_assistant(self):
        start = (APP / "start-services.sh").read_text()
        # By env, not --preserve-env: sudo's pam_env rereads /etc/environment after the latter.
        self.assertNotIn("ARA_ALPHA_GROUP", start)
        self.assertIn("resolve --config-dir /opt/agent-sandbox/config", start)
        self.assertLess(start.index("check_access || access_rc=$?"), start.rindex("start_once"))
        self.assertIn("if feature_on cohort_designer && ! sudo", start)
        self.assertIn("if feature_on kumo_forecast && ! sudo", start)
        # The sandbox is created inside start_assistant only.
        body = start[start.index("start_assistant() {"):start.index("\n}\n", start.index("start_assistant() {"))]
        self.assertIn("agent-sandbox web", body)
        self.assertEqual(start.count("agent-sandbox web"), 2, "once in the call, once in the hint")

    def run_access_block(self, answers, runs=1, start_rc=0, expect_rc=0):
        """Runs start-services.sh's access block with check_access answering `answers` in turn
        (exit code, tier) and start_assistant only logging, then returning `start_rc`; returns the
        log once it settles. self.tmp is the run's directory."""
        import subprocess
        import tempfile
        import time
        start = (APP / "start-services.sh").read_text()
        block = start[start.index("admitted() {"):]
        tmp = self.tmp = Path(tempfile.mkdtemp())
        script = tmp / "run.sh"
        script.write_text(
            "set -o errexit -o nounset -o pipefail\n"
            f"ACCESS_STATE={tmp}/access.json USER_HOME_DIR={tmp} USER_NAME=abc ACCESS=access.py n=0\n"
            f"answers=({' '.join(f'{rc}:{tier}' for rc, tier in answers)})\n"
            "check_access() {\n"
            "  local a=${answers[$n]:-${answers[-1]}}; n=$((n + 1))\n"
            "  local tier=${a#*:}\n"
            "  if [[ -n $tier ]]; then echo \"{\\\"status\\\":\\\"ok\\\",\\\"tier\\\":\\\"$tier\\\"}\" > \"$ACCESS_STATE\"\n"
            "  else echo '{\"status\":\"ok\",\"tier\":null,\"message\":\"in beta\"}' > \"$ACCESS_STATE\"; fi\n"
            "  return ${a%%:*}\n"
            "}\n"
            f"start_assistant() {{ echo STARTED >> {tmp}/started; return {start_rc}; }}\n"
            f"sudo() {{ echo \"sudo $*\" >> {tmp}/sudo; }}\n"
            + block)
        env = {"PATH": "/usr/bin:/bin", "ACCESS_RECHECK_SECONDS": "0.1", "ACCESS_RETRY_SECONDS": "0.1",
               "START_MARKERS": str(tmp / "markers" / "ara-start")}
        for _ in range(runs):
            result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, expect_rc, result.stderr)
        self.stdout = result.stdout
        log = tmp / "ai-research-assistant-access.log"
        if "Rechecking access" in result.stderr:  # the background loop: wait for it to start the assistant
            deadline = time.time() + 10
            while time.time() < deadline and not (tmp / "started").exists():
                time.sleep(0.1)
            time.sleep(0.3)
        started = (tmp / "started").read_text() if (tmp / "started").exists() else ""
        return started, result.stderr, log.read_text() if log.exists() else ""

    def test_an_admitted_person_gets_the_assistant_at_once(self):
        started, err, log = self.run_access_block([(0, "alpha")])
        self.assertEqual(started, "STARTED\n")
        self.assertEqual(log, "")

    def test_someone_added_to_a_group_later_gets_the_assistant_without_a_restart(self):
        started, err, log = self.run_access_block([(0, ""), (0, ""), (2, ""), (0, "beta")])
        self.assertIn("in beta", err)
        self.assertEqual(started, "STARTED\n", "started once, after the recheck admitted them")
        self.assertIn("admitted as beta", log)

    def test_the_assistant_starts_once_per_boot(self):
        # postCreateCommand and postStartCommand both run the script on an app's first start.
        started, err, log = self.run_access_block([(0, "alpha")], runs=2)
        self.assertEqual(started, "STARTED\n")

    def test_the_once_per_boot_marker_is_in_a_directory_the_script_creates(self):
        started, err, log = self.run_access_block([(0, "alpha")], runs=2)
        self.assertEqual(started, "STARTED\n")
        self.assertIn("already started", self.stdout)
        self.assertTrue((self.tmp / "markers" / "ara-start" / "assistant-started").is_file())
        self.assertFalse((self.tmp / "access.json").parent.joinpath("assistant-started").exists(),
                         "not on the volume that outlives the container")

    def test_a_model_that_did_not_start_leaves_the_boot_unmarked_and_the_script_still_ends_well(self):
        started, err, log = self.run_access_block([(0, "alpha")], runs=2, start_rc=1, expect_rc=0)
        self.assertEqual(started, "STARTED\nSTARTED\n", "the second run tries again")
        self.assertIn("did not start", err)
        self.assertFalse((self.tmp / "markers" / "ara-start" / "assistant-started").exists())
        self.assertIn("model-failed", (self.tmp / "sudo").read_text(), "the page is told")

    def test_the_first_check_of_a_start_runs_without_the_last_states_admission(self):
        """A person removed from the group since the last start is not admitted while the check runs."""
        import subprocess
        import tempfile
        start = (APP / "start-services.sh").read_text()
        block = start[start.index("forget_old_access() {"):start.index("start_once() {")]
        tmp = Path(tempfile.mkdtemp())
        (tmp / "access.json").write_text('{"status":"ok","tier":"alpha"}')
        script = tmp / "run.sh"
        script.write_text(
            "set -o errexit -o nounset -o pipefail\n"
            f"ACCESS_STATE={tmp}/access.json LOCKS={tmp} RESOLVED={tmp}/resolved BOOT_ID=b1\n" + block
            + "forget_old_access\n"
            + f"[[ ! -e {tmp}/access.json ]] && echo gone\n"
            + f"echo new > {tmp}/access.json\n"
            + "forget_old_access\n"
            + f"[[ -e {tmp}/access.json ]] && echo kept\n")
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, timeout=30)
        self.assertEqual(result.stdout.split(), ["gone", "kept"], result.stderr)
        # The periodic rechecks never go through it.
        loop = start[start.index("Rechecking access in the background"):]
        self.assertNotIn("forget_old_access", loop)

    def test_the_local_model_probe_does_not_take_the_vertex_proxy_for_vllm(self):
        import subprocess
        start = (APP / "start-services.sh").read_text()
        match = re.search(r"jq -e --arg m \"\$\{VLLM_MODEL:-\}\" '([^']*)'", start)
        self.assertIsNotNone(match)
        listing = lambda owner: json.dumps({"data": [{"id": "m", "owned_by": owner}]})  # noqa: E731
        for owner, up in (("vllm", True), ("vertex-ai", False)):
            result = subprocess.run(["jq", "-e", "--arg", "m", "m", match.group(1)], input=listing(owner),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, up, owner)
        # An entry that names no owner is not the proxy.
        result = subprocess.run(["jq", "-e", "--arg", "m", "m", match.group(1)], input='{"data":[{"id":"m"}]}',
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)

    def test_an_unknown_or_missing_backend_is_a_failed_start(self):
        start = (APP / "start-services.sh").read_text()
        body = start[start.index("start_assistant() {"):start.index("\nreconnect_tools() {")]
        self.assertIn("could not choose a model", body)
        after_none = body[body.index("    none)"):]
        self.assertRegex(after_none, r"none\)\n.*\n +return 0\n +;;\n +\*\)\n.*\n +return 1")

    def test_two_runs_waiting_on_access_start_the_assistant_once(self):
        started, err, log = self.run_access_block([(0, ""), (0, ""), (0, "beta")], runs=2)
        self.assertEqual(started, "STARTED\n")

    def test_an_invalid_configuration_is_not_rechecked(self):
        started, err, log = self.run_access_block([(1, "")])
        self.assertEqual(started, "")
        self.assertIn("configuration is invalid", err)
        self.assertEqual(log, "")

    def test_start_services_reconnects_the_tools_opencode_marked_failed(self):
        start = (APP / "start-services.sh").read_text()
        body = start[start.index("start_assistant() {"):start.index("\nreconnect_tools() {")]
        self.assertLess(body.index("agent-sandbox web"), body.index("  reconnect_tools\n"))
        fn = start[start.index("reconnect_tools() {"):]
        self.assertIn('select(.value.status == "failed")', fn)
        for action in ("disconnect", "connect"):
            self.assertIn(f'"${{opencode}}/mcp/${{name}}/{action}"', fn)
        # The same OpenCode the assistant UI talks to.
        ui = self.compose["services"]["assistant-ui"]["environment"]["OPENCODE_URL"]
        self.assertIn(f'${{OPENCODE_URL:-{ui}}}', fn)

    def test_a_server_that_comes_up_late_is_reconnected(self):
        """On a restart Kumo listens minutes after the sandbox is back: one reconnect is too early."""
        import subprocess
        import tempfile
        start = (APP / "start-services.sh").read_text()
        fn = start[start.index("reconnect_tools() {"):start.index("\n}\n", start.index("reconnect_tools() {")) + 3]
        tmp = Path(tempfile.mkdtemp())
        # A fake curl: forecast stays failed until its third connect, wb is connected throughout.
        (tmp / "curl").write_text(
            "#!/bin/bash\n"
            f"state={tmp}/connects\n"
            'url="${@: -1}"\n'
            'n=$(cat "$state" 2>/dev/null || echo 0)\n'
            'case "$url" in\n'
            '  */mcp/forecast/connect) echo $((n + 1)) > "$state" ;;\n'
            '  */mcp) if (( n >= 3 )); then echo \'{"wb":{"status":"connected"},"forecast":{"status":"connected"}}\';\n'
            '         else echo \'{"wb":{"status":"connected"},"forecast":{"status":"failed"}}\'; fi ;;\n'
            'esac\n')
        (tmp / "curl").chmod(0o755)
        script = tmp / "run.sh"
        script.write_text("set -o errexit -o nounset -o pipefail\n" + fn + "reconnect_tools\n")
        env = {"PATH": f"{tmp}:/usr/bin:/bin", "RECONNECT_SECONDS": "0", "RECONNECT_ATTEMPTS": "5"}
        result = subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((tmp / "connects").read_text().strip(), "3", "retried until it connected, then stopped")
        self.assertIn("Reconnected the forecast tools", result.stdout)
        self.assertNotIn("wb", result.stdout + result.stderr, "a connected server is left alone")

    def test_agent_sandbox_refuses_a_person_the_state_does_not_admit(self):
        script = (FEATURES / "agent-sandbox" / "agent-sandbox.sh").read_text()
        ensure = script[script.index("ensure_policy() {"):]
        self.assertLess(ensure.index("check_access"), ensure.index("render-policy.py\" \""))
        self.assertIn('${ACCESS_STATE:+--access "${ACCESS_STATE}"}', script)


if __name__ == "__main__":
    unittest.main()
