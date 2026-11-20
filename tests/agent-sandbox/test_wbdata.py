"""wbdata.py: the workspace's datasets described in one call, against a fake BigQuery client; and
the data notes that point the agent at it."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "features" / "src" / "agent-sandbox" / "sandbox" / "wbdata.py"
spec = importlib.util.spec_from_file_location("wbdata", SCRIPT)
wbdata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wbdata)

NOTES = """# Data you can reach

This is the data of the Workbench workspace you are in. Queries run as jobs in project `wb-work`.

BigQuery datasets:
- `wb-data.crf` (read-only)
- `wb-data.locked` (read-only)
- `wb-work.scratch` (read and write: the workspace owns it)

Cloud Storage buckets:
- `gs://a-bucket` (read-only)
"""

TABLES = {"crf": [("CE", 6203), ("DM", 2502)], "scratch": [("RESULTS", 10)]}
COLUMNS = {
    "crf": [("CE", "SUBJID", "STRING"), ("CE", "event_date", "DATE"), ("DM", "SUBJID", "STRING"),
            ("DM", "birth_ts", "TIMESTAMP")],
    "scratch": [("RESULTS", "SUBJID", "STRING"), ("RESULTS", "risk", "FLOAT64")],
}


class Row(dict):
    def items(self):
        return super().items()


class FakeJob:
    def __init__(self, rows):
        self.rows = rows

    def result(self):
        return [Row(r) for r in self.rows]


class FakeClient:
    def __init__(self):
        self.sql = []

    def query(self, sql, **_):
        self.sql.append(sql)
        dataset = sql.split("`")[1].split(".")[1]
        if dataset == "locked":
            raise RuntimeError("403 Access Denied: Table wb-data:locked.__TABLES__: User does not have permission")
        if "__TABLES__" in sql:
            return FakeJob([{"table_id": t, "row_count": n} for t, n in TABLES[dataset]])
        return FakeJob([{"table_name": t, "column_name": c, "data_type": ty} for t, c, ty in COLUMNS[dataset]])


class WbdataTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        notes = Path(self.dir.name) / "data-access.md"
        notes.write_text(NOTES)
        self.saved = (wbdata.NOTES, wbdata._client)
        wbdata.NOTES = str(notes)
        wbdata._client = self.client = FakeClient()

    def tearDown(self):
        wbdata.NOTES, wbdata._client = self.saved
        self.dir.cleanup()

    def test_the_datasets_and_project_come_from_the_notes(self):
        self.assertEqual(wbdata.datasets(), ["wb-data.crf", "wb-data.locked", "wb-work.scratch"])
        self.assertEqual(wbdata._project(), "wb-work")

    def test_survey_reads_two_metadata_tables_per_dataset_and_reports_each(self):
        out = wbdata.survey()
        self.assertIn("wb-data.crf: 2 tables", out)
        self.assertIn("  CE: 6,203 rows, 2 columns; dates: event_date", out)
        self.assertIn("  DM: 2,502 rows, 2 columns; dates: birth_ts", out)
        self.assertIn("  RESULTS: 10 rows, 2 columns; no date columns", out)
        self.assertEqual(len(self.client.sql), 5, "two queries per dataset (one for the refused one), none per table")
        self.assertIn("`wb-data.crf.__TABLES__`", " ".join(self.client.sql))
        self.assertIn("`wb-data.crf.INFORMATION_SCHEMA.COLUMNS`", " ".join(self.client.sql))

    def test_a_refused_dataset_is_one_line_that_says_to_stop_and_the_rest_are_still_read(self):
        out = wbdata.survey()
        line = next(l for l in out.splitlines() if l.startswith("wb-data.locked"))
        self.assertIn("Google refused it (403)", line)
        self.assertIn("do not look for other data", line)
        self.assertNotIn("User does not have permission", out)
        self.assertIn("wb-work.scratch: 1 tables", out)

    def test_describe_lists_columns_and_find_searches_every_dataset(self):
        described = wbdata.describe("wb-data.crf")
        self.assertIn("CE (6,203 rows): SUBJID STRING, event_date DATE", described)
        self.assertNotIn("RESULTS", described)
        found = wbdata.find_columns("date|_ts$")
        self.assertIn("wb-data.crf.CE (6,203 rows): event_date DATE", found)
        self.assertIn("wb-data.crf.DM (2,502 rows): birth_ts TIMESTAMP", found)
        self.assertNotIn("RESULTS", found)
        self.assertEqual(wbdata.find_columns("nothing_like_this", ["wb-work.scratch"]),
                         "No column matches 'nothing_like_this'.")

    def test_a_name_that_could_inject_sql_is_refused(self):
        for bad in ("p.d`; DROP TABLE x; --", "p.d e", "nodot"):
            with self.assertRaises(ValueError):
                wbdata._ref(bad, "__TABLES__")

    def test_the_command_line(self):
        self.assertIn("usage", wbdata.main([]))
        self.assertIn("wb-data.crf: 2 tables", wbdata.main(["survey", "wb-data.crf"]))
        self.assertIn("event_date DATE", wbdata.main(["describe", "wb-data.crf", "CE"]))
        self.assertIn("birth_ts", wbdata.main(["find", "_ts$"]))


class NotesTests(unittest.TestCase):
    def test_the_data_notes_point_the_agent_at_wbdata(self):
        script = (ROOT / "features" / "src" / "agent-sandbox" / "agent-sandbox.sh").read_text()
        start = script.index("  jq -r '\n    def python") + len("  jq -r '")
        program = script[start:script.index("' \"${POLICY_SUMMARY}\" > \"${notes}/data-access.md\"")]
        summary = {"data": {"enabled": True, "python": "/usr/bin/python3.11", "project": "wb-x", "write": False,
                            "datasets": [{"project": "p1", "dataset": "d1", "write": False}], "buckets": []},
                   "tools": {"enabled": False}, "servers": []}
        with tempfile.NamedTemporaryFile("w", suffix=".json") as handle:
            json.dump(summary, handle)
            handle.flush()
            notes = subprocess.run(["jq", "-r", program, handle.name], capture_output=True, text=True, check=True).stdout
        self.assertIn("/opt/venv/bin/python -m wbdata survey", notes)
        self.assertIn("Do not list or read tables one at a time", notes)
        # The notes' own lines are what wbdata reads its datasets and project from.
        self.assertIn("- `p1.d1` (read-only)", notes)
        self.assertIn("jobs in project `wb-x`", notes)


if __name__ == "__main__":
    unittest.main()
