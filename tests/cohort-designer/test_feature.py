"""The cohort-designer feature: how it fetches the designer's binary, its catalog, the config the
binary writes (with COHORT_DESIGNER_BIN set to a binary), the policy and harness configuration
rendered from the catalog, and the app's wiring."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FEATURES = REPO / "features" / "src"
FEATURE = FEATURES / "cohort-designer"
APP = REPO / "src" / "ai-research-assistant"
AI_POLICY = FEATURES / "ai-policy"
SANDBOX = FEATURES / "agent-sandbox"
HARNESS = FEATURES / "opencode-harness" / "harnesses"
URL = "http://host.openshell.internal:9243/mcp"
RESOURCES = [
    {"resourceType": "BQ_DATASET", "projectId": "wb-data-1234", "datasetId": "omop"},
    {"resourceType": "BQ_DATASET", "projectId": "wb-data-1234", "datasetId": "omop"},
    {"resourceType": "BQ_DATASET", "projectId": "wb-work-5678", "datasetId": "scratch_1"},
    {"resourceType": "GCS_BUCKET", "bucketName": "a-bucket"},
    {"resourceType": "BQ_DATASET", "projectId": "bad project", "datasetId": "x"},
]


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = yaml.safe_load((FEATURE / "sandbox" / "cohort.yaml").read_text())

    def test_the_catalog_lists_exactly_the_tools_the_server_offers(self):
        """The release's tools/list (0.1.0): the designer's own, with wait_for_reply and
        new_cohort added and reset_session, read_events and get_choices withheld."""
        self.assertEqual(sorted(self.catalog["tools"]), sorted([
            "new_cohort", "send_message", "wait_for_reply", "get_status", "answer_choices",
            "respond_approval", "get_cohort_definition", "get_results"]))

    def test_the_person_is_asked_before_an_approval_and_an_answer_to_choices(self):
        self.assertEqual(self.catalog["ask"], ["respond_approval", "answer_choices"])
        for tool in self.catalog["tools"]:
            self.assertIn(f"`cohort_{tool}`", self.catalog["instructions"], tool)


class FetchTests(unittest.TestCase):
    """fetch-designer.sh installs a binary only when its sha256 matches."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, release, sha256, dest):
        return subprocess.run([str(FEATURE / "fetch-designer.sh"), release, sha256, str(dest)],
                              capture_output=True, text=True, check=False)

    def test_a_binary_already_there_with_the_right_sha256_is_kept(self):
        dest = self.dir / "bin" / "cohort-designer"
        dest.parent.mkdir()
        dest.write_bytes(b"designer")
        result = self.fetch("gs://nowhere/never", hashlib.sha256(b"designer").hexdigest(), dest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dest.read_bytes(), b"designer")

    def test_only_gs_and_https_releases_are_fetched(self):
        dest = self.dir / "cohort-designer"
        result = self.fetch("http://example.com/designer", "0" * 64, dest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be gs:// or https://", result.stderr)
        self.assertFalse(dest.exists())
        self.assertEqual(list(self.dir.iterdir()), [], "no partial download is left")

    def test_a_download_is_checked_before_it_is_installed(self):
        script = (FEATURE / "fetch-designer.sh").read_text()
        check, move = script.index('if [[ "${actual}" != "${SHA256}" ]]'), script.index('mv -f "${tmp}" "${DEST}"')
        self.assertLess(check, move)

    def test_every_download_has_a_time_limit_and_the_token_is_not_in_argv(self):
        script = (FEATURE / "fetch-designer.sh").read_text().replace("\\\n", " ")
        self.assertRegex(script, r"readonly TRANSFER=\(.*--connect-timeout 10 --max-time 900")
        downloads = [ln for ln in script.splitlines() if re.search(r"\bcurl\b.*-o \"\$\{tmp\}\"", ln)]
        self.assertEqual(len(downloads), 2)
        for line in downloads:
            self.assertIn('"${TRANSFER[@]}"', line)
        self.assertRegex(script, r"timeout 900 gcloud storage cp")
        self.assertNotRegex(script, r"-H [\"']Authorization")

    def test_the_feature_and_install_sh_pin_the_same_release(self):
        options = json.loads((FEATURE / "devcontainer-feature.json").read_text())["options"]
        install = (FEATURE / "install.sh").read_text()
        self.assertIn(f'readonly RELEASE="${{RELEASE:-"{options["release"]["default"]}"}}"', install)
        self.assertIn(f'readonly SHA256="${{SHA256:-"{options["sha256"]["default"]}"}}"', install)
        self.assertRegex(options["sha256"]["default"], r"^[0-9a-f]{64}$")

    def test_no_designer_source_is_in_the_repository(self):
        for name in ("app", "serve.py", "make-config.py", "requirements.txt"):
            self.assertFalse((FEATURE / name).exists(), name)


@unittest.skipUnless(os.environ.get("COHORT_DESIGNER_BIN"), "set COHORT_DESIGNER_BIN to a designer binary")
class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, resources, *extra):
        (self.dir / "resources.json").write_text(json.dumps(resources))
        env = {k: v for k, v in os.environ.items() if k != "GOOGLE_CLOUD_PROJECT"}
        return subprocess.run(
            [os.environ["COHORT_DESIGNER_BIN"], "make-config", str(self.dir / "config.yaml"), "--model", "nvidia/model",
             "--base-url", "http://127.0.0.1:8000/v1", "--resources", str(self.dir / "resources.json"),
             "--project", "wb-work-5678", *extra], capture_output=True, text=True, check=False, env=env)

    def test_the_designer_runs_on_the_local_model_and_reads_the_workspaces_datasets(self):
        result = self.make(RESOURCES)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = yaml.safe_load((self.dir / "config.yaml").read_text())
        self.assertEqual((config["provider"], config["model"], config["base_url"]),
                         ("openai_compatible", "nvidia/model", "http://127.0.0.1:8000/v1"))
        self.assertEqual(config["allowed_datasets"], "wb-data-1234.omop,wb-work-5678.scratch_1")
        self.assertEqual(config["bigquery_execution_project"], "wb-work-5678")
        self.assertEqual(config["approval"], "confirm", "an approval waits for the driver, which asks the person")

    def test_the_reply_and_history_budgets_follow_the_context_length(self):
        self.make(RESOURCES, "--context", "262144")
        wide = yaml.safe_load((self.dir / "config.yaml").read_text())
        self.make(RESOURCES, "--context", "65536")
        narrow = yaml.safe_load((self.dir / "config.yaml").read_text())
        self.assertEqual((wide["sampling"]["max_tokens"], wide["sampling"]["thinking_token_budget"]), (32768, 16384),
                         "the author's own budgets where the context holds them")
        self.assertEqual((narrow["sampling"]["max_tokens"], narrow["sampling"]["thinking_token_budget"]), (8192, 4096))
        self.assertEqual(wide["history_chars"], 500000)
        self.assertEqual(narrow["history_chars"], 20000)
        self.assertEqual(wide["max_commands_per_call"], 6)
        self.assertEqual(wide["card_folder"], "cards", "beside the config, where the user can write")

    def test_the_datasets_can_be_narrowed_but_not_widened(self):
        self.assertEqual(self.make(RESOURCES, "--datasets", "wb-work-5678.scratch_1").returncode, 0)
        self.assertEqual(yaml.safe_load((self.dir / "config.yaml").read_text())["allowed_datasets"], "wb-work-5678.scratch_1")
        result = self.make(RESOURCES, "--datasets", "other-project.secret")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not list", result.stderr)

    def test_on_gemini_the_designer_gets_its_own_provider_and_no_endpoint_keys(self):
        result = self.make(RESOURCES, "--provider", "gemini")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = yaml.safe_load((self.dir / "config.yaml").read_text())
        self.assertEqual({k: config[k] for k in ("provider", "model", "project", "region")},
                         {"provider": "gemini", "model": "nvidia/model", "project": "wb-work-5678", "region": "global"})
        # The designer's startup.ENDPOINT_KEYS: what its Gemini provider refuses.
        ENDPOINT_KEYS = ("base_url", "credential", "sampling", "tool_choice", "request_limit",
                         "history_chars", "tool_retries")
        self.assertFalse(set(ENDPOINT_KEYS) & set(config), "the Gemini provider refuses them")
        self.assertEqual((config["max_commands_per_call"], config["approval"]), (6, "confirm"))

    def test_no_dataset_is_no_config(self):
        result = self.make([RESOURCES[3]])
        self.assertEqual(result.returncode, 3)
        self.assertFalse((self.dir / "config.yaml").exists())


