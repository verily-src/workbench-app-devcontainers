"""Tests for app/data.py, using a stand-in for BigQuery.

Run from this folder's parent:
    app/.venv/bin/python -m unittest discover -s tests -v
"""

import concurrent.futures
import sys
import unittest
from pathlib import Path
from unittest import mock

from google.api_core import exceptions as api_errors
from google.auth import exceptions as auth_errors

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import data  # noqa: E402

DATASET = "some-project.some_dataset"


class FakeRow:
    def __init__(self, **values):
        self._values = values

    def items(self):
        return self._values.items()


class FakeJob:
    def __init__(self, statement_type="SELECT", bytes_processed=0, rows=(), result_error=None):
        self.statement_type = statement_type
        self.total_bytes_processed = bytes_processed
        self._rows = rows
        self._result_error = result_error
        self.cancelled = False
        self.result_arguments = None

    def result(self, timeout=None, max_results=None):
        self.result_arguments = {"timeout": timeout, "max_results": max_results}
        if self._result_error:
            raise self._result_error
        return list(self._rows)[:max_results]

    def cancel(self):
        self.cancelled = True


class FakeTable:
    def __init__(self, table_id, table_type):
        self.table_id = table_id
        self.table_type = table_type


class FakeClient:
    """Records every call and returns whatever the test set up."""

    def __init__(self, dry_run=None, real=None, tables=(), query_error=None, list_error=None):
        self.dry_run_job = dry_run or FakeJob()
        self.real_job = real or FakeJob(rows=[FakeRow(row_count=42)])
        self.tables = tables
        self.query_error = query_error
        self.list_error = list_error
        self.queries = []
        self.listed = []

    def query(self, sql, job_config=None):
        self.queries.append((sql, job_config))
        if self.query_error:
            raise self.query_error
        return self.dry_run_job if job_config.dry_run else self.real_job

    def list_tables(self, path, max_results=None):
        self.listed.append((path, max_results))
        if self.list_error:
            raise self.list_error
        return list(self.tables)


class ParseDatasetTests(unittest.TestCase):
    def test_accepts_dot_and_colon_forms(self):
        self.assertEqual(data.parse_dataset(DATASET), ("some-project", "some_dataset"))
        self.assertEqual(data.parse_dataset(" some-project:some_dataset "), ("some-project", "some_dataset"))

    def test_rejects_anything_else(self):
        bad = ["", None, "some_dataset", "p.d", "some-project.some dataset",
               "some-project.some_dataset.table", "some-project.d`; DROP TABLE x",
               "Some-Project.some_dataset", "some-project."]
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(data.DataError) as caught:
                    data.parse_dataset(value)
                self.assertEqual(caught.exception.kind, "bad_input")


class ListTablesTests(unittest.TestCase):
    def test_returns_sorted_names_and_types(self):
        client = FakeClient(tables=[FakeTable("zeta", "VIEW"), FakeTable("alpha", "TABLE")])
        self.assertEqual(
            data.list_tables(client, DATASET),
            [{"name": "alpha", "type": "table"}, {"name": "zeta", "type": "view"}],
        )
        self.assertEqual(client.listed, [(DATASET, data.MAX_TABLES_LISTED)])

    def test_no_access_and_not_found_are_explained(self):
        cases = [(api_errors.Forbidden("denied"), "no_access"), (api_errors.NotFound("missing"), "not_found")]
        for error, kind in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(data.DataError) as caught:
                    data.list_tables(FakeClient(list_error=error), DATASET)
                self.assertEqual(caught.exception.kind, kind)
                self.assertIn("some-project.some_dataset", str(caught.exception))

    def test_bad_dataset_never_reaches_bigquery(self):
        client = FakeClient()
        with self.assertRaises(data.DataError):
            data.list_tables(client, "not a dataset")
        self.assertEqual(client.listed, [])


class CountRowsTests(unittest.TestCase):
    def test_counts_one_table(self):
        client = FakeClient()
        result = data.count_rows(client, DATASET, "events")
        self.assertEqual(result.rows, [{"row_count": 42}])
        self.assertEqual(result.sql, "SELECT COUNT(*) AS row_count FROM `some-project.some_dataset.events`")
        self.assertFalse(result.truncated)

    def test_rejects_unsafe_table_names(self):
        for table in ["", None, "events`", "events; DROP TABLE x", "a b", "a.b", "a-b"]:
            with self.subTest(table=table):
                client = FakeClient()
                with self.assertRaises(data.DataError) as caught:
                    data.count_rows(client, DATASET, table)
                self.assertEqual(caught.exception.kind, "bad_input")
                self.assertEqual(client.queries, [])


