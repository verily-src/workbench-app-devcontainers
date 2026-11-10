"""Tests for model-source.sh: the gs:// URL of a directory on a gcsfuse mount."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "features" / "src" / "vllm-model" / "model-source.sh"
MOUNTS = """overlay / overlay rw,relatime 0 0
/dev/sdb1 /config ext4 rw,relatime 0 0
models-wb-example /config/workspace/models fuse.gcsfuse rw,nosuid,nodev,relatime,user_id=911,group_id=911 0 0
uploads-wb-example /config/workspace/uploads fuse.gcsfuse rw,nosuid,nodev,relatime,user_id=911 0 0
nested-bucket /config/workspace/models/nested fuse.gcsfuse rw,relatime 0 0
other /mnt/other fuse.sshfs rw,relatime 0 0
"""


class ModelSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".mounts", delete=False)
        self.tmp.write(MOUNTS)
        self.tmp.close()

    def tearDown(self):
        os.unlink(self.tmp.name)

    def source(self, directory: str) -> subprocess.CompletedProcess:
        return subprocess.run([str(SCRIPT), directory], capture_output=True, text=True, check=False,
                              env={**os.environ, "PROC_MOUNTS": self.tmp.name})

    def test_directory_on_a_bucket_mount(self):
        result = self.source("/config/workspace/models/vllm-store/nvidia--Model")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "gs://models-wb-example/vllm-store/nvidia--Model")

    def test_mount_point_itself(self):
        self.assertEqual(self.source("/config/workspace/uploads").stdout.strip(), "gs://uploads-wb-example")

    def test_longest_mount_wins(self):
        self.assertEqual(self.source("/config/workspace/models/nested/x").stdout.strip(), "gs://nested-bucket/x")

    def test_local_directory_prints_nothing(self):
        result = self.source("/config/.vllm/models/nvidia--Model")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_prefix_that_is_not_a_path_component(self):
        self.assertEqual(self.source("/config/workspace/models-copy/x").stdout, "")

    def test_other_fuse_types_are_not_buckets(self):
        self.assertEqual(self.source("/mnt/other/x").stdout, "")

    def test_relative_path_is_an_error(self):
        self.assertNotEqual(self.source("relative/dir").returncode, 0)


if __name__ == "__main__":
    unittest.main()