class SandboxTests(unittest.TestCase):
    """The catalog through the policy compiler and the OpenCode config hook."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        harness = subprocess.run([sys.executable, str(SANDBOX / "harness.py"), str(HARNESS / "opencode.yaml")],
                                 capture_output=True, text=True, check=True)
        (self.dir / "harness.json").write_text(harness.stdout)

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, tools, *extra):
        (self.dir / "ai.yaml").write_text(yaml.safe_dump({"version": 1, "data": {"read": "none", "write": "none"}, "tools": tools}))
        env = {k: v for k, v in os.environ.items() if k not in ("GOOGLE_CLOUD_PROJECT", "AGENT_DATA_CREDENTIAL")}
        args = [sys.executable, str(AI_POLICY / "render-policy.py"), str(SANDBOX / "config" / "policy.yaml"), str(self.dir / "ai.yaml"),
                "--harness", str(self.dir / "harness.json"), "--summary", str(self.dir / "summary.json"),
                "--tools", str(SANDBOX / "tool-groups.yaml"), "--mcp-url", "http://host.openshell.internal:9242",
                "--server", "cohort", URL, str(FEATURE / "sandbox" / "cohort.yaml"), *extra]
        return subprocess.run(args, capture_output=True, text=True, check=False, env=env)

    def rendered(self, tools):
        result = self.render(tools)
        self.assertEqual(result.returncode, 0, result.stderr)
        return yaml.safe_load(result.stdout), json.loads((self.dir / "summary.json").read_text())

    def test_the_designer_gets_its_own_rule_beside_the_workbench_tools(self):
        shipped = yaml.safe_load((SANDBOX / "config" / "ai-policy.yaml").read_text())["tools"]
        policy, summary = self.rendered(shipped)
        self.assertIn("workbench_tools", policy["network_policies"])
        rule = policy["network_policies"]["mcp_cohort"]
        endpoint = rule["endpoints"][0]
        self.assertEqual((endpoint["host"], endpoint["port"], endpoint["protocol"], endpoint["enforcement"]),
                         ("host.openshell.internal", 9243, "mcp", "enforce"))
        calls = [r["allow"]["tool"]["any"] for r in endpoint["rules"] if r["allow"]["method"] == "tools/call"]
        self.assertEqual(len(calls[0]), 8)
        self.assertEqual(rule["binaries"], policy["network_policies"]["workbench_tools"]["binaries"])
        self.assertEqual(summary["servers"][0]["ask"], ["respond_approval", "answer_choices"])

    def test_the_policy_can_deny_one_of_its_tools_or_all_tools(self):
        policy, summary = self.rendered({"allow": "all", "deny": ["respond_approval"]})
        endpoint = policy["network_policies"]["mcp_cohort"]["endpoints"][0]
        self.assertEqual(endpoint["deny_rules"], [{"method": "tools/call", "tool": "respond_approval"}])
        self.assertEqual(summary["servers"][0]["ask"], ["answer_choices"], "a denied tool is not asked about")
        policy, summary = self.rendered({"allow": "none"})
        self.assertNotIn("mcp_cohort", policy["network_policies"])
        self.assertEqual(summary["servers"], [])

    def test_a_catalog_of_another_server_is_refused(self):
        result = self.render({"allow": "all"}, "--server", "other", URL, str(FEATURE / "sandbox" / "cohort.yaml"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not of 'other'", result.stderr)

    def test_opencode_registers_the_designer_and_asks_before_an_approval(self):
        self.rendered({"allow": "all", "deny": ["wb_execute", "get_results"]})
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_")}
        env.update({"AGENT_MODEL": "nvidia/model", "MODEL_BASE_URL": "http://host.openshell.internal:8000/v1",
                    "AGENT_CONTEXT_LENGTH": "65536", "AGENT_MCP_URL": "http://host.openshell.internal:9242",
                    "AGENT_POLICY_SUMMARY": str(self.dir / "summary.json")})
        result = subprocess.run([str(HARNESS / "opencode-config.sh")], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        self.assertEqual(config["mcp"]["cohort"], {"type": "remote", "url": URL, "enabled": True})
        self.assertIn("wb", config["mcp"])
        self.assertEqual(config["permission"], {"webfetch": "deny", "external_directory": "allow",
                                                "cohort_respond_approval": "ask", "cohort_answer_choices": "ask",
                                                "wb_workflow_create": "ask", "wb_workflow_job_run": "ask",
                                                "wb_workflow_job_cancel": "ask"})
        self.assertIs(config["tools"]["cohort_get_results"], False)
        self.assertIs(config["tools"]["wb_wb_execute"], False)


class AppTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())

    def test_the_sandbox_reaches_the_designer_on_a_published_loopback_port(self):
        self.assertIn("127.0.0.1:9243:9243", self.compose["services"]["app"]["ports"])
        for service in ("app", "sandbox-broker"):
            self.assertIn(f"cohort={URL}", self.compose["services"][service]["environment"]["AGENT_MCP_SERVERS"].split(), service)
        self.assertIn("AGENT_MCP_SERVERS", (SANDBOX / "broker" / "entrypoint.sh").read_text())
        feature = json.loads((APP / ".devcontainer.json").read_text())["features"]["./.devcontainer/features/cohort-designer"]
        self.assertEqual(feature, {"username": "abc", "userHomeDir": "/config", "bindAddress": "0.0.0.0"})

    def test_the_broker_image_carries_the_catalog_and_not_the_designer(self):
        dockerfile = (APP / "broker" / "Dockerfile").read_text()
        self.assertIn("COPY .devcontainer/features/cohort-designer/sandbox ", dockerfile)
        self.assertIn("ROLE=broker bash /tmp/features/cohort-designer/install.sh", dockerfile)
        self.assertNotIn("fetch-designer", dockerfile)

    def test_stop_returns_only_once_the_designer_has_exited(self):
        """start-server.sh starts nothing while the old process is there, so a stop that returned
        at once left no designer running after `stop-server.sh && start-server.sh`."""
        install = (FEATURE / "install.sh").read_text()
        stop = install[install.index('cat > "${INSTALL_DIR}/stop-server.sh" <<STOP'):]
        stop = stop[:stop.index("\nSTOP\n")]
        kill, wait = stop.index('pkill -f "bin/cohort-designer serve --config"'), stop.index("for _ in")
        self.assertLess(kill, wait)
        self.assertIn('if ! pgrep -f "bin/cohort-designer serve --config" > /dev/null; then\n    echo "Stopped the cohort designer."', stop[wait:])
        self.assertIn("exit 1", stop[wait:], "a designer that will not exit is said, not passed over")
        self.assertIn('readonly RUNNING="bin/cohort-designer serve --config"', install)
        self.assertIn('if pgrep -f "\\${RUNNING}" > /dev/null; then\n  echo "The cohort designer is already running."', install)

    def test_the_app_names_no_dataset_and_the_setting_still_reaches_the_designer(self):
        env = self.compose["services"]["app"]["environment"]
        self.assertEqual(env["COHORT_DESIGNER_DATASETS"], "")
        start = (APP / "start-services.sh").read_text()
        self.assertRegex(start, r"--preserve-env=[A-Z_,]*COHORT_DESIGNER_DATASETS[A-Z_,]* \\\n +env VLLM_MODEL=")
        self.assertIn('\\${COHORT_DESIGNER_DATASETS:+--datasets "\\${COHORT_DESIGNER_DATASETS}"}', (FEATURE / "install.sh").read_text())

    def test_the_designer_starts_after_the_model_as_the_user(self):
        start = (APP / "start-services.sh").read_text()
        self.assertLess(start.index("/opt/vllm-model/start-vllm.sh"), start.index("/opt/cohort-designer/start-server.sh"))
        install = (FEATURE / "install.sh").read_text()
        self.assertIn('readonly INSTALL_DIR="/opt/cohort-designer"', install)
        self.assertIn('cat > "${INSTALL_DIR}/start-server.sh"', install)
        self.assertIn("--preserve-env=VLLM_PORT,VLLM_CONTEXT_LENGTH", start)
        self.assertIn('env VLLM_MODEL="${VLLM_MODEL}" COHORT_DESIGNER_PROVIDER=', start)
        self.assertIn('/opt/cohort-designer/start-server.sh; then', start)



if __name__ == "__main__":
    unittest.main()
