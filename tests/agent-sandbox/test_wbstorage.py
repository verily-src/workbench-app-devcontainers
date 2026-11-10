"""wbstorage.py: Cloud Storage objects by gs:// URL, with literal slashes in the object path."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "features" / "src" / "agent-sandbox" / "sandbox" / "wbstorage.py"
spec = importlib.util.spec_from_file_location("wbstorage", SCRIPT)
wbstorage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wbstorage)


class WbStorageTests(unittest.TestCase):
    def test_urls_keep_the_slashes_of_the_object_name(self):
        self.assertEqual(wbstorage.object_url("gs://my-bucket/folder/sub/file name.csv"),
                         "https://storage.googleapis.com/my-bucket/folder/sub/file%20name.csv")
        self.assertNotIn("%2F", wbstorage.object_url("gs://b/a/b/c"))

    def test_split(self):
        self.assertEqual(wbstorage.split("gs://b/a/b"), ("b", "a/b"))
        self.assertEqual(wbstorage.split("gs://b/"), ("b", ""))
        self.assertEqual(wbstorage.split("gs://b"), ("b", ""))
        for bad in ("s3://b/a", "b/a", "gs:///a", 3):
            with self.assertRaises(ValueError):
                wbstorage.split(bad)
        with self.assertRaises(ValueError):
            wbstorage.object_url("gs://b/")


if __name__ == "__main__":
    unittest.main()
