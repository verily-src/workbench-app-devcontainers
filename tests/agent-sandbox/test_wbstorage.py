"""wbstorage's listing: object URLs and their sizes, across pages, with the HTTP session faked."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "features" / "src" / "agent-sandbox" / "sandbox"))
import wbstorage  # noqa: E402


class FakeResponse:
    def __init__(self, body):
        self.status_code, self._body, self.text = 200, body, ""

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return FakeResponse(self.pages[len(self.calls) - 1])


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, wbstorage, "_session", None)

    def test_sizes_and_names_come_from_the_same_paged_listing(self):
        wbstorage._session = FakeSession([
            {"items": [{"name": "cram/a.cram", "size": "14437718353"}], "nextPageToken": "t1"},
            {"items": [{"name": "cram/a.cram.crai", "size": "1250777"}]},
        ])
        self.assertEqual(wbstorage.sizes("gs://genomes/cram/"),
                         {"gs://genomes/cram/a.cram": 14437718353, "gs://genomes/cram/a.cram.crai": 1250777})
        calls = wbstorage._session.calls
        self.assertEqual(calls[0][0], "https://storage.googleapis.com/storage/v1/b/genomes/o")
        self.assertEqual(calls[0][1]["prefix"], "cram/")
        self.assertEqual(calls[1][1]["pageToken"], "t1")
        wbstorage._session = FakeSession([{"items": [{"name": "x", "size": "3"}, {"name": "y"}]}])
        self.assertEqual(wbstorage.list_objects("gs://b/"), ["gs://b/x", "gs://b/y"])


if __name__ == "__main__":
    unittest.main()
