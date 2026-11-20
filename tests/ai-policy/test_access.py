"""access.py: who may use the app (access.yaml, the person's Workbench groups) and which features
they get (features.yaml), and the model the app serves them."""
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"
AI_POLICY = FEATURES / "ai-policy"
CONFIG = FEATURES / "agent-sandbox" / "config"
sys.path.insert(0, str(AI_POLICY))

import access  # noqa: E402

ACCESS = {"version": 1, "org": "verily", "tiers": {"beta": {"group": "b-group"}, "alpha": {"group": "a-group"}}}
FEATURE_SET = {
    "cohort_designer": {"tier": "beta", "servers": ["cohort"], "tool_groups": []},
    "workflow_runs": {"tier": "beta", "servers": [], "tool_groups": ["workflows"]},
    "kumo_forecast": {"tier": "alpha", "servers": ["forecast"], "tool_groups": []},
    "vertex_model": {"tier": "alpha", "servers": [], "tool_groups": []},
}
H100 = "NVIDIA H100 80GB HBM3, 81559"


def groups(*names, roles=("MEMBER",), org="verily"):
    return [{"orgId": org, "name": n, "currentUserRoles": list(roles)} for n in names]


class ConfigTests(unittest.TestCase):
    def test_the_shipped_files_are_valid_and_name_what_the_app_has(self):
        servers = [yaml.safe_load(p.read_text())["name"] for p in FEATURES.glob("*/sandbox/*.yaml")
                   if "name" in (yaml.safe_load(p.read_text()) or {})]
        tool_groups = yaml.safe_load((FEATURES / "agent-sandbox" / "tool-groups.yaml").read_text())["groups"]
        found = access.read_access(access.load_yaml(CONFIG / "access.yaml"))
        self.assertEqual(set(found["groups"]), {"alpha", "beta"})
        features = access.read_features(access.load_yaml(CONFIG / "features.yaml"), servers, list(tool_groups))
        self.assertEqual({n: f["tier"] for n, f in features.items()},
                         {"cohort_designer": "beta", "workflow_runs": "beta", "kumo_forecast": "beta", "vertex_model": "alpha"})

    def test_the_environment_does_not_change_the_groups(self):
        import os
        old = {k: os.environ.get(k) for k in ("ARA_ALPHA_GROUP", "ARA_BETA_GROUP")}
        os.environ.update({"ARA_ALPHA_GROUP": "dev-alpha", "ARA_BETA_GROUP": "dev-beta"})
        try:
            self.assertEqual(access.read_access(ACCESS)["groups"]["alpha"], ACCESS["tiers"]["alpha"]["group"])
        finally:
            for k, v in old.items():
                os.environ.pop(k) if v is None else os.environ.__setitem__(k, v)

    def test_the_environment_does_not_change_which_config_is_read(self):
        """Without --config-dir, check and resolve read the image's files, whatever
        AGENT_SANDBOX_CONFIG says; the groups are fixed."""
        import contextlib
        import io
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            image, other = Path(tmp, "image"), Path(tmp, "other")
            for folder, group in ((image, "image-group"), (other, "env-group")):
                folder.mkdir()
                config = {**ACCESS, "tiers": {"beta": {"group": group}}}
                (folder / "access.yaml").write_text(yaml.safe_dump(config))
                (folder / "features.yaml").write_text((CONFIG / "features.yaml").read_text())
            state = Path(tmp, "state.json")
            with mock.patch.dict(os.environ, {"AGENT_SANDBOX_CONFIG": str(other)}), \
                    mock.patch.object(access, "DEFAULT_CONFIG", str(image)), \
                    mock.patch.object(access, "perimeter_of", lambda wb, timeout: ""):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(access.main(["check"]), 0)
                self.assertIn("image-group", out.getvalue())
                self.assertNotIn("env-group", out.getvalue())
                with contextlib.redirect_stdout(io.StringIO()):
                    access.main(["resolve", "--state", str(state), "--wb", str(Path(tmp, "no-wb"))])
                self.assertEqual(json.loads(state.read_text())["groups"], {"beta": "image-group"})
        result = subprocess.run([sys.executable, "-c", "import access; print(access.DEFAULT_CONFIG)"],
                                cwd=AI_POLICY, capture_output=True, text=True, check=True,
                                env={**os.environ, "AGENT_SANDBOX_CONFIG": "/elsewhere"})
        self.assertEqual(result.stdout.strip(), "/opt/agent-sandbox/config")

    def test_a_failed_model_start_is_recorded_as_no_model_with_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp, "state.json")
            state.write_text(json.dumps({"status": "ok", "tier": "beta",
                                         "model": {"backend": "vllm", "name": "m", "reason": "", "message": ""}}))
            self.assertEqual(access.main(["model-failed", "--state", str(state), "--message", "did not start"]), 0)
            written = json.loads(state.read_text())
            self.assertEqual((written["status"], written["tier"]), ("ok", "beta"))
            self.assertEqual((written["model"]["backend"], written["model"]["message"]), (None, "did not start"))
            self.assertEqual(access.main(["model-name", "--state", str(state)]), 1)

    def test_what_this_app_does_not_know_is_refused(self):
        for bad, message in (
                ({**ACCESS, "extra": 1}, "extra"),
                ({**ACCESS, "version": 2}, "version"),
                ({**ACCESS, "tiers": {"gamma": {"group": "g"}}}, "gamma"),
                ({**ACCESS, "tiers": {"beta": {"group": "b", "role": "x"}}}, "role"),
                ({**ACCESS, "tiers": {"beta": {"group": "has space"}}}, "group name"),
                ({**ACCESS, "tiers": {}}, "names no group")):
            with self.subTest(message), self.assertRaisesRegex(access.InvalidConfig, message):
                access.read_access(bad)
        for bad, message in (
                ({"version": 1, "features": {"x": {"tier": "gamma"}}}, "tier"),
                ({"version": 1, "features": {"x": {"tier": "beta", "env": {}}}}, "env"),
                ({"version": 1, "features": {"x": {"tier": "beta", "servers": ["nope"]}}}, "nope"),
                ({"version": 1, "features": {"Bad-Name": {"tier": "beta"}}}, "feature name")):
            with self.subTest(message), self.assertRaisesRegex(access.InvalidConfig, message):
                access.read_features(bad, known_servers=["cohort"])

    def test_check_validates_the_shipped_files(self):
        result = subprocess.run([sys.executable, str(AI_POLICY / "access.py"), "check", "--config-dir", str(CONFIG)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)


class TierTests(unittest.TestCase):
    access_config = access.read_access(ACCESS)

    def test_alpha_wins_and_either_group_admits(self):
        self.assertEqual(access.tier_of(groups("a-group", "b-group"), self.access_config), "alpha")
        self.assertEqual(access.tier_of(groups("a-group"), self.access_config), "alpha", "alpha does not need beta")
        self.assertEqual(access.tier_of(groups("b-group", "other"), self.access_config), "beta")
        self.assertIsNone(access.tier_of(groups("other"), self.access_config))
        self.assertIsNone(access.tier_of([], self.access_config))
        self.assertIsNone(access.tier_of(groups("a-group", org="elsewhere"), self.access_config),
                          "a same-named group in another org admits nobody")
        self.assertIsNone(access.tier_of([{"name": "a-group", "currentUserRoles": ["MEMBER"]}], self.access_config),
                          "nor does a group whose org is not given")

    def test_an_admin_counts_and_another_org_or_role_does_not(self):
        self.assertEqual(access.tier_of(groups("b-group", roles=["ADMIN"]), self.access_config), "beta")
        self.assertIsNone(access.tier_of(groups("b-group", roles=["SUPPORT"]), self.access_config))
        self.assertIsNone(access.tier_of(groups("b-group", org="elsewhere"), self.access_config))

    def test_flags_and_what_they_turn_off(self):
        beta = access.flags(FEATURE_SET, "beta")
        self.assertEqual(beta, {"cohort_designer": True, "workflow_runs": True, "kumo_forecast": False, "vertex_model": False})
        self.assertEqual(access.off_parts(FEATURE_SET, beta), {"servers": ["forecast"], "tool_groups": []})
        self.assertTrue(all(access.flags(FEATURE_SET, "alpha").values()))
        none = access.flags(FEATURE_SET, None)
        self.assertFalse(any(none.values()))
        self.assertEqual(access.off_parts(FEATURE_SET, none), {"servers": ["cohort", "forecast"], "tool_groups": ["workflows"]})

    def test_a_server_a_feature_that_is_on_needs_stays_on(self):
        features = {"a": {"tier": "beta", "servers": ["cohort"], "tool_groups": []},
                    "b": {"tier": "alpha", "servers": ["cohort"], "tool_groups": []}}
        self.assertEqual(access.off_parts(features, access.flags(features, "beta"))["servers"], [])


WORKSPACE = "101caec0-1473-4a8c-82f5-796930bd9741"
APP_WORKSPACE = "the-apps-workspace"
PERIMETER = [{"namespace": "terra", "name": "exfil-perimeter-constraint",
              "additionalData": [{"key": "perimeter-id", "value": "a-perimeter"}]}]


class FakeWorkspaceApi(BaseHTTPRequestHandler):
    """Workbench's workspace API: the app's workspace (APP_WORKSPACE) with its policies, 500 when
    policies is None, or `body` as it is when a test sets one."""
    policies = []
    body = None
    asked = []

    def do_GET(self):
        FakeWorkspaceApi.asked.append(self.path)
        if (self.path != f"/api/workspaces/v1/workspaceByUserFacingId/{APP_WORKSPACE}"
                or self.headers.get("Authorization") != "Bearer tok"):
            self.send_response(404)
            self.end_headers()
            return
        if FakeWorkspaceApi.policies is None:
            self.send_response(500)
            self.end_headers()
            return
        answer = FakeWorkspaceApi.body
        if answer is None:
            answer = {"id": WORKSPACE, "userFacingId": APP_WORKSPACE, "policies": FakeWorkspaceApi.policies}
        body = json.dumps(answer).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


# Runs access.py with the two lookups a test cannot make (the VM's metadata, Workbench's host)
# answered from the environment. access.py itself has no such switch.
RUNNER = """
import functools, os, sys
sys.path.insert(0, sys.argv[1])
import access
given = {k: os.environ[v] for k, v in (("api", "TEST_WORKSPACE_API"), ("workspace", "TEST_APP_WORKSPACE"))
         if os.environ.get(v)}
access.perimeter_of = functools.partial(access.perimeter_of, **given)
sys.exit(access.main(sys.argv[2:]))
"""


class ResolveTests(unittest.TestCase):
    """resolve with a fake wb and a fake workspace API, as the app runs it."""

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeWorkspaceApi)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeWorkspaceApi.policies = [{"namespace": "terra", "name": "group-constraint", "additionalData": []}]
        FakeWorkspaceApi.body = None
        FakeWorkspaceApi.asked = []
        self.home = None
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "config").mkdir()
        (self.dir / "config" / "access.yaml").write_text(yaml.safe_dump(ACCESS))
        (self.dir / "config" / "features.yaml").write_text((CONFIG / "features.yaml").read_text())
        self.state = self.dir / "ara" / "access.json"
        self.home = self.dir / "home"
        (self.home / ".workbench").mkdir(parents=True)
        # wb's current workspace is another one: the check must not follow it.
        (self.home / ".workbench" / "context.json").write_text(json.dumps({
            "workspace": {"uuid": WORKSPACE, "userFacingId": "another-workspace"},
            "server": {"workspaceManagerUri": "https://workbench.verily.com/api/wsm"}}))
        self.api = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.tmp.cleanup()

    def fake_wb(self, body):
        path = self.dir / "wb"
        auth = 'if [[ "$1 $2" == "auth print-access-token" ]]; then echo tok; exit 0; fi\n'
        path.write_text("#!/bin/bash\n" + auth + body + "\n")
        path.chmod(0o755)
        return path

    def resolve(self, body, *extra, env=None):
        wb = self.fake_wb(body)
        run_env = {k: v for k, v in os.environ.items() if not k.startswith("ARA_")}
        run_env["HOME"] = str(self.home)
        run_env.update({"TEST_WORKSPACE_API": self.api, "TEST_APP_WORKSPACE": APP_WORKSPACE})
        run_env.update(env or {})
        result = subprocess.run([sys.executable, "-c", RUNNER, str(AI_POLICY), "resolve", "--config-dir",
                                 str(self.dir / "config"), "--state", str(self.state), "--wb", str(wb), *extra],
                                capture_output=True, text=True, check=False, env=run_env)
        state = json.loads(self.state.read_text()) if self.state.exists() else None
        return result, state

    def answering(self, *names):
        return f"cat <<'EOF'\n{json.dumps(groups(*names))}\nEOF"

    def test_an_alpha_member_gets_every_feature(self):
        result, state = self.resolve(self.answering("a-group"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((state["status"], state["tier"], state["message"]), ("ok", "alpha", ""))
        self.assertTrue(all(state["features"].values()))
        self.assertEqual(state["off"], {"servers": [], "tool_groups": []})
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o644, "the UI container reads it as another user")

    def test_a_beta_member_gets_the_beta_features(self):
        _, state = self.resolve(self.answering("b-group"))
        self.assertEqual(state["tier"], "beta")
        self.assertEqual(state["off"], {"servers": [], "tool_groups": []})
        self.assertTrue(state["features"]["kumo_forecast"])
        self.assertFalse(state["features"]["vertex_model"])

    def test_inside_a_perimeter_gemini_is_off_even_for_alpha(self):
        FakeWorkspaceApi.policies = PERIMETER
        result, state = self.resolve(self.answering("a-group"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((state["tier"], state["perimeter"]), ("alpha", "a-perimeter"))
        self.assertFalse(state["features"]["vertex_model"])
        self.assertTrue(state["features"]["cohort_designer"] and state["features"]["kumo_forecast"])

    def test_when_the_perimeter_cannot_be_told_gemini_is_off(self):
        FakeWorkspaceApi.policies = None
        result, state = self.resolve(self.answering("a-group"))
        self.assertEqual((result.returncode, state["tier"], state["perimeter"]), (0, "alpha", None))
        self.assertIn("could not read the workspace's policies", state["perimeter_error"])
        self.assertFalse(state["features"]["vertex_model"])
        (self.home / ".workbench" / "context.json").unlink()
        _, state = self.resolve(self.answering("a-group"), env={"TEST_WORKSPACE_API": ""})
        self.assertFalse(state["features"]["vertex_model"])
        self.assertIn("no workspace API in wb's context", state["perimeter_error"])

    def test_the_perimeter_is_read_for_the_apps_workspace_not_wbs_current_one(self):
        FakeWorkspaceApi.policies = PERIMETER
        _, state = self.resolve(self.answering("a-group"))
        self.assertEqual(state["perimeter"], "a-perimeter")
        self.assertEqual(FakeWorkspaceApi.asked, [f"/api/workspaces/v1/workspaceByUserFacingId/{APP_WORKSPACE}"])

    def test_an_answer_that_is_not_the_workspace_and_its_policies_is_cannot_tell(self):
        answers = [{"id": WORKSPACE, "userFacingId": APP_WORKSPACE},
                   {"id": WORKSPACE, "userFacingId": APP_WORKSPACE, "policies": None},
                   {"id": WORKSPACE, "userFacingId": APP_WORKSPACE, "policies": {"namespace": "terra"}},
                   {"id": WORKSPACE, "userFacingId": APP_WORKSPACE, "policies": "terra/exfil-perimeter-constraint"},
                   {"id": WORKSPACE, "userFacingId": "another-workspace", "policies": []},
                   [], "ok"]
        for answer in answers:
            with self.subTest(answer=answer):
                FakeWorkspaceApi.body = answer
                _, state = self.resolve(self.answering("a-group"))
                self.assertIsNone(state["perimeter"])
                self.assertIn("unexpected answer", state["perimeter_error"])
                self.assertFalse(state["features"]["vertex_model"])

    def test_the_token_only_goes_to_workbench(self):
        for uri in (self.api, "https://evil.example.com", "https://workbench.verily.com:8443/api/wsm",
                    "http://workbench.verily.com/api/wsm"):
            with self.subTest(uri=uri):
                (self.home / ".workbench" / "context.json").write_text(json.dumps(
                    {"workspace": {"uuid": WORKSPACE}, "server": {"workspaceManagerUri": uri}}))
                _, state = self.resolve(self.answering("a-group"), env={"TEST_WORKSPACE_API": ""})
                self.assertIsNone(state["perimeter"])
                self.assertIn("not on workbench.verily.com", state["perimeter_error"])
                self.assertFalse(state["features"]["vertex_model"])
        self.assertEqual(FakeWorkspaceApi.asked, [])

    def test_a_vm_that_names_no_workspace_is_cannot_tell(self):
        _, state = self.resolve(self.answering("a-group"), env={"TEST_APP_WORKSPACE": "../x"})
        self.assertIsNone(state["perimeter"])
        self.assertFalse(state["features"]["vertex_model"])

    def test_a_kept_gemini_model_goes_when_the_workspace_is_in_a_perimeter(self):
        self.resolve(self.answering("a-group"))
        state = json.loads(self.state.read_text())
        state["model"] = {"backend": "vertex", "name": "gemini-x", "reason": "", "message": ""}
        self.state.write_text(json.dumps(state))
        FakeWorkspaceApi.policies = PERIMETER
        _, state = self.resolve(self.answering("a-group"))
        self.assertIsNone(state["model"]["backend"])

    def test_anyone_else_gets_the_beta_page(self):
        result, state = self.resolve(self.answering("other"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual((state["status"], state["tier"]), ("ok", None))
        self.assertIn("is in beta", state["message"])
        self.assertFalse(any(state["features"].values()))

    def test_the_environment_cannot_admit_anyone(self):
        _, state = self.resolve(self.answering("dev-alpha"), env={"ARA_ALPHA_GROUP": "dev-alpha"})
        self.assertIsNone(state["tier"])

    def test_wb_is_asked_for_the_configured_org_as_json(self):
        _, state = self.resolve('[[ "$*" == "group list --format=json --org=verily" ]] || exit 9\necho "[]"')
        self.assertEqual(state["status"], "ok")

    def test_a_check_that_cannot_be_made_fails_closed_and_says_so(self):
        for body, error in (("echo 'Not logged in' >&2; exit 1", "Not logged in"),
                            ("echo not-json", "JSON"),
                            ("sleep 5", "did not answer within 1 s")):
            with self.subTest(error):
                result, state = self.resolve(body, "--timeout", "1")
                self.assertEqual(result.returncode, 2)
                self.assertEqual((state["status"], state["tier"]), ("error", None))
                self.assertIn(error, state["error"])
                self.assertIn("couldn't verify", state["message"])
                self.assertFalse(any(state["features"].values()))

    def test_a_recheck_keeps_the_model_the_app_started(self):
        self.state.parent.mkdir(parents=True)
        vertex = {"backend": "vertex", "name": "gemini-3.5-flash", "reason": "r", "message": ""}
        access.write_state(self.state, {"status": "ok", "tier": "alpha", "model": vertex})
        _, state = self.resolve(self.answering("a-group"))
        self.assertEqual(state["model"], vertex)
        # Dropped to beta: Gemini is an alpha feature, so no model, and the page says why.
        _, state = self.resolve(self.answering("b-group"))
        self.assertIsNone(state["model"]["backend"])
        self.assertIn("GPU setup", state["model"]["message"])
        vllm = {"backend": "vllm", "name": "nvidia/super", "reason": "r", "message": ""}
        access.write_state(self.state, {"status": "ok", "tier": "alpha", "model": vllm})
        _, state = self.resolve(self.answering("b-group"))
        self.assertEqual(state["model"], vllm, "the local model is everyone's")

    def test_an_invalid_configuration_writes_an_error_state(self):
        (self.dir / "config" / "access.yaml").write_text("version: 1\norg: verily\ntiers: {gamma: {group: g}}\n")
        result, state = self.resolve(self.answering("a-group"))
        self.assertEqual(result.returncode, 1)
        self.assertEqual((state["status"], state["tier"]), ("error", None))
        self.assertIn("gamma", state["error"])


class ModelTests(unittest.TestCase):
    alpha = {"features": {"vertex_model": True}}
    beta = {"features": {"vertex_model": False}}

    def choose(self, state, gpus="", vllm_up=False, vertex="gemini-3.5-flash", endpoint=""):
        return access.choose_model(state, access.gpus_from_csv(gpus), vllm_up, vertex, "nvidia/super",
                                   endpoint)

    def test_without_the_gpus_only_alpha_gets_the_workspaces_endpoint_ahead_of_gemini(self):
        model = self.choose(self.alpha, H100, endpoint="nvidia/super")
        self.assertEqual((model["backend"], model["name"]), ("endpoint", "nvidia/super"))
        model = self.choose(self.beta, H100, endpoint="nvidia/super")
        self.assertIsNone(model["backend"], "beta runs only on the app's own GPUs")
        self.assertEqual(self.choose(self.alpha, f"{H100}\n{H100}", endpoint="nvidia/super")["backend"], "vllm",
                         "a machine that runs the model locally keeps it")
        self.assertEqual(self.choose(self.beta, vllm_up=True, endpoint="nvidia/super")["backend"], "vllm")

    def test_a_kept_endpoint_model_goes_with_the_vertex_model_feature(self):
        kept = {"backend": "endpoint", "name": "nvidia/super", "reason": "", "message": ""}
        self.assertEqual(access.kept_model(kept, self.alpha), kept)
        self.assertIsNone(access.kept_model(kept, self.beta)["backend"])

    def test_two_h100_serve_nemotron_for_everyone(self):
        for state in (self.alpha, self.beta):
            model = self.choose(state, f"{H100}\n{H100}")
            self.assertEqual((model["backend"], model["name"]), ("vllm", "nvidia/super"))

    def test_a_local_model_that_already_answers_is_used(self):
        self.assertEqual(self.choose(self.beta, vllm_up=True)["backend"], "vllm")

    def test_without_the_gpus_alpha_gets_vertex_and_beta_a_message(self):
        model = self.choose(self.alpha, H100)
        self.assertEqual((model["backend"], model["name"]), ("vertex", "gemini-3.5-flash"))
        model = self.choose(self.beta, "NVIDIA A100-SXM4-40GB, 40960\nNVIDIA A100-SXM4-40GB, 40960")
        self.assertIsNone(model["backend"])
        self.assertIn("GPU setup", model["message"])
        self.assertIsNone(self.choose(self.alpha, vertex="")["backend"], "no Vertex model named")

    def test_the_local_model_needs_two_gpus_of_79000_mib(self):
        self.assertIsNone(self.choose(self.beta, "NVIDIA L4, 23034\nNVIDIA L4, 23034")["backend"])
        self.assertIsNone(self.choose(self.beta, "NVIDIA H100 80GB HBM3, 78999\nNVIDIA H100 80GB HBM3, 81559")["backend"])
        self.assertEqual(self.choose(self.beta, "NVIDIA H100 80GB HBM3, 79000\nNVIDIA H100 80GB HBM3, 79000")["backend"],
                         "vllm")

    def test_model_writes_the_choice_and_model_name_prints_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "access.json"
            access.write_state(state, {"status": "ok", "tier": "alpha", "features": {"vertex_model": True}})
            run = lambda *a: subprocess.run([sys.executable, str(AI_POLICY / "access.py"), *a, "--state", str(state)],
                                            capture_output=True, text=True, check=False)
            result = run("model-name")
            self.assertEqual(result.returncode, 1, "no model chosen yet")
            result = run("model", "--gpus", "", "--vertex-model", "gemini-3.5-flash")
            self.assertEqual(result.stdout.strip(), "vertex")
            self.assertEqual(run("model-name").stdout.strip(), "gemini-3.5-flash")
            access.write_state(state, {"status": "ok", "tier": "beta", "features": {}})
            result = run("model", "--gpus", "", "--endpoint-model", "nvidia/super")
            self.assertEqual(result.stdout.strip(), "none", "no Vertex AI model for beta")
            access.write_state(state, {"status": "ok", "tier": "alpha", "features": {"vertex_model": True}})
            result = run("model", "--gpus", "", "--endpoint-model", "nvidia/super")
            self.assertEqual(result.stdout.strip(), "endpoint")
            self.assertEqual(run("model-name").stdout.strip(), "nvidia/super")
            self.assertEqual(run("model", "--gpus", "").stdout.strip(), "none")
            result = run("model-name")
            self.assertEqual(result.returncode, 1)
            self.assertIn("GPU setup", result.stderr)


if __name__ == "__main__":
    unittest.main()