class RunSelectTests(unittest.TestCase):
    def test_checks_first_then_runs_with_the_byte_limit(self):
        client = FakeClient()
        data.run_select(client, "SELECT 1")
        self.assertEqual(len(client.queries), 2)
        self.assertTrue(client.queries[0][1].dry_run)
        self.assertFalse(client.queries[1][1].dry_run)
        self.assertEqual(client.queries[1][1].maximum_bytes_billed, data.MAX_BYTES_BILLED)
        self.assertEqual(client.real_job.result_arguments["timeout"], data.QUERY_TIMEOUT_SECONDS)

    def test_refuses_anything_that_is_not_a_select(self):
        for statement in ["INSERT", "UPDATE", "DELETE", "MERGE", "CREATE_TABLE_AS_SELECT", "DROP_TABLE", "SCRIPT", None]:
            with self.subTest(statement=statement):
                client = FakeClient(dry_run=FakeJob(statement_type=statement))
                with self.assertRaises(data.DataError) as caught:
                    data.run_select(client, "anything")
                self.assertEqual(caught.exception.kind, "not_read_only")
                self.assertEqual(len(client.queries), 1, "the real query must never start")

    def test_refuses_a_query_over_the_byte_limit_before_running_it(self):
        client = FakeClient(dry_run=FakeJob(bytes_processed=data.MAX_BYTES_BILLED + 1))
        with self.assertRaises(data.DataError) as caught:
            data.run_select(client, "SELECT 1")
        self.assertEqual(caught.exception.kind, "too_big")
        self.assertEqual(len(client.queries), 1)

    def test_limit_hit_while_running_is_explained(self):
        error = api_errors.BadRequest("Query exceeded limit for bytes billed: bytesBilledLimitExceeded")
        client = FakeClient(real=FakeJob(result_error=error))
        with self.assertRaises(data.DataError) as caught:
            data.run_select(client, "SELECT 1")
        self.assertEqual(caught.exception.kind, "too_big")

    def test_slow_query_is_cancelled(self):
        job = FakeJob(result_error=concurrent.futures.TimeoutError())
        with self.assertRaises(data.DataError) as caught:
            data.run_select(FakeClient(real=job), "SELECT 1")
        self.assertEqual(caught.exception.kind, "timeout")
        self.assertTrue(job.cancelled)

    def test_no_access_and_not_found_are_explained(self):
        cases = [(api_errors.Forbidden("denied"), "no_access"), (api_errors.NotFound("missing"), "not_found")]
        for error, kind in cases:
            with self.subTest(kind=kind):
                with self.assertRaises(data.DataError) as caught:
                    data.run_select(FakeClient(query_error=error), "SELECT 1", what="the table events")
                self.assertEqual(caught.exception.kind, kind)
                self.assertIn("the table events", str(caught.exception))

    def test_long_results_are_cut_and_flagged(self):
        rows = [FakeRow(n=n) for n in range(data.MAX_ROWS_SHOWN + 5)]
        result = data.run_select(FakeClient(real=FakeJob(rows=rows)), "SELECT 1")
        self.assertEqual(len(result.rows), data.MAX_ROWS_SHOWN)
        self.assertTrue(result.truncated)

    def test_unexpected_errors_keep_their_text(self):
        with self.assertRaises(data.DataError) as caught:
            data.run_select(FakeClient(query_error=RuntimeError("boom")), "SELECT 1")
        self.assertEqual(caught.exception.kind, "other")
        self.assertIn("boom", str(caught.exception))


class ConnectTests(unittest.TestCase):
    def test_missing_credentials_are_explained(self):
        with mock.patch.object(data.google.auth, "default", side_effect=auth_errors.DefaultCredentialsError("none")):
            with self.assertRaises(data.DataError) as caught:
                data.connect()
        self.assertEqual(caught.exception.kind, "no_credentials")

    def test_missing_project_is_explained(self):
        with mock.patch.object(data.google.auth, "default", return_value=(object(), None)):
            with self.assertRaises(data.DataError) as caught:
                data.connect()
        self.assertEqual(caught.exception.kind, "no_credentials")

    def test_reports_identity_and_project(self):
        class Credentials:
            service_account_email = "someone@example.iam.gserviceaccount.com"

        with mock.patch.object(data.google.auth, "default", return_value=(Credentials(), "some-project")), \
                mock.patch.object(data.bigquery, "Client") as client_class:
            client, info = data.connect()
        self.assertIs(client, client_class.return_value)
        self.assertEqual(info, data.ConnectionInfo("someone@example.iam.gserviceaccount.com", "some-project"))


class IdentityTests(unittest.TestCase):
    def test_vm_identity_is_read_after_a_refresh(self):
        class Credentials:
            service_account_email = "default"

            def refresh(self, request):
                self.service_account_email = "vm@example.iam.gserviceaccount.com"

        self.assertEqual(data._identity_of(Credentials()), "vm@example.iam.gserviceaccount.com")

    def test_a_failed_refresh_does_not_break_the_connection(self):
        class Credentials:
            service_account_email = "default"

            def refresh(self, request):
                raise RuntimeError("no network")

        self.assertEqual(data._identity_of(Credentials()), "your own Google login")

    def test_personal_login_is_described_plainly(self):
        class Credentials:
            account = ""

            def refresh(self, request):
                pass

        self.assertEqual(data._identity_of(Credentials()), "your own Google login")


if __name__ == "__main__":
    unittest.main()
