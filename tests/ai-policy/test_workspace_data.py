"""workspace-data.py: Workspace Manager resource records become the sandbox's data list."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "features" / "src" / "ai-policy" / "workspace-data.py"
spec = importlib.util.spec_from_file_location("workspace_data", SCRIPT)
workspace_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace_data)


def record(name, stewardship, **attrs):
    return {"metadata": {"name": name, "stewardshipType": stewardship}, "resourceAttributes": attrs}


class WorkspaceDataTests(unittest.TestCase):
    def test_datasets_and_buckets_with_their_stewardship(self):
        resources = workspace_data.collect([
            record("admin", "REFERENCED", gcpBqDataset={"projectId": "bhs-project", "datasetId": "admin"}),
            record("mine", "CONTROLLED", gcpBqDataset={"projectId": "ws-project", "datasetId": "synthetic"}),
            record("uploads", "CONTROLLED", gcpGcsBucket={"bucketName": "uploads-ws-project"}),
            record("shared-file", "REFERENCED", gcpGcsObject={"bucketName": "other-bucket", "fileName": "a.csv"}),
            record("repo", "REFERENCED", gitRepo={"gitRepoUrl": "https://github.com/x/y"}),
        ])
        self.assertEqual(resources, [
            {"name": "admin", "stewardship": "referenced", "type": "bigquery", "project": "bhs-project", "dataset": "admin"},
            {"name": "mine", "stewardship": "controlled", "type": "bigquery", "project": "ws-project", "dataset": "synthetic"},
            {"name": "uploads", "stewardship": "controlled", "type": "storage", "bucket": "uploads-ws-project"},
            {"name": "shared-file", "stewardship": "referenced", "type": "storage", "bucket": "other-bucket"},
        ])

    def test_an_object_reference_into_an_owned_bucket_does_not_demote_it(self):
        owned = record("uploads", "CONTROLLED", gcpGcsBucket={"bucketName": "uploads-ws"})
        ref = record("one-file", "REFERENCED", gcpGcsObject={"bucketName": "uploads-ws", "fileName": "a"})
        for order in ([owned, ref], [ref, owned]):
            resources = workspace_data.collect(order)
            self.assertEqual(len(resources), 1, order)
            self.assertEqual(resources[0]["stewardship"], "controlled")

    def test_an_object_reference_never_grants_writes(self):
        resources = workspace_data.collect([
            record("f", "CONTROLLED", gcpGcsObject={"bucketName": "somebody-elses", "fileName": "a"})])
        self.assertEqual(resources[0]["stewardship"], "referenced")

    def test_an_unexpected_answer_is_unavailable_not_the_previous_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "workspace-data.json"
            output.write_text(json.dumps({"unavailable": False, "resources": [{"type": "storage", "bucket": "old"}]}))
            with mock.patch.object(workspace_data, "Workbench", side_effect=KeyError("uuid")), \
                    mock.patch("sys.argv", ["workspace-data.py", str(output)]), mock.patch("sys.stderr"):
                workspace_data.main()
            written = json.loads(output.read_text())
        self.assertTrue(written["unavailable"])
        self.assertEqual(written["resources"], [])
        self.assertIn("KeyError", written["errors"][0])

    def test_the_workspace_manager_must_be_on_workbenchs_host(self):
        for url in ("https://workbench.verily.com/api/wsm", "https://workbench.verily.com/api/wsm/"):
            self.assertEqual(workspace_data.workbench_url(url), "https://workbench.verily.com/api/wsm")
        for url in ("https://workbench-dev.verily.com/api/wsm", "http://workbench.verily.com/api/wsm", "https://example.com/api/wsm", "https://workbench.verily.com.example.com/",
                    "https://workbench.verily.com:8443/api/wsm", "https://user@evil.example/workbench.verily.com", None):
            with self.assertRaises(workspace_data.Unavailable, msg=url):
                workspace_data.workbench_url(url)


if __name__ == "__main__":
    unittest.main()
