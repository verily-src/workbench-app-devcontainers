"""deploy-endpoint.sh run against stand-ins for gcloud and curl on PATH: nothing is created
without --yes, and an operation that errors or never finishes ends the script."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "features" / "src" / "vertex-model" / "deploy-endpoint.sh"
ENDPOINT = '{"endpoints": [{"name": "projects/1/locations/us-central1/endpoints/42"}]}'
DEPLOYED = '{"deployedModels": [{"id": "7"}]}'


class DeployScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.calls = self.root / "calls"
        self.polls = self.root / "polls"
        self.stub("gcloud", f'echo "$@" >> {self.calls}\n[[ "$1 $2" == "auth print-access-token" ]] && echo token\nexit 0')
        self.curl(operation='{"error": {"code": 403, "message": "Permission denied on project p."}}')

    def stub(self, name, body):
        path = self.bin / name
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(0o755)

    def curl(self, operation, undeploy='{"name": "projects/1/locations/us-central1/operations/9"}', fail_first=0):
        """GETs of endpoints answer as a deployed endpoint; the undeploy POST answers `undeploy`;
        GETs of the operation answer `operation`, after `fail_first` failed requests."""
        failed = self.root / "failed"
        self.stub("curl", f'''echo "$@" >> {self.polls}
args="$*"
case "$args" in
  *undeployModel*) echo '{undeploy}' ;;
  *operations/9*)
    n=$(cat {failed} 2> /dev/null || echo 0)
    if (( n < {fail_first} )); then echo $(( n + 1 )) > {failed}; exit 6; fi
    echo '{operation}' ;;
  *endpoints/42*) echo '{DEPLOYED}' ;;
  *endpoints*) echo '{ENDPOINT}' ;;
  *) echo '{{}}' ;;
esac''')

    def run_script(self, *args):
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "DEPLOY_POLL_SECONDS": "0"}
        env.pop("GOOGLE_CLOUD_PROJECT", None)
        return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)

    def test_without_yes_it_says_what_it_would_create_and_creates_nothing(self):
        done = self.run_script("--project", "p", "--region", "europe-west4", "--machine", "g4-standard-96")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Project p, region europe-west4", done.stdout)
        self.assertIn("g4-standard-96", done.stdout)
        self.assertIn("$6/h", done.stdout)
        self.assertIn("--yes", done.stderr)
        for log in (self.calls, self.polls):
            text = log.read_text() if log.exists() else ""
            self.assertNotIn("artifacts repositories create", text)
            self.assertNotIn("POST", text)
            self.assertNotIn("-X", text)

    def test_with_yes_it_goes_on_to_create(self):
        self.run_script("--project", "p", "--yes")
        self.assertIn("artifacts repositories describe", self.calls.read_text())

    def test_an_error_reply_while_waiting_fails_with_the_apis_message(self):
        done = self.run_script("--project", "p", "--delete")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Permission denied on project p.", done.stderr)
        self.assertLess(len((self.polls.read_text()).splitlines()), 10)

    def test_an_error_reply_in_place_of_an_operation_name_fails_instead_of_waiting_on_null(self):
        self.curl(operation="{}", undeploy='{"error": {"code": 403, "message": "Denied to undeploy."}}')
        done = self.run_script("--project", "p", "--delete")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Denied to undeploy.", done.stderr)
        self.assertIn("No operation to wait for", done.stderr)

    def test_an_operation_that_never_finishes_times_out(self):
        self.curl(operation='{"name": "projects/1/locations/us-central1/operations/9"}')
        done = self.run_script("--project", "p", "--delete")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Timed out after 60 polls", done.stderr)

    def test_a_failed_request_is_tried_again_but_not_for_ever(self):
        self.curl(operation='{"done": true, "response": {}}', fail_first=3)
        done = self.run_script("--project", "p", "--delete")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.curl(operation='{"done": true}', fail_first=100)
        (self.root / "failed").unlink()
        done = self.run_script("--project", "p", "--delete")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Could not reach the Vertex AI API", done.stderr)


if __name__ == "__main__":
    unittest.main()
