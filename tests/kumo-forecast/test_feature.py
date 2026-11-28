"""The kumo-forecast feature: its catalog against its server, the cohort reader against the
designer's session files, small-cell masking, and the app's wiring. Runs without a GPU, BigQuery
or the model's packages (standard library and PyYAML)."""
import json
import re
import sys
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FEATURES = REPO / "features" / "src"
FEATURE = FEATURES / "kumo-forecast"
APP = REPO / "src" / "ai-research-assistant"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
URL = "http://host.openshell.internal:9244/mcp"
OMOP_SCHEMAS = {
    "person": {"columns": [("person_id", "INTEGER"), ("year_of_birth", "INTEGER")], "source": "wb-data-1234.omop",
               "table": "person"},
    "condition_occurrence": {"columns": [("person_id", "INTEGER"), ("condition_concept_id", "INTEGER"),
                                         ("condition_start_date", "DATE"), ("condition_source_value", "STRING")],
                             "source": "wb-data-1234.omop", "table": "condition_occurrence"},
    "measurement": {"columns": [("person_id", "INTEGER"), ("measurement_concept_id", "INTEGER"),
                                ("measurement_date", "DATE"), ("value_as_number", "FLOAT"), ("abnormal", "BOOLEAN")],
                    "source": "wb-data-1234.omop", "table": "measurement"},
    "death": {"columns": [("person_id", "INTEGER"), ("death_date", "DATE")], "source": "wb-data-1234.omop",
              "table": "death"},
    "concept": {"columns": [("concept_id", "INTEGER"), ("concept_name", "STRING")], "source": "wb-data-1234.omop",
                "table": "concept"},
}
CKD3 = {"table": "condition_occurrence", "where": [{"column": "condition_concept_id", "op": "in", "value": [443597]}]}

sys.path.insert(0, str(FEATURE))
sys.path.insert(0, str(FEATURES / "ai-policy"))
from kumo_forecast import cohort, destination, outcome, privacy, schema  # noqa: E402  (standard library only)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = yaml.safe_load((FEATURE / "sandbox" / "forecast.yaml").read_text())

    def test_the_catalog_lists_exactly_the_tools_the_server_offers(self):
        serve = (FEATURE / "serve.py").read_text()
        tools = re.findall(r"^@mcp\.tool\nasync def (\w+)\(", serve, flags=re.M)
        self.assertEqual(sorted(tools), sorted(self.catalog["tools"]))
        declared = re.search(r"^TOOLS = \((.*)\)$", serve, flags=re.M).group(1).replace('"', "").split(", ")
        self.assertEqual(sorted(declared), sorted(tools))

    def test_the_app_accepts_the_catalog(self):
        import ai_policy
        loaded = ai_policy.load_server_catalog(self.catalog)
        self.assertEqual(loaded["name"], "forecast")
        self.assertEqual(loaded["ask"], ["select_highest_risk"])

    def test_the_agent_is_told_every_tool_by_its_sandbox_name(self):
        for tool in self.catalog["tools"]:
            self.assertIn(f"`forecast_{tool}`", self.catalog["instructions"], tool)

    def test_the_forecast_takes_the_outcome_described_and_no_second_lock(self):
        serve = (FEATURE / "serve.py").read_text()
        signature = re.search(r"async def forecast_risk\((.*?)\) -> dict:", serve, flags=re.S).group(1)
        self.assertTrue(signature.startswith("outcome: dict"), signature)
        for gone in ("outcome_lock_version", "outcome_session_id", "population"):
            self.assertIsNone(re.search(rf"\b{gone}\s*:", signature), gone)
        text = " ".join(self.catalog["instructions"].split())
        self.assertIn("Never ask the designer to build or lock a cohort for the outcome", text)
        self.assertNotIn("outcome_lock_version", text)
        self.assertNotIn("sarek", text.lower())

    def test_the_agent_is_told_every_outcome_operator(self):
        text = self.catalog["instructions"]
        for op in outcome.OPS:
            self.assertIn(f"`{op}`", text, op)

    def test_the_agent_is_told_not_to_pass_sql_or_ids(self):
        self.assertIn("never pass it SQL or participant ids", self.catalog["instructions"])


class CohortTests(unittest.TestCase):
    def test_the_newest_locked_session_is_read_as_a_cohort_of_people(self):
        c = cohort.locked_cohort(cohort.load_session(FIXTURES / "people"))
        self.assertEqual((c.session_id, c.version), ("20261111-224856", 1))
        self.assertEqual((c.key_column, c.key_data_column, c.index_column), ("cohort_key", "person_id", "index_date"))
        self.assertEqual(c.dataset, "wb-data-1234.omop")
        self.assertEqual(c.billing_project, "wb-work-5678")
        self.assertEqual(c.question, "Adults with hypertension.")
        self.assertIn("SELECT", c.sql)

    def test_journals_and_message_logs_are_not_sessions(self):
        names = [p.name for p in cohort.session_files(FIXTURES / "people")]
        self.assertEqual(names, ["20261111-224856.json"])

    def test_a_session_is_found_by_id(self):
        data = cohort.load_session(FIXTURES / "people", "20261111-224856")
        self.assertEqual(data["session_id"], "20261111-224856")

    def test_an_unsafe_or_missing_session_id_is_refused(self):
        for bad in ("../etc/passwd", "latest; drop", "20261111-999999"):
            with self.assertRaises(cohort.CohortError):
                cohort.load_session(FIXTURES / "people", bad)

    def test_a_cohort_of_stays_is_keyed_by_its_own_column(self):
        c = cohort.locked_cohort(cohort.load_session(FIXTURES / "stays"))
        self.assertEqual((c.key_column, c.key_data_column), ("cohort_key", "visit_occurrence_id"))

    def test_a_lock_with_no_key_is_refused(self):
        data = cohort.load_session(FIXTURES / "people")
        for col in data["locks"][0]["export"]["columns"]:
            if col["meaning"] == "key":
                col["meaning"] = "attribute"
        with self.assertRaisesRegex(cohort.CohortError, "no key column"):
            cohort.locked_cohort(data)

    def two_locks(self):
        data = cohort.load_session(FIXTURES / "two_locks")
        return data, cohort.locked_cohort(data, 1), cohort.locked_cohort(data, 2)

    def test_two_locks_of_a_session_are_read_by_version(self):
        _, first, second = self.two_locks()
        self.assertEqual((first.version, second.version), (1, 2))
        self.assertIn("443597", second.sql)

    def without_column(self, grain="patient", tables=("person", "condition_occurrence", "concept")):
        data = cohort.load_session(FIXTURES / "people")
        lock = data["locks"][0]
        # The person's key with no data column: the one key a lock may print without one.
        key = next(c for c in lock["export"]["columns"] if c["meaning"] == "key")
        key.pop("column")
        key["meaning"] = "person_key"
        key["grain"] = grain
        lock["evidence"]["tables"] = [{"table": {"name": f"wb-data-1234.omop.{t}", "read": {}}, "state": "columns"}
                                      for t in tables]
        return cohort.locked_cohort(data)

    def test_a_key_without_a_data_column_is_read_from_the_schema(self):
        omop = {"person": {"columns": [("person_id", "INTEGER")]},
                "condition_occurrence": {"columns": [("person_id", "INTEGER"), ("condition_concept_id", "INTEGER")]},
                "concept": {"columns": [("concept_id", "INTEGER")]}}
        lc = self.without_column()
        self.assertIsNone(lc.key_data_column)
        self.assertEqual(lc.dataset, "wb-data-1234.omop")
        # OMOP: person_id, whatever the grain is called and though the vocabulary holds none.
        self.assertEqual(cohort.resolve_key(lc, omop).key_data_column, "person_id")
        self.assertEqual(cohort.resolve_key(self.without_column(tables=("condition_occurrence", "concept")), omop)
                         .key_data_column, "person_id")
        # Other data: the grain's own id comes first.
        study = {"visits": {"columns": [("patient_id", "STRING"), ("visit_date", "DATE")]}}
        self.assertEqual(cohort.resolve_key(self.without_column(tables=("visits",)), study).key_data_column,
                         "patient_id")
        with self.assertRaisesRegex(cohort.CohortError, "patient_id, patient, person_id is in a table it reads"):
            cohort.resolve_key(self.without_column(tables=("visits",)), {"visits": {"columns": [("PATNO", "INTEGER")]}})
        named = cohort.locked_cohort(cohort.load_session(FIXTURES / "people"))
        self.assertIs(cohort.resolve_key(named, study), named)

    def test_no_lock_yet_says_to_lock_one(self):
        with self.assertRaisesRegex(cohort.CohortError, "lock one in the cohort designer"):
            cohort.load_session(FIXTURES / "unlocked")

    def test_a_missing_lock_version_names_the_ones_there_are(self):
        with self.assertRaisesRegex(cohort.CohortError, "no lock version 3; it has 1"):
            cohort.locked_cohort(cohort.load_session(FIXTURES / "people"), version=3)


class StudyAcrossDatasetsTests(unittest.TestCase):
    """A study that keeps its forms in several datasets of one project (case report forms,
    screening, analysis): the cohort reads them all, and so does the forecast."""

    def needs_pandas(self):
        """tables reads with pandas; the cohort tests below need only the standard library."""
        try:
            import pandas
        except ImportError:
            self.skipTest("needs pandas")
        from kumo_forecast import tables
        return pandas, tables

    class Client:
        def __init__(self, datasets, pd=None):
            self.pd = pd
            self.datasets, self.queries = datasets, []

        def list_tables(self, dataset):
            import types
            return [types.SimpleNamespace(table_id=t, table_type="TABLE") for t in self.datasets[dataset]]

        def get_table(self, ref):
            import types
            dataset, table = ref.rsplit(".", 1)
            fields = [types.SimpleNamespace(name=n, field_type=ty, mode="NULLABLE")
                      for n, ty in self.datasets[dataset][table]]
            return types.SimpleNamespace(schema=fields, num_rows=3, modified=None)

        def query(self, sql):
            import types
            self.queries.append(sql)
            frame = self.pd.DataFrame({"USUBJID": ["a", "b", "c"], "study_day": [1, 2, 3]})
            return types.SimpleNamespace(to_dataframe=lambda: frame)

    STUDY = {"wb-study-1234.crf": {"MH": [("USUBJID", "STRING"), ("study_day", "INTEGER")],
                                   "DM": [("USUBJID", "STRING")]},
             "wb-study-1234.screener": {"DM": [("USUBJID", "STRING")]},
             "wb-study-1234.analysis": {"SCORES": [("USUBJID", "STRING")]}}

    def test_the_schemas_of_every_dataset_are_read_and_a_shared_name_told_apart(self):
        pd, tables = self.needs_pandas()
        client = self.Client(self.STUDY, pd)
        schemas = tables.read_schemas(client, "wb-study-1234.crf,wb-study-1234.screener,wb-study-1234.analysis")
        self.assertEqual(sorted(schemas), ["MH", "SCORES", "crf_DM", "screener_DM"])
        self.assertEqual((schemas["screener_DM"]["source"], schemas["screener_DM"]["table"]),
                         ("wb-study-1234.screener", "DM"))
        one = tables.read_schemas(client, "wb-study-1234.crf")
        self.assertEqual(sorted(one), ["DM", "MH"], "one dataset's names are its tables' own")

    def test_each_table_is_read_from_its_own_dataset(self):
        import tempfile
        pd, tables = self.needs_pandas()
        client = self.Client(self.STUDY, pd)
        schemas = tables.read_schemas(client, "wb-study-1234.crf,wb-study-1234.screener")
        plan = tables.Plan("USUBJID", ["screener_DM", "MH"], {"screener_DM": None, "MH": None}, 6, schemas)
        with tempfile.TemporaryDirectory() as tmp:
            raw = tables.load(client, "wb-study-1234.crf,wb-study-1234.screener", plan, Path(tmp))
        self.assertEqual(sorted(raw), ["MH", "screener_DM"])
        self.assertIn("FROM `wb-study-1234`.`screener`.`DM`", client.queries[0])
        self.assertIn("FROM `wb-study-1234`.`crf`.`MH`", client.queries[1])

    def test_tables_dated_only_by_study_day_are_refused_before_any_is_read(self):
        pd, tables = self.needs_pandas()
        client = self.Client(self.STUDY, pd)
        schemas = tables.read_schemas(client, "wb-study-1234.crf")
        with self.assertRaisesRegex(schema.SchemaError, "needs calendar dates.*study day"):
            tables.plan(schemas, "USUBJID")
        self.assertEqual(client.queries, [])

    def lock(self, names, key_column="USUBJID"):
        data = cohort.load_session(FIXTURES / "people")
        lock = data["locks"][0]
        key = next(c for c in lock["export"]["columns"] if c["meaning"] == "key")
        key["column"] = key_column
        lock["evidence"]["tables"] = [{"table": {"name": n, "read": {}}, "state": "columns"} for n in names]
        return cohort.locked_cohort(data)

    def test_a_cohort_drawn_from_several_datasets_reads_them_all(self):
        lc = self.lock(["wb-study-1234.crf.MH", "wb-study-1234.screener.DM", "wb-study-1234.analysis.SCORES"])
        self.assertEqual(lc.dataset, "wb-study-1234.analysis,wb-study-1234.crf,wb-study-1234.screener")
        self.assertEqual(lc.dataset.split(",")[1], "wb-study-1234.crf")
        # OMOP: the key's own table still settles one dataset, whatever else is read.
        omop = self.lock(["wb-data-1234.omop.person", "wb-data-1234.vocab.concept"], "person_id")
        self.assertEqual(omop.dataset, "wb-data-1234.omop")

class BackgroundJobTests(unittest.TestCase):
    """A slow tool answers within the agent's call timeout with a job id, and the same call made
    again waits on the same work (serve.py, with fastmcp and the service stubbed)."""

    def setUp(self):
        import asyncio
        import importlib
        import types
        stub = types.ModuleType("fastmcp")

        class FastMCP:
            def __init__(self, *a, **k):
                pass

            def tool(self, fn):
                return fn
        stub.FastMCP = FastMCP
        service = types.ModuleType("kumo_forecast.service")
        service.Service = object
        self.saved = {n: sys.modules.get(n) for n in ("fastmcp", "kumo_forecast.service")}
        sys.modules.update({"fastmcp": stub, "kumo_forecast.service": service})
        spec = importlib.util.spec_from_file_location("kumo_serve", FEATURE / "serve.py")
        self.serve = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.serve)
        self.serve.WAIT_S = 0.2
        self.asyncio = asyncio

    def tearDown(self):
        for name, module in self.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_a_slow_call_returns_a_job_and_the_answer_comes_later(self):
        import threading
        import time
        serve, release, calls = self.serve, threading.Event(), []

        def slow(*args):
            calls.append(args)
            release.wait(5)
            return {"answer": 42}

        async def run():
            first = await serve._waited("forecast_risk", slow, "s", 2)
            again = await serve._waited("forecast_risk", slow, "s", 2)
            self.assertEqual(first["status"], "running")
            self.assertEqual(again["job_id"], first["job_id"], "the same call waits on the same work")
            release.set()
            await self.asyncio.sleep(0.1)
            done = await serve.wait_for_result(first["job_id"])
            gone = await serve.wait_for_result(first["job_id"])
            return done, gone

        done, gone = self.asyncio.run(run())
        self.assertEqual(done, {"answer": 42})
        self.assertIn("no running job", gone["error"])
        self.assertEqual(len(calls), 1)

    def test_a_finished_job_nobody_collected_is_dropped_when_the_next_job_starts(self):
        import time
        serve = self.serve
        serve.KEEP_FINISHED_S = 0.05

        async def run():
            first = await serve._waited("forecast_risk", lambda *a: time.sleep(1.3) or {"ok": 1}, "a")
            self.assertEqual(first["status"], "running")
            await self.asyncio.sleep(0.5)
            self.assertIn(first["job_id"], serve.JOBS, "finished, answer not collected yet")
            await self.asyncio.sleep(0.1)
            await serve._waited("get_cohort_info", lambda *a: {"ok": 2}, "b")
            return first["job_id"]

        job_id = self.asyncio.run(run())
        self.assertNotIn(job_id, serve.JOBS)
        self.assertNotIn(job_id, serve.FINISHED)

    def test_a_quick_call_answers_at_once_and_an_error_is_the_answer(self):
        serve = self.serve

        def refuse(*args):
            raise schema.SchemaError("no date column")

        async def run():
            return (await serve._waited("get_cohort_info", lambda *a: {"ok": True}, "s"),
                    await serve._waited("get_cohort_info", refuse, "t"))

        quick, refused = self.asyncio.run(run())
        self.assertEqual(quick, {"ok": True})
        self.assertEqual(refused, {"error": "no date column"})


    def test_warming_reads_the_newest_lock_and_the_warm_tables_and_never_fails_the_server(self):
        import os
        import types
        from unittest import mock
        calls = []
        with mock.patch.dict(os.environ, {"KUMO_FORECAST_WARM_TABLES": " g.apol1 , p.d.t,"}):
            self.serve.warm(types.SimpleNamespace(warm=lambda extra: calls.append(extra) or ["warmed d"]))
        with mock.patch.dict(os.environ, {"KUMO_FORECAST_WARM_TABLES": ""}):
            self.serve.warm(types.SimpleNamespace(warm=lambda extra: calls.append(extra) or ["d"]))
        self.assertEqual(calls, [["g.apol1", "p.d.t"], []])

        tries = []

        def locked_on_the_third_look(extra):
            tries.append(1)
            if len(tries) < 3:
                raise ValueError("no locked cohort yet: lock one in the cohort designer first")
            return ["warmed d"]
        self.serve.warm(types.SimpleNamespace(warm=locked_on_the_third_look), poll_s=0.01)
        self.assertEqual(len(tries), 3, "with nothing locked it looks again until a cohort is")

        def broken(extra):
            raise RuntimeError("BigQuery is down")
        self.serve.warm(types.SimpleNamespace(warm=broken), poll_s=0.01)   # does not raise or loop
        self.assertIn("threading.Thread(target=warm, args=(SERVICE,)", (FEATURE / "serve.py").read_text())

    def test_the_wait_is_held_close_to_but_under_the_client_timeout(self):
        serve = (FEATURE / "serve.py").read_text()
        held = int(re.search(r"^WAIT_S = (\d+)$", serve, flags=re.M).group(1))
        self.assertTrue(45 <= held < 60, held)
        self.assertIn(f"wait_s: int = {held})", serve)
        self.assertIn(f"(at most {held})", serve)


class TimeColumnTests(unittest.TestCase):
    def test_a_time_column_must_be_a_date(self):
        cols = [("USUBJID", "STRING"), ("study_day", "INTEGER"), ("visit_date", "DATE")]
        self.assertEqual(schema.time_column(cols, "visit_date"), "visit_date")
        with self.assertRaisesRegex(schema.SchemaError, "'study_day' is INTEGER, not a DATE"):
            schema.time_column(cols, "study_day")


class OutcomeTests(unittest.TestCase):
    """The outcome as the agent describes it: checked against the schema, sent as parameters."""

    def parse(self, spec):
        return outcome.parse(spec, OMOP_SCHEMAS, "person_id")

    def test_a_diagnosis_is_the_first_row_with_one_of_its_codes(self):
        o = self.parse(CKD3)
        self.assertEqual((o.table, o.time_column), ("condition_occurrence", "condition_start_date"))
        sql, params = outcome.query(o, "person_id")
        self.assertEqual(sql, "SELECT `person_id` AS `person_id`, MIN(`condition_start_date`) AS outcome_date "
                              "FROM `wb-data-1234`.`omop`.`condition_occurrence` WHERE `person_id` IS NOT NULL "
                              "AND `condition_start_date` IS NOT NULL AND `condition_concept_id` IN UNNEST(@v0) "
                              "GROUP BY `person_id`")
        self.assertEqual(params, [("v0", "INT64", [443597], True)])
        self.assertEqual(o.describe({"443597": "Chronic kidney disease stage 3"}),
                         "the first row of condition_occurrence where condition_concept_id in "
                         "[443597 (Chronic kidney disease stage 3)], dated by condition_start_date")

    def test_a_lab_past_a_threshold_holds_every_condition(self):
        o = self.parse({"table": "measurement", "where": [
            {"column": "measurement_concept_id", "op": "=", "value": "3049187"},
            {"column": "value_as_number", "op": "<", "value": 60},
            {"column": "measurement_date", "op": "between", "value": ["2020-01-01", "2025-12-31"]}]})
        sql, params = outcome.query(o, "person_id")
        self.assertIn("`measurement_concept_id` = @v0 AND `value_as_number` < @v1 AND "
                      "`measurement_date` BETWEEN @v2_lo AND @v2_hi", sql)
        from datetime import date
        self.assertEqual(params, [("v0", "INT64", 3049187, False), ("v1", "FLOAT64", 60.0, False),
                                  ("v2_lo", "DATE", date(2020, 1, 1), False),
                                  ("v2_hi", "DATE", date(2025, 12, 31), False)])

    def test_a_table_with_no_conditions_is_any_row(self):
        o = self.parse({"table": "death"})
        self.assertEqual(o.time_column, "death_date")
        self.assertNotIn("@", outcome.query(o, "person_id")[0])
        self.assertEqual(o.describe(), "the first row of death, dated by death_date")

    def test_the_time_column_can_be_named_and_must_be_a_date(self):
        o = self.parse({"table": "measurement", "time_column": "measurement_date"})
        self.assertEqual(o.time_column, "measurement_date")
        with self.assertRaisesRegex(schema.SchemaError, "'value_as_number' is FLOAT, not a DATE"):
            self.parse({"table": "measurement", "time_column": "value_as_number"})

    def test_what_is_not_in_the_schema_is_refused_by_name(self):
        cases = [
            ({"table": "diagnoses"}, "'diagnoses' is not in the cohort's dataset; tables with person_id: person, "
                                     "condition_occurrence, measurement, death"),
            ({"table": "concept"}, "concept has no person_id column"),
            ({"table": "person"}, "person has no DATE, DATETIME or TIMESTAMP column"),
            ({"table": "death", "where": [{"column": "cause; DROP", "op": "=", "value": 1}]},
             "'cause; DROP' is not a column of death"),
            ({"table": "death", "where": [{"column": "death_date", "op": "LIKE", "value": "x"}]},
             "op 'LIKE' is not one of in"),
            ({"table": "death", "sql": "SELECT 1"}, "unknown fields sql"),
            ("condition_occurrence", "outcome is an object"),
        ]
        for spec, message in cases:
            with self.assertRaisesRegex(outcome.OutcomeError, re.escape(message)):
                self.parse(spec)

    def test_values_must_fit_their_column_and_operator(self):
        def where(column, op, value):
            return {"table": "measurement" if column != "condition_source_value" else "condition_occurrence",
                    "where": [{"column": column, "op": op, "value": value}]}
        cases = [
            (where("measurement_concept_id", "in", []), "a non-empty list"),
            (where("measurement_concept_id", "in", ["3049187; --"]), "is not a whole number"),
            (where("measurement_concept_id", "=", True), "is not a whole number"),
            (where("measurement_concept_id", "=", [1, 2]), "use in for a list"),
            (where("value_as_number", "between", [1]), "takes [low, high]"),
            (where("value_as_number", "<", "sixty"), "is not a number"),
            (where("condition_source_value", "<", "N18"), "a text column takes op in, = or !="),
            (where("abnormal", "<", True), "a true/false column takes op = or !="),
            (where("measurement_date", ">", "last year"), "is not an ISO date"),
            (where("measurement_concept_id", "in", list(range(outcome.MAX_VALUES + 1))), "at most 1000 values"),
        ]
        for spec, message in cases:
            with self.assertRaisesRegex(outcome.OutcomeError, re.escape(message)):
                self.parse(spec)
        too_many = {"table": "death", "where": [{"column": "death_date", "op": ">", "value": "2020-01-01"}] * 11}
        with self.assertRaisesRegex(outcome.OutcomeError, "at most 10"):
            self.parse(too_many)

    def test_text_codes_are_sent_as_text(self):
        o = self.parse({"table": "condition_occurrence",
                        "where": [{"column": "condition_source_value", "op": "in", "value": ["N18.3", 585]}]})
        self.assertEqual(outcome.query(o, "person_id")[1], [("v0", "STRING", ["N18.3", "585"], True)])


class KeyedTablesTests(unittest.TestCase):
    def test_get_cohort_info_shows_at_most_twenty_columns_a_table_and_says_how_many_more(self):
        try:
            import pandas  # noqa: F401 - tables reads with pandas
        except ImportError:
            self.skipTest("needs pandas")
        from kumo_forecast import tables
        wide = [("person_id", "INTEGER"), ("visit_date", "DATE")] + [(f"q{i}", "STRING") for i in range(126)]
        schemas = {"WIDE": {"num_rows": 2502, "columns": wide},
                   "NARROW": {"num_rows": 10, "columns": [("person_id", "INTEGER"), ("x", "STRING")]}}
        keyed = {t["table"]: t for t in tables.describe_keyed(schemas, "person_id")}
        self.assertEqual(len(keyed["WIDE"]["columns"]), tables.SHOWN_COLUMNS)
        self.assertEqual(keyed["WIDE"]["more_columns"], 128 - tables.SHOWN_COLUMNS)
        self.assertEqual(keyed["WIDE"]["time_column"], "visit_date")
        self.assertEqual(keyed["NARROW"]["columns"], ["person_id", "x"])
        self.assertNotIn("more_columns", keyed["NARROW"])


class PrivacyTests(unittest.TestCase):
    def test_small_counts_are_masked(self):
        self.assertEqual(privacy.count(0, 20), 0)
        self.assertEqual(privacy.count(7, 20), "<20")
        self.assertEqual(privacy.count(20, 20), 20)

    def test_rates_on_small_counts_and_small_groups_are_masked(self):
        self.assertEqual(privacy.rate(300, 1000, 20), "30.0%")
        self.assertEqual(privacy.rate(8, 1000, 20), "<2.0%")
        self.assertEqual(privacy.rate(995, 1000, 20), ">98.0%")
        self.assertTrue(privacy.rate(5, 20, 20).startswith("masked"))

    def test_masking_can_be_turned_off(self):
        self.assertEqual(privacy.count(7, 0), 7)
        self.assertEqual(privacy.rate(5, 20, 0), "25.0%")

    def test_a_count_that_is_part_of_a_total_is_masked_when_either_side_is_small(self):
        self.assertEqual(privacy.count_of(0, 1000, 20), 0)
        self.assertEqual(privacy.count_of(1, 1000, 20), "<20")
        self.assertEqual(privacy.count_of(19, 1000, 20), "<20")
        self.assertEqual(privacy.count_of(20, 1000, 20), 20)
        self.assertEqual(privacy.count_of(1000, 1000, 20), 1000)     # nobody is left out
        self.assertEqual(privacy.count_of(981, 1000, 20), ">980")    # 19 without
        self.assertEqual(privacy.count_of(980, 1000, 20), 980)       # 20 without
        self.assertEqual(privacy.count_of(999, 1000, 20), ">980")

    def test_a_count_that_is_part_of_a_total_is_shown_when_masking_is_off(self):
        self.assertEqual(privacy.count_of(5, 1000, 0), 5)
        self.assertEqual(privacy.count_of(995, 1000, 0), 995)

    def test_one_masked_group_rate_masks_the_next_smallest_too(self):
        # 800 members, 200 a group; events 7, 40, 60, 90: the 7 would be 197 - 190 from the total
        got = privacy.rates([(7, 200), (40, 200), (60, 200), (90, 200)], 20)
        self.assertEqual(got[0], "<10.0%")
        self.assertEqual(got[1], "<30.0%")           # 40 is under the next multiple of 20, 60
        self.assertEqual(got[2:], ["30.0%", "45.0%"])

    def test_one_group_masked_for_small_non_events_masks_the_next_fewest_non_events(self):
        got = privacy.rates([(185, 200), (150, 200), (100, 200), (50, 200)], 20)
        # 15 without the outcome; the group with 50 without is under 60
        self.assertEqual(got, [">90.0%", ">70.0%", "50.0%", "25.0%"])

    def test_groups_with_two_masked_rates_or_none_are_left_as_rate_gives_them(self):
        both = [(7, 200), (9, 200), (60, 200), (90, 200)]
        self.assertEqual(privacy.rates(both, 20), [privacy.rate(e, t, 20) for e, t in both])
        none = [(40, 200), (60, 200), (80, 200), (90, 200)]
        self.assertEqual(privacy.rates(none, 20), [privacy.rate(e, t, 20) for e, t in none])

    def test_group_rates_are_exact_when_masking_is_off(self):
        self.assertEqual(privacy.rates([(7, 200), (40, 200), (60, 200), (90, 200)], 0),
                         ["3.5%", "20.0%", "30.0%", "45.0%"])


SCHEMAS = {
    "person": {"num_rows": 100, "columns": [("person_id", "INTEGER"), ("gender_concept_id", "INTEGER"),
                                            ("birth_datetime", "TIMESTAMP"), ("year_of_birth", "INTEGER")]},
    "measurement": {"num_rows": 5_000, "columns": [
        ("measurement_id", "INTEGER"), ("person_id", "INTEGER"), ("measurement_concept_id", "INTEGER"),
        ("measurement_type_concept_id", "INTEGER"), ("measurement_date", "DATE"), ("value_as_number", "FLOAT"),
        ("value_source_value", "STRING")]},
    "visit_occurrence": {"num_rows": 800, "columns": [
        ("visit_occurrence_id", "INTEGER"), ("person_id", "INTEGER"), ("visit_end_date", "DATE"),
        ("visit_start_date", "DATE")]},
    "notes": {"num_rows": 9, "columns": [("person_id", "INTEGER"), ("created", "DATE"), ("updated", "DATE")]},
    "concept": {"num_rows": 10, "columns": [("concept_id", "INTEGER"), ("concept_name", "STRING")]},
}


class SchemaChoiceTests(unittest.TestCase):
    def test_tables_are_the_ones_with_the_entity_key(self):
        self.assertEqual(schema.tables_with_key(SCHEMAS, "person_id"), ["person", "measurement", "visit_occurrence", "notes"])
        self.assertEqual(schema.tables_with_key(SCHEMAS, "visit_occurrence_id"), ["visit_occurrence"])

    def test_the_time_column_is_the_only_date_column(self):
        self.assertEqual(schema.time_column(SCHEMAS["measurement"]["columns"]), "measurement_date")
        self.assertEqual(schema.time_column(SCHEMAS["person"]["columns"]), "birth_datetime")

    def test_with_several_the_one_named_start_wins_else_the_first(self):
        self.assertEqual(schema.time_column(SCHEMAS["visit_occurrence"]["columns"]), "visit_start_date")
        self.assertEqual(schema.time_column(SCHEMAS["notes"]["columns"]), "created")

    def test_a_table_with_no_date_column_is_static(self):
        self.assertIsNone(schema.time_column([("person_id", "INTEGER"), ("sex", "STRING")]))

    def test_an_override_wins_and_must_name_a_column(self):
        self.assertEqual(schema.time_column(SCHEMAS["notes"]["columns"], "updated"), "updated")
        with self.assertRaisesRegex(schema.SchemaError, "not a column"):
            schema.time_column(SCHEMAS["notes"]["columns"], "nope")
        chosen = schema.time_columns(SCHEMAS, ["notes", "person"], {"notes": "updated"})
        self.assertEqual(chosen, {"notes": "updated", "person": "birth_datetime"})
        with self.assertRaisesRegex(schema.SchemaError, "not tables"):
            schema.time_columns(SCHEMAS, ["notes"], {"nowhere": "x"})

    def test_code_columns_are_integer_or_string_named_like_codes(self):
        cols = SCHEMAS["measurement"]["columns"]
        self.assertEqual(schema.code_columns(cols, "person_id", "measurement_date"),
                         ["measurement_concept_id", "measurement_type_concept_id"])
        self.assertEqual(schema.code_columns([("person_id", "INTEGER"), ("icd_code", "STRING"), ("barcode", "STRING"),
                                              ("note", "STRING"), ("start_code", "FLOAT")], "person_id", None),
                         ["icd_code", "barcode"])

    def test_the_value_column_is_a_numeric_one_named_value(self):
        cols = SCHEMAS["measurement"]["columns"]
        self.assertEqual(schema.value_column(cols, "person_id", "measurement_concept_id"), "value_as_number")
        self.assertIsNone(schema.value_column(SCHEMAS["visit_occurrence"]["columns"], "person_id"))

    def test_frequent_codes_need_half_a_percent_and_stop_at_twenty(self):
        counts = {i: 100 - i for i in range(30)} | {"rare": 1}
        got = schema.frequent_codes(counts)
        self.assertEqual(len(got), 20)
        self.assertEqual(got[:3], [0, 1, 2])
        self.assertEqual(schema.frequent_codes({"a": 990, "b": 6, "c": 4}), ["a", "b"])
        self.assertEqual(schema.frequent_codes({}), [])

    def test_a_split_table_is_named_for_its_table_and_code(self):
        self.assertEqual(schema.split_name("measurement", 3004249), "measurement__3004249")
        self.assertEqual(schema.split_name("lab", "a b/c"), "lab__a_b_c")
        self.assertEqual(schema.display_name(3004249, {"3004249": "Systolic BP"}), "Systolic BP")
        self.assertEqual(schema.display_name(7, {}), "7")
        self.assertEqual(schema.concept_table(SCHEMAS), "concept")
        self.assertIsNone(schema.concept_table({"person": SCHEMAS["person"]}))

    def test_no_choice_means_every_table_with_the_key(self):
        self.assertEqual(schema.choose_tables(SCHEMAS, "person_id", None),
                         ["person", "measurement", "visit_occurrence", "notes"])

    def test_chosen_tables_are_exactly_what_is_read(self):
        self.assertEqual(schema.choose_tables(SCHEMAS, "person_id", ["notes", "person", "notes"]), ["notes", "person"])

    def test_an_unknown_table_or_one_without_the_key_is_refused_by_name(self):
        with self.assertRaisesRegex(schema.SchemaError, "tables nope are not in the dataset"):
            schema.choose_tables(SCHEMAS, "person_id", ["person", "nope"])
        with self.assertRaisesRegex(schema.SchemaError, "tables concept have no person_id column"):
            schema.choose_tables(SCHEMAS, "person_id", ["concept"])

    def test_the_size_guard_refuses_with_the_total_and_the_largest_tables(self):
        self.assertEqual(schema.size_guard(SCHEMAS, ["person", "measurement"], 10_000), 5_100)
        with self.assertRaises(schema.SchemaError) as err:
            schema.size_guard(SCHEMAS, ["person", "measurement", "visit_occurrence"], 5_000)
        message = str(err.exception)
        self.assertIn("5,900 rows", message)
        self.assertIn("measurement (5,000)", message)
        self.assertLess(message.index("measurement (5,000)"), message.index("visit_occurrence (800)"))

    def test_the_limit_defaults_to_fifty_million_and_follows_the_environment(self):
        import os
        old = os.environ.pop("KUMO_FORECAST_MAX_ROWS", None)
        try:
            self.assertEqual(schema.max_rows(), 50_000_000)
            os.environ["KUMO_FORECAST_MAX_ROWS"] = "123"
            self.assertEqual(schema.max_rows(), 123)
        finally:
            os.environ.pop("KUMO_FORECAST_MAX_ROWS", None)
            if old is not None:
                os.environ["KUMO_FORECAST_MAX_ROWS"] = old

    def test_a_primary_key_is_the_tables_own_id_when_unique_in_the_first_rows(self):
        cols = SCHEMAS["measurement"]["columns"]
        self.assertEqual(schema.primary_key("measurement", cols, [1, 2, 3]), "measurement_id")
        self.assertIsNone(schema.primary_key("measurement", cols, [1, 2, 2]))
        self.assertIsNone(schema.primary_key("measurement", cols, [1, None]))
        self.assertIsNone(schema.primary_key("notes", SCHEMAS["notes"]["columns"], None))

    def test_the_entity_table_is_the_static_table_unique_on_the_key_else_none(self):
        static = ["person", "extra"]
        schemas = {"person": SCHEMAS["person"], "extra": {"num_rows": 1, "columns": [("person_id", "INTEGER")]}}
        self.assertEqual(schema.entity_table(static, {"person": True, "extra": True}, schemas), "person")
        self.assertEqual(schema.entity_table(static, {"person": False, "extra": True}, schemas), "extra")
        self.assertIsNone(schema.entity_table(static, {"person": False, "extra": False}, schemas))


class DestinationTests(unittest.TestCase):
    RESOURCES = [
        {"id": "outputs", "resourceType": "GCS_BUCKET", "stewardshipType": "CONTROLLED", "bucketName": "ws-outputs"},
        {"id": "scratch", "resourceType": "GCS_BUCKET", "stewardshipType": "CONTROLLED", "bucketName": "ws-scratch"},
        {"id": "data", "resourceType": "GCS_BUCKET", "stewardshipType": "REFERENCED", "bucketName": "someone-elses"},
        {"id": "ds", "resourceType": "BQ_DATASET", "stewardshipType": "CONTROLLED", "datasetId": "x"},
    ]

    def test_only_controlled_buckets_count(self):
        self.assertEqual(destination.controlled_buckets(self.RESOURCES), {"ws-outputs": "outputs", "ws-scratch": "scratch"})

    def test_a_file_in_a_controlled_bucket_is_accepted(self):
        self.assertEqual(destination.check_destination("gs://ws-outputs/risk/top16.csv", self.RESOURCES),
                         ("ws-outputs", "risk/top16.csv"))

    def test_a_referenced_or_unknown_bucket_is_refused_naming_the_controlled_ones(self):
        for bad in ("gs://someone-elses/risk.csv", "gs://nowhere/risk.csv"):
            with self.assertRaisesRegex(ValueError, "gs://ws-outputs, gs://ws-scratch"):
                destination.check_destination(bad, self.RESOURCES)

    def test_a_destination_that_is_not_a_file_url_is_refused(self):
        for bad in ("ws-outputs/risk.csv", "https://ws-outputs/risk.csv", "gs://ws-outputs", "gs://ws-outputs/",
                    "gs://ws-outputs/folder/", "gs://ws-outputs/../other/x.csv", None):
            with self.assertRaises(ValueError, msg=bad):
                destination.check_destination(bad, self.RESOURCES)

    def test_the_resource_listing_is_run_with_wb_and_an_empty_answer_is_a_failure(self):
        import os
        import stat
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            wb = Path(tmp) / "wb"
            wb.write_text("#!/bin/sh\nexit 0\n")
            wb.chmod(wb.stat().st_mode | stat.S_IEXEC)
            old = os.environ["PATH"]
            os.environ["PATH"] = tmp + os.pathsep + old
            try:
                with self.assertRaisesRegex(ValueError, "cannot list the workspace's resources"):
                    destination.workspace_resources()
                wb.write_text("#!/bin/sh\necho '[{\"resourceType\": \"GCS_BUCKET\"}]'\n")
                self.assertEqual(destination.workspace_resources(), [{"resourceType": "GCS_BUCKET"}])
            finally:
                os.environ["PATH"] = old


class AppTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())

    def test_the_sandbox_reaches_the_server_on_a_published_loopback_port(self):
        self.assertIn("127.0.0.1:9244:9244", self.compose["services"]["app"]["ports"])
        for service in ("app", "sandbox-broker"):
            servers = self.compose["services"][service]["environment"]["AGENT_MCP_SERVERS"].split()
            self.assertIn(f"forecast={URL}", servers, service)
        feature = json.loads((APP / ".devcontainer.json").read_text())["features"]["./.devcontainer/features/kumo-forecast"]
        self.assertEqual(feature, {"username": "abc", "userHomeDir": "/config", "bindAddress": "0.0.0.0"})

    def test_the_app_names_no_dataset_or_outcome_for_the_forecast_server(self):
        env = self.compose["services"]["app"]["environment"]
        self.assertNotIn("KUMO_FORECAST_DATASET", env)
        start = (APP / "start-services.sh").read_text()
        self.assertNotIn("KUMO_FORECAST_DATASET", start)
        self.assertNotIn("--warm", (FEATURE / "serve.py").read_text())

    def test_the_broker_image_carries_the_catalog_and_not_the_model(self):
        dockerfile = (APP / "broker" / "Dockerfile").read_text()
        self.assertIn("COPY .devcontainer/features/kumo-forecast/sandbox ", dockerfile)
        self.assertIn("ROLE=broker bash /tmp/features/kumo-forecast/install.sh", dockerfile)
        self.assertNotIn("kumo-forecast/kumo_forecast", dockerfile)

    def test_the_app_starts_the_server_after_the_designer(self):
        start = (APP / "start-services.sh").read_text()
        self.assertLess(start.index("/opt/cohort-designer/start-server.sh"), start.index("/opt/kumo-forecast/start-server.sh"))

    def test_install_keeps_the_model_out_of_the_users_home_and_runs_offline(self):
        install = (FEATURE / "install.sh").read_text()
        self.assertIn('readonly INSTALL_DIR="/opt/kumo-forecast"', install)
        self.assertIn("HF_HUB_OFFLINE=1", install)
        # The weights are cached by building the model online before the offline check, so the
        # cache holds the revision the package pins; a snapshot of the default revision did not.
        self.assertNotIn("snapshot_download", install)
        online = install.index('HF_HUB_CACHE="${INSTALL_DIR}/hf" "${INSTALL_DIR}/venv/bin/python" -W ignore -c')
        offline = install.index("HF_HUB_OFFLINE=1")
        self.assertLess(online, offline)
        req = (FEATURE / "requirements.txt").read_text()
        torch = re.search(r"^torch==(\d+)\.(\d+)", req, flags=re.M).groups()
        self.assertIn(f"+pt{''.join(torch)}cpu", req)
        self.assertIn(f"torch-{torch[0]}.{torch[1]}.0+cpu.html", install)


class GraphTests(unittest.TestCase):
    """dataset.build and dataset.tasks over small frames (needs pandas; skipped without it)."""

    def setUp(self):
        try:
            import pandas
        except ImportError:
            self.skipTest("needs pandas")
        self.pd = pandas
        from kumo_forecast import dataset
        self.dataset = dataset

    def frames(self, with_person=True):
        pd = self.pd
        n = 400
        raw = {
            "measurement": pd.DataFrame({
                "measurement_id": range(n), "person_id": [i % 50 for i in range(n)],
                "measurement_concept_id": [1 if i % 2 else 2 if i % 7 else 3 for i in range(n)],
                "measurement_date": pd.to_datetime("2020-01-01") + pd.to_timedelta([i for i in range(n)], unit="D"),
                "value_as_number": [float(i) for i in range(n)]}),
            "visit": pd.DataFrame({"person_id": [1, 1, 2], "visit_start_date": pd.to_datetime(["2019-05-01"] * 3)}),
        }
        schemas = {
            "measurement": {"num_rows": n, "columns": [("measurement_id", "INTEGER"), ("person_id", "INTEGER"),
                                                       ("measurement_concept_id", "INTEGER"), ("measurement_date", "DATE"),
                                                       ("value_as_number", "FLOAT")]},
            "visit": {"num_rows": 3, "columns": [("person_id", "INTEGER"), ("visit_start_date", "DATE")]},
        }
        if with_person:
            raw["person"] = pd.DataFrame({"person_id": range(50), "sex": ["F", "M"] * 25})
            schemas["person"] = {"num_rows": 50, "columns": [("person_id", "INTEGER"), ("sex", "STRING")]}
        time = {n: schema.time_column(s["columns"]) for n, s in schemas.items()}
        return raw, schemas, time

    def build(self, with_person=True, **kw):
        raw, schemas, time = self.frames(with_person)
        kw.setdefault("today", self.pd.Timestamp("2030-01-01"))
        return self.dataset.build(raw, schemas, "person_id", time, **kw)

    def test_a_static_table_unique_on_the_key_is_the_entity_table(self):
        ds = self.build()
        self.assertEqual((ds.entity, ds.built_entity_table), ("person", False))
        self.assertEqual(ds.tables_read()["entity_table"], "person")

    def test_without_one_the_entity_table_is_built_from_the_distinct_keys(self):
        ds = self.build(with_person=False)
        self.assertTrue(ds.built_entity_table)
        self.assertEqual(len(ds.frames[ds.entity]), 50)
        self.assertEqual(ds.tables_read()["entity_table"], "built from the distinct keys")

    def test_a_dated_table_with_a_value_and_a_code_is_split_by_its_frequent_codes(self):
        ds = self.build(vocabulary={"1": "Glucose"})
        self.assertEqual(sorted(ds.split), ["measurement__1", "measurement__2", "measurement__3"])
        self.assertEqual(ds.split["measurement__1"]["name"], "Glucose")
        self.assertNotIn("measurement_concept_id", ds.frames["measurement__1"])
        self.assertEqual(len(ds.frames["measurement"]), 0)
        self.assertEqual(ds.pk["measurement__1"], "measurement_id")
        self.assertEqual(ds.time["measurement__1"], "measurement_date")

    def test_a_table_with_no_own_id_gets_a_row_number(self):
        ds = self.build()
        self.assertEqual(ds.pk["visit"], self.dataset.ROW)
        self.assertIn(self.dataset.ROW, ds.frames["visit"])

    def test_the_data_end_is_the_latest_date_capped_at_today(self):
        raw, schemas, time = self.frames()
        ds = self.dataset.build(raw, schemas, "person_id", time, today=self.pd.Timestamp("2030-01-01"))
        self.assertEqual(ds.data_end, raw["measurement"].measurement_date.max())
        ds = self.dataset.build(raw, schemas, "person_id", time, today=self.pd.Timestamp("2020-06-30"))
        self.assertEqual(ds.data_end, self.pd.Timestamp("2020-06-30"))

    def test_a_string_column_of_file_locations_is_dropped_by_value(self):
        pd = self.pd
        from kumo_forecast import tables
        df = pd.DataFrame({"person_id": [1, 2], "where": ["gs://b/a.cram", "gs://b/c.cram"], "sex": ["F", "M"]})
        kept, cols = tables.compact(df, "person_id")
        self.assertEqual(cols, ["person_id", "sex"])

    def test_a_member_is_at_risk_with_a_record_by_the_cutoff_and_no_outcome_yet(self):
        pd = self.pd
        ds = self.build()
        first = pd.Series(pd.to_datetime(["2020-02-01", "2019-01-01"]), index=[3, 4])
        rows = self.dataset.tasks(ds, first, pd.Timestamp("2020-01-20"), 30)
        # persons 0..19 have a measurement by 2020-01-20; 4 already had the outcome; 3's comes in 13 days
        self.assertEqual(sorted(rows.person_id)[:5], [0, 1, 2, 3, 5])
        label = dict(zip(rows.person_id, rows[self.dataset.TARGET]))
        self.assertEqual((label[3], label[5]), ("1", "0"))
        self.assertNotIn(4, label)
        none = self.dataset.tasks(ds, first, pd.Timestamp("2019-01-01"), 30)
        self.assertEqual(len(none), 0)

    def test_an_observation_period_table_decides_who_is_at_risk(self):
        pd = self.pd
        raw, schemas, time = self.frames()
        raw["observation_period"] = pd.DataFrame({
            "person_id": [1, 2], "observation_period_start_date": pd.to_datetime(["2018-01-01", "2018-01-01"]),
            "observation_period_end_date": pd.to_datetime(["2030-01-01", "2019-01-01"])})
        schemas["observation_period"] = {"num_rows": 2, "columns": [
            ("person_id", "INTEGER"), ("observation_period_start_date", "DATE"), ("observation_period_end_date", "DATE")]}
        time["observation_period"] = "observation_period_start_date"
        ds = self.dataset.build(raw, schemas, "person_id", time, today=pd.Timestamp("2030-01-01"))
        rows = self.dataset.tasks(ds, pd.Series(dtype="datetime64[ns]"), pd.Timestamp("2020-06-01"), 30)
        self.assertEqual(list(rows.person_id), [1])


def _graph(pd):
    """A small graph: 50 people with dated measurements from 2020 (codes 1-3, one missing), a
    visit table with no own id, and a person table with a code column holding a missing value."""
    from kumo_forecast import dataset
    n = 400
    raw = {
        "measurement": pd.DataFrame({
            "measurement_id": range(n), "person_id": [i % 50 for i in range(n)],
            "measurement_concept_id": [1 if i % 2 else 2 if i % 7 else 3 for i in range(n)],
            "measurement_date": pd.to_datetime("2020-01-01") + pd.to_timedelta(list(range(n)), unit="D"),
            "value_as_number": [float(i) for i in range(n)]}),
        "visit": pd.DataFrame({"person_id": [1, 1, 2], "visit_start_date": pd.to_datetime(["2019-05-01"] * 3)}),
        "person": pd.DataFrame({"person_id": range(50), "race_concept_id": [None] + [8527.0] * 49}),
    }
    schemas = {
        "measurement": {"num_rows": n, "columns": [("measurement_id", "INTEGER"), ("person_id", "INTEGER"),
                                                   ("measurement_concept_id", "INTEGER"), ("measurement_date", "DATE"),
                                                   ("value_as_number", "FLOAT")]},
        "visit": {"num_rows": 3, "columns": [("person_id", "INTEGER"), ("visit_start_date", "DATE")]},
        "person": {"num_rows": 50, "columns": [("person_id", "INTEGER"), ("race_concept_id", "INTEGER")]},
    }
    time = {t: schema.time_column(s["columns"]) for t, s in schemas.items()}
    return raw, dataset.build(dict(raw), schemas, "person_id", time, today=pd.Timestamp("2030-01-01"))


def _fake_model_packages(fail: bool = False):
    """Stand-ins for sdm and torch: enough for Forecaster to build its graph on a CPU, and, with
    ``fail``, to fail on the second table as an out-of-memory error would."""
    import types

    class TableTensor:
        built = []

        @staticmethod
        def from_pandas(df, stypes=None):
            TableTensor.built.append(df)
            if fail and len(TableTensor.built) == 2:
                raise RuntimeError("CUDA out of memory")
            return types.SimpleNamespace(df=df)

    data = types.SimpleNamespace(sampler=lambda time_columns: None)
    sdm = types.SimpleNamespace(
        TableTensor=TableTensor, infer_stypes=lambda df, **kw: {},
        RelationalData=lambda tables, relationships: data,
        models=types.SimpleNamespace(KumoRelational=lambda device: None))
    torch = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False),
                                  device=lambda name: types.SimpleNamespace(type=name))
    return {"sdm": sdm, "torch": torch}


class ForecasterTests(unittest.TestCase):
    """model.Forecaster with stand-ins for its packages (needs pandas; skipped without it)."""

    def setUp(self):
        try:
            import pandas
        except ImportError:
            self.skipTest("needs pandas")
        self.pd = pandas
        from kumo_forecast import model
        self.model = model

    def forecaster(self):
        from unittest import mock
        raw, ds = _graph(self.pd)
        with mock.patch.dict(sys.modules, _fake_model_packages()):
            return raw, ds, self.model.Forecaster(ds)

    def test_a_failed_build_leaves_the_cached_dataset_whole(self):
        raw, ds = _graph(self.pd)
        before = dict(ds.frames)
        from unittest import mock
        with mock.patch.dict(sys.modules, _fake_model_packages(fail=True)):
            with self.assertRaises(RuntimeError):
                self.model.Forecaster(ds)
        self.assertEqual(list(ds.frames), list(before))
        for name, df in before.items():
            self.assertIs(ds.frames[name], df)

    def test_a_build_converts_codes_on_copies_and_leaves_the_tables_as_read(self):
        raw, ds, _ = self.forecaster()
        self.assertEqual(ds.frames, {})
        self.assertTrue(ds.raw["person"].race_concept_id.isna().iloc[0])
        self.assertNotIn("nan", ds.raw["person"].race_concept_id.astype(object).tolist())
        from kumo_forecast import dataset
        self.assertNotIn(dataset.ROW, raw["visit"])

    def _run(self, onsets, members=None):
        pd = self.pd
        _, ds, fc = self.forecaster()
        first = pd.Series(pd.to_datetime([d for _, d in onsets]), index=[p for p, _ in onsets])
        if members is None:
            members = pd.DataFrame({"person_id": range(50)})
        with self.assertRaises(ValueError) as caught:
            fc.run(first, members, pd.Timestamp("2026-01-01"), 365)
        return str(caught.exception)

    def test_too_few_cases_does_not_name_a_small_count(self):
        message = self._run([(p, "2022-06-01") for p in range(5)])
        self.assertIn("too few cases", message)
        self.assertIn("<20 in the population", message)

    def test_no_member_at_risk_does_not_name_small_counts(self):
        pd = self.pd
        members = pd.DataFrame({"person_id": range(35, 50), "index_date": pd.Timestamp("2030-01-01")})
        message = self._run([(p, "2022-06-01") for p in range(12)], members)
        self.assertIn("none of the cohort's <20 members", message)
        self.assertNotRegex(message, r"\b15\b")


class ProfileTests(unittest.TestCase):
    def setUp(self):
        try:
            import pandas
        except ImportError:
            self.skipTest("needs pandas")
        self.pd = pandas
        from kumo_forecast import profile
        self.profile = profile

    def test_a_median_over_fewer_than_the_threshold_is_left_out(self):
        pd = self.pd
        self.assertIsNone(self.profile._median(pd.Series([1.0] * 19 + [None] * 30)))
        self.assertEqual(self.profile._median(pd.Series([2.0] * 20 + [None])), 2.0)
        self.assertIsNone(self.profile._median(pd.Series([None, None])))

    def test_the_top_tenth_of_a_small_forecast_shows_no_median(self):
        pd = self.pd
        _, ds = _graph(pd)
        scores = pd.DataFrame({"person_id": range(50), "risk": [i / 50 for i in range(50)]})
        rows = self.profile.high_risk_profile(ds, scores, pd.Timestamp("2021-06-01"))
        medians = [r for r in rows if r["characteristic"].startswith("median latest")]
        self.assertTrue(medians)
        for r in medians:
            self.assertIsNone(r["top_10pct"])     # 5 people


    def test_race_and_ethnicity_are_not_described(self):
        pd = self.pd
        _, ds = _graph(pd)
        scores = pd.DataFrame({"person_id": range(50), "risk": [i / 50 for i in range(50)]})
        with self.subTest("the fixture's person table has only a race column"):
            rows = self.profile.high_risk_profile(ds, scores, pd.Timestamp("2021-06-01"))
            self.assertFalse([r for r in rows if r["characteristic"].startswith("race")], rows)
        with self.subTest("a person table dated by birth, whose code column is race"):
            people = pd.DataFrame({"person_id": range(50), "birth_datetime": pd.to_datetime("1970-01-01"),
                                   "race_concept_id": [8516 if i < 25 else 8527 for i in range(50)]})
            raw = {"person": people}
            schemas = {"person": {"num_rows": 50, "columns": [("person_id", "INTEGER"), ("birth_datetime", "DATETIME"),
                                                              ("race_concept_id", "INTEGER")]}}
            time = {"person": "birth_datetime"}
            from kumo_forecast import dataset
            dated = dataset.build(dict(raw), schemas, "person_id", time, today=pd.Timestamp("2030-01-01"))
            self.assertEqual(dated.codes, {"person": "race_concept_id"})
            rows = self.profile.high_risk_profile(dated, scores, pd.Timestamp("2021-06-01"))
            self.assertFalse([r for r in rows if "race" in r["characteristic"]], rows)
        for name in ("race", "race_concept_id", "ethnicity", "ethnicity_concept_id", "RACE", "patient_race", "ETHNIC_GROUP"):
            self.assertTrue(self.profile.SENSITIVE.search(name), name)
        for name in ("gender", "sex_at_birth", "gender_concept_id", "trace_id", "grace_period_days"):
            self.assertIsNone(self.profile.SENSITIVE.search(name), name)


class ViewTests(unittest.TestCase):
    """The ready answers for showing records, genomes and a VCF (kumo_forecast.views)."""

    def setUp(self):
        try:
            import pandas
        except ImportError:
            self.skipTest("needs pandas")
        self.pd = pandas
        from kumo_forecast import views
        self.views = views

    def test_a_timeline_names_codes_with_dates_and_counts_and_lists_values(self):
        pd = self.pd
        _, ds = _graph(pd)
        t = self.views.timeline(ds, 1)
        self.assertIn("measurement", t)
        first = t["measurement"][0]
        self.assertEqual(set(first), {"what", "first", "last", "times"})
        self.assertTrue(all(isinstance(v["times"], int) for v in t["measurement"] if "times" in v))
        self.assertIn("values", t)
        self.assertRegex(t["values"][0]["first"], r"^[0-9.]+ on 20[0-9]{2}-[0-9]{2}-[0-9]{2}$")
        self.assertNotIn(1, [v for row in t["measurement"] for v in row.values()], "no id in the timeline")

    def test_members_are_picked_from_those_with_a_history_the_same_ones_each_time(self):
        pd = self.pd
        _, ds = _graph(pd)
        members = pd.Series(list(range(50)) + [999])     # 999 has no record
        picked = self.views.pick_members(ds, members, 3)
        self.assertEqual(len(picked), 3)
        self.assertNotIn(999, picked)
        self.assertEqual(picked, self.views.pick_members(ds, members, 3))

    def test_sample_records_need_the_server_switch(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"KUMO_FORECAST_SAMPLE_RECORDS": "0"}):
            self.assertFalse(self.views.sample_records_allowed())
            from kumo_forecast import service
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                svc = service.Service(Path(d) / "s", Path(d) / "state")
                with self.assertRaisesRegex(ValueError, "sample records are off"):
                    svc.cohort_records()
        with mock.patch.dict(os.environ, {"KUMO_FORECAST_SAMPLE_RECORDS": "1"}):
            self.assertTrue(self.views.sample_records_allowed())

    def test_the_manifest_is_counted_over_the_cohorts_genomes(self):
        pd = self.pd
        df = pd.DataFrame({"person_id": [1, 2, 3, 4], "research_id": ["a", "b", "c", "d"],
                           "nominal_coverage": [30, 30, 30, 30], "processing": ["BWA"] * 4,
                           "is_staged": [True, False, False, True], "cram_uri": ["gs://b/a.cram", None, None, "gs://b/d.cram"],
                           "source_sample_id": ["NA1", "NA2", "NA3", "NA4"]})
        out = self.views.manifest_summary(df, "person_id", pd.Series([1, 2, 9]))
        self.assertEqual((out["genomes"], out["of_the_cohort"]), (4, 2))
        self.assertEqual(out["cohort_genomes"]["nominal_coverage"], {"30": 2})
        self.assertEqual(out["cohort_genomes"]["is_staged"], {"True": 1, "False": 1})
        self.assertNotIn("cram_uri", out["cohort_genomes"])
        self.assertNotIn("research_id", out["cohort_genomes"])
        self.assertEqual(self.views.size_estimate([14_400_000_000, 14_600_000_000], 3202),
                         {"files_present": 2, "one_genome_gb": 14.5, "all_genomes_tb_estimated": 46.4})

    def test_the_cohorts_staged_genomes_make_sareks_samplesheet_by_research_id(self):
        pd = self.pd
        df = pd.DataFrame({"person_id": [1, 2, 3, 4], "research_id": ["wgs_4", "wgs_2", "wgs_3", "wgs_1"],
                           "is_staged": [True, True, None, True],
                           "cram_uri": ["gs://b/1.cram", "gs://b/2.cram", None, "gs://b/4.cram"],
                           "crai_uri": ["gs://b/1.crai", "gs://b/2.crai", None, "gs://b/4.crai"]})
        staged = self.views.staged_genomes(df, "person_id", pd.Series([1, 2, 3]))
        self.assertEqual(staged.research_id.tolist(), ["wgs_2", "wgs_4"], "only members, only staged, by research_id")
        sheet = self.views.samplesheet(staged, "person_id", {1: "XX"})
        self.assertEqual(sheet.splitlines(), ["patient,sex,status,sample,cram,crai",
                                              "wgs_2,NA,0,wgs_2,gs://b/2.cram,gs://b/2.crai",
                                              "wgs_4,XX,0,wgs_4,gs://b/1.cram,gs://b/1.crai"])
        self.assertIsNone(self.views.staged_genomes(df.drop(columns=["is_staged"]), "person_id", pd.Series([1])))

    def test_regions_are_parsed_and_a_bad_one_is_refused(self):
        self.assertEqual(self.views.parse_regions("APOL1=chr22:36,245,000-36,275,000; PCSK9=chr1:55030000-55070000"),
                         [("APOL1", "chr22", 36245000, 36275000), ("PCSK9", "chr1", 55030000, 55070000)])
        self.assertEqual(self.views.parse_regions(None), [])
        with self.assertRaisesRegex(ValueError, "is not NAME=chrom:start-end"):
            self.views.parse_regions("APOL1 chr22")

    def test_a_vcf_is_counted_per_region_with_pass_rows_from_the_first(self):
        import gzip
        vcf = "\n".join([
            "##fileformat=VCFv4.2",
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA19657",
            "chr22\t36250000\t.\tG\tA\t51.7\tPASS\t.\tGT:GQ\t1/1:50",
            "chr22\t36251000\t.\tG\tT\t0\tRefCall\t.\tGT:GQ\t0/0:45",
            "chr22\t36252000\t.\tTC\tT\t30.1\tPASS\t.\tGT:GQ\t0/1:30",
            "chr1\t55030322\t.\tT\tC\t25.5\tPASS\t.\tGT:GQ\t0/1:25",
            "chr2\t100\t.\tA\tG\t40\tPASS\t.\tGT:GQ\t0/1:40", ""]).encode()
        regions = self.views.parse_regions("APOL1=chr22:36245000-36275000; PCSK9=chr1:55030000-55070000")
        for data in (vcf, gzip.compress(vcf)):
            out = self.views.vcf_summary(data, regions)
            self.assertEqual((out["records"], out["passed"], out["passed_snps"], out["passed_indels"]), (5, 4, 3, 1))
            self.assertEqual(out["variants_per_region"], {"APOL1": 2, "PCSK9": 1})
            self.assertEqual([r["POS"] for r in out["rows"]], [36250000, 36252000])
            self.assertEqual(out["rows"][0]["GT"], "1/1")
            self.assertEqual(out["sample"], "NA19657")
            self.assertIn("QUAL", out["columns"])


class ViewTableTests(unittest.TestCase):
    """The views' Markdown tables: built in code, so the page shows the same thing every time."""

    def setUp(self):
        from kumo_forecast import views
        self.views = views

    def test_the_records_table_has_a_headline_the_tables_by_name_then_one_row_per_patient(self):
        overview = [{"table": "person", "rows": 25000, "dated_by": "birth_datetime", "columns": ["gender_concept_id"]},
                    {"table": "measurement", "rows": 3355100, "dated_by": "measurement_date", "columns": ["a", "..."]},
                    {"table": "cb_search_person", "rows": 25000, "dated_by": "dob", "columns": []},
                    {"table": "lab_notes", "rows": 7, "dated_by": None, "columns": []}]
        people = [{"label": "Patient 1", "in_the_cohort_from": "2018-12-27",
                   "condition_occurrence": [{"what": "Type 2 diabetes mellitus", "first": "2018-12-27", "last": "2018-12-27", "times": 1}],
                   "drug_exposure": [{"what": "Metformin", "first": "2018-12-27", "last": "2025-12-22", "times": 30}],
                   "values": [{"what": "eGFR | CKD-EPI", "first": "94 on 2016-09-08", "last": "82 on 2025-04-11", "times": 12},
                              {"what": "Glomerular filtration rate/1.73 sq M.predicted [Volume Rate/Area]",
                               "first": "90 on 2016-09-08", "last": "80 on 2025-04-11", "times": 9}]}]
        for t, n in zip(overview, (2388, 300000, 2388, 0)):
            t["cohort_rows"] = n
        table = self.views.records_table(overview, people, 25000, 2388)
        self.assertEqual(table, self.views.records_table(overview, people, 25000, 2388))
        lines = table.splitlines()
        self.assertEqual(lines[0], "**Kumo learns from the whole dataset, 4 tables with 3.4 million rows of health records "
                                   "for 25,000 people, with no hand-built features, and forecasts for this cohort's 2,388 members.**")
        self.assertEqual(lines[2:7], ["| Records | All 25,000 people | This cohort's 2,388 |", "|---|---:|---:|",
                                      "| Lab results and vitals | 3,355,100 | 300,000 |",
                                      "| People | 25,000 | 2,388 |", "| lab_notes | 7 | 0 |"])
        self.assertIn("| 1 more tables | 25,000 | 2,388 |", lines, "a bookkeeping table is counted, not named")
        self.assertIn("*One of the cohort's 2,388 members, picked at random, as examples of what a record holds "
                      "(synthetic patients; no names or ids):*", lines)
        plain = self.views.records_table(overview, [], None, None).splitlines()
        self.assertEqual(plain[2], "| Records | Rows |", "without the counts, one column of rows")
        self.assertIn("| Patient | In the cohort since | Diagnoses | Prescriptions | Labs (first → last) |", lines)
        row = next(l for l in lines if l.startswith("| Patient 1"))
        self.assertIn("| 2018 |", row)
        self.assertIn("Type 2 diabetes mellitus (2018)", row)
        self.assertIn("Metformin (2018)", row)
        self.assertNotIn("×", row)
        self.assertIn("eGFR / CKD-EPI: 94 → 82", row, "a | in a name would break the table")
        self.assertIn("eGFR: 90 → 80", row)
        self.assertNotIn("1000", table)

    def test_the_genotype_comparison_puts_both_runs_side_by_side(self):
        import os
        from unittest import mock
        try:
            import pandas as pd
        except ImportError:
            self.skipTest("needs pandas")
        scores = pd.DataFrame({"risk": [0.9, 0.8] + [0.1] * 18, "outcome_within_horizon": ["1", "0"] + ["0"] * 17 + ["1"]})
        with mock.patch.dict(os.environ, {"KUMO_FORECAST_SMALL_CELL": "0"}):
            tenth = self.views.tenth_summary(scores, "outcome_within_horizon", True)
            self.assertEqual((tenth["people"], tenth["cases_in_it"], tenth["cases"]), (2, 1, 2))
            self.assertEqual((tenth["rate"], tenth["rate_in_the_rest"]), ("50.0%", "5.6%"))

        def run(auroc, top, two):
            return {"observed": {"auroc": auroc}, "highest_risk_tenth": {"cases_in_it": top, "cases": 33, "rate": "9.5%",
                                                                       "rate_in_the_rest": "0.2%"},
                    "genotypes": [{"characteristic": "apol1_genotype: two APOL1 risk alleles", "top_10pct": two, "rest": "3.0%"}]}
        lines = self.views.genotype_comparison_table("everyone in p.d.t", "CKD 3 within 365 days", 2834,
                                                     {"health_records_only": run(0.957, 27, "8.1%"),
                                                      "with_genotypes": run(0.959, 28, "9.5%")}).splitlines()
        self.assertEqual(lines[0], "**The same 2,834 people, forecast twice: CKD 3 within 365 days.**")
        for want in ("| | Health records only | Health records + genotypes |", "| Accuracy (AUROC) | 0.957 | 0.959 |",
                     "| Cases in the highest-risk tenth | 27 of 33 | 28 of 33 |",
                     "| Two APOL1 risk alleles: highest-risk tenth vs the rest | 8.1% vs 3.0% | 9.5% vs 3.0% |"):
            self.assertIn(want, lines)

    def test_lab_names_are_shortened_and_race_columns_are_not_listed(self):
        v = self.views
        self.assertEqual(v.short_name("Glomerular filtration rate/1.73 sq M.predicted [Volume Rate/Area] in Serum"),
                         "Glomerular filtration rate")
        self.assertEqual(v.short_name("Creatinine [Mass/volume] in Serum or Plasma"), "Creatinine")
        self.assertEqual(v.short_name("Hemoglobin A1c (Glycated)"), "Hemoglobin A1c (Glycated)")
        self.assertEqual(len(v.short_name("x" * 60)), 40)
        schemas = {"person": {"num_rows": 3, "columns": [("person_id", "INTEGER"), ("race_concept_id", "INTEGER"),
                                                         ("ethnicity", "STRING"), ("year_of_birth", "INTEGER")]}}
        self.assertEqual(v.table_overview(schemas, ["person"], "person_id")[0]["columns"], ["year_of_birth"])

    def test_the_genomes_table_has_a_headline_key_figures_then_variants_in_plain_words(self):
        summary = {"genomes": 3202, "of_the_cohort": 275,
                   "cohort_genomes": {"nominal_coverage": {"30": 275}, "is_staged": {"False": 274, "True": 1}},
                   "aligned_reads": {"files_present": 8, "one_genome_gb": 14.7, "all_genomes_tb_estimated": 46.9}}
        rows = [{"CHROM": "chr22", "POS": 36245412 + i, "REF": "G", "ALT": "A", "QUAL": "51.7", "GT": gt}
                for i, gt in enumerate(["1/1", "0/1", "0|1", "1/1"])]
        vcf = {"sample": "NA19657", "passed": 150, "passed_snps": 130, "passed_indels": 20,
               "variants_per_region": {"APOL1": 40, "PCSK9": 9}, "regions": {"APOL1": "chr22:36,245,000-36,275,000"},
               "rows": rows, "columns": self.views.VCF_COLUMNS}
        lines = self.views.genomes_table(summary, vcf).splitlines()
        self.assertEqual(lines[0], "**3,202 whole genomes, 275 of them from this cohort's members.**")
        for want in ("| One genome | Whole genome, 30x coverage: about 14.7 GB of sequencing reads |",
                     "| All of them | about 46.9 TB |", "| Parabricks found, in one genome | 40 in APOL1, 9 in PCSK9 |",
                     "| Gene | Position | Reference → this genome | Copies |",
                     "| APOL1 | chr22:36,245,412 | G → A | 2 |", "| APOL1 | chr22:36,245,413 | G → A | 1 |",
                     "| APOL1 | chr22:36,245,414 | G → A | 1 |"):
            self.assertIn(want, lines)
        self.assertEqual(len([l for l in lines if l.startswith("| APOL1 |")]), 3)
        self.assertFalse([l for l in lines if "staged" in l.lower() or "QUAL" in l or "NA19657" in l])
        no_vcf = self.views.genomes_table({"genomes": 10, "of_the_cohort": 2, "cohort_genomes": {},
                                           "aligned_reads": {"note": "none"}}, None).splitlines()
        self.assertIn("| One genome | Whole genome |", no_vcf)

    def test_the_page_draws_a_tool_answers_table(self):
        script = (APP / "assistant-ui" / "static" / "app.js").read_text()
        self.assertIn('typeof output.table === "string"', script)
        self.assertIn("markdown(table)", script)


class ForecastAnswerTests(unittest.TestCase):
    """Service.forecast's answer and its argument checks, with BigQuery and the model stubbed."""

    def setUp(self):
        try:
            import pandas
        except ImportError:
            self.skipTest("needs pandas")
        import tempfile
        self.pd = pandas
        from kumo_forecast import service
        self.service = service
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svc = service.Service(Path(self.tmp.name) / "sessions", Path(self.tmp.name) / "state")

    def two_lock_service(self):
        return self.service.Service(FIXTURES / "two_locks", Path(self.tmp.name) / "state")

    def test_extra_tables_are_read_beside_the_cohorts_dataset(self):
        import types
        from unittest import mock
        lc = types.SimpleNamespace(dataset="wb-data-1234.omop", key_data_column="person_id", billing_project=None)
        schemas = {
            "person": {"columns": [("person_id", "INTEGER")], "source": "wb-data-1234.omop", "table": "person"},
            "measurement": {"columns": [("person_id", "INTEGER"), ("d", "DATE")], "source": "wb-data-1234.omop",
                            "table": "measurement"},
            "concept": {"columns": [("concept_id", "INTEGER")], "source": "wb-data-1234.omop", "table": "concept"},
            "apol1_genotypes": {"columns": [("person_id", "INTEGER"), ("apol1_risk_alleles", "INTEGER")],
                                "source": "wb-work-5678.genomic_results", "table": "apol1_genotypes"},
            "other_person": {"columns": [("person_id", "INTEGER")], "source": "wb-work-5678.genomic_results",
                             "table": "other_person"},
        }
        self.svc._client = lambda project: None
        with mock.patch.object(self.service.tables, "read_schemas", return_value=schemas) as read:
            dataset, names = self.svc._with_extra(lc, None, ["wb-work-5678.genomic_results.apol1_genotypes"])
            self.assertEqual(dataset, "wb-data-1234.omop,wb-work-5678.genomic_results")
            read.assert_called_once_with(None, dataset)
            # Every keyed table of the cohort's own dataset, then the extra table, and nothing else of its dataset.
            self.assertEqual(names, ["person", "measurement", "apol1_genotypes"])
            self.assertEqual(self.svc._with_extra(lc, ["measurement"], ["`wb-work-5678.genomic_results.apol1_genotypes`"])[1],
                             ["measurement", "apol1_genotypes"])
            with self.assertRaisesRegex(ValueError, "is not a table of wb-work-5678.genomic_results"):
                self.svc._with_extra(lc, None, ["wb-work-5678.genomic_results.missing"])
            for bad in ("apol1_genotypes", "genomic_results.apol1_genotypes", "wb-work-5678.genomic_results.t; DROP"):
                with self.assertRaisesRegex(ValueError, "not a project.dataset.table"):
                    self.svc._with_extra(lc, None, [bad])
        self.assertEqual(self.svc._with_extra(lc, ["person"], None), ("wb-data-1234.omop", ["person"]))

    def test_a_population_table_scores_its_people_instead_of_the_cohort(self):
        import types
        pd = self.pd
        lc = types.SimpleNamespace(key_data_column="person_id", billing_project=None)
        sent = []

        class Client:
            def query(self, sql):
                sent.append(sql)
                return types.SimpleNamespace(to_dataframe=lambda: pd.DataFrame({"person_id": ["7", "7", "9"]}))
        self.svc._client = lambda project: Client()
        people = self.svc._table_members(lc, "wb-work-5678.genomic_results.apol1_genotypes", "INTEGER")
        self.assertEqual(people.person_id.tolist(), [7, 9])
        self.assertEqual(sent, ["SELECT DISTINCT `person_id` FROM `wb-work-5678`.`genomic_results`.`apol1_genotypes` "
                                "WHERE `person_id` IS NOT NULL"])
        for bad in ("apol1_genotypes", "wb-work-5678.genomic_results.t`; DROP TABLE x; --"):
            with self.assertRaisesRegex(ValueError, "not a project.dataset.table"):
                self.svc._table_members(lc, bad, "INTEGER")

    def test_a_forecast_needs_an_outcome(self):
        with self.assertRaisesRegex(ValueError, "outcome is required"):
            self.svc.forecast()

    def test_the_outcome_is_checked_against_the_cohorts_schema_before_any_table_is_read(self):
        import types
        lc = types.SimpleNamespace(session_id="s", version=1, key_data_column="person_id", dataset="d",
                                   billing_project=None)
        self.svc._locked = lambda sid, v: lc
        self.svc._schemas = lambda lc: OMOP_SCHEMAS
        self.svc.graph = lambda *a: self.fail("a refused outcome reads no table")
        with self.assertRaisesRegex(outcome.OutcomeError, "'diagnoses' is not in the cohort's dataset"):
            self.svc.forecast(outcome={"table": "diagnoses"})

    def test_the_two_latest_table_choices_are_kept_and_an_older_one_is_read_again_for_compare(self):
        import types
        from unittest import mock
        svc, built = self.svc, []
        pd_ts = self.pd.Timestamp("2025-01-01")
        svc._client = lambda project: None
        plan = types.SimpleNamespace(time={})
        with mock.patch.object(self.service.tables, "read_schemas", return_value={}), \
                mock.patch.object(self.service.tables, "plan", return_value=plan), \
                mock.patch.object(self.service.tables, "load", side_effect=lambda *a: built.append(a[2]) or {}), \
                mock.patch.object(self.service.tables, "vocabulary", return_value={}), \
                mock.patch.object(self.service.dataset_mod, "build", side_effect=lambda *a: object()):
            svc.graph("d", "k", chosen=["a"])
            svc.graph("d", "k", chosen=["a"])
            self.assertEqual(len(built), 1, "the same choice is read once")
            svc.graph("d", "k", chosen=["b"])
            svc.graph("d", "k", chosen=["a"])
            self.assertEqual(len(built), 2, "the two latest choices are both kept")
            svc.graph("d", "k", chosen=["c"])
            self.assertEqual(list(svc._graphs), [svc._cache_key("d", "k", None, ["a"]), svc._cache_key("d", "k", None, ["c"])],
                             "the least recently used (b) went")
            svc.graph("d", "k", chosen=["b"])
            self.assertEqual(len(built), 4)
            # compare() on a run made with the first choice asks for that choice again, from its metadata
            scores = self.pd.DataFrame({"k": [1, 2], "cutoff": pd_ts, "outcome_within_horizon": ["1", "0"], "risk": [0.9, 0.1]})
            svc._save("run-1", scores, {"dataset": "d", "key": "k", "billing_project": None, "time_columns": {},
                                        "tables": ["a"], "labels_known": True})
            scores.to_parquet(svc.state / "runs" / "run-1.pool.parquet", index=False)
            with mock.patch("kumo_forecast.baselines.compare",
                            return_value=scores.assign(logistic_regression=0.5, gradient_boosting=0.5).astype({"outcome_within_horizon": str})):
                svc.compare("run-1")
            self.assertEqual(len(built), 5)
            self.assertEqual(list(svc._graphs), [svc._cache_key("d", "k", None, ["b"]), svc._cache_key("d", "k", None, ["a"])])

    def test_warm_builds_the_cohorts_model_then_one_with_each_extra_table_in_its_project(self):
        import types
        svc, made = self.svc, []
        svc._locked = lambda sid, version: types.SimpleNamespace(dataset="wb-data-1.omop", key_data_column="person_id",
                                                                 billing_project="wb-work-2")

        def extra_of(pop, chosen, extra):
            if extra and extra[0].startswith("bad."):
                raise ValueError("no such table")
            return "wb-data-1.omop" + (",x" if extra else ""), extra
        svc._with_extra = extra_of
        svc.forecaster = lambda dataset, key, project, overrides, chosen: made.append((dataset, chosen))
        said = svc.warm(["genomic_results.apol1", "bad.d.t", "q-2.g.t"])
        self.assertEqual(said[:2], ["warmed wb-data-1.omop", "warmed wb-data-1.omop with wb-work-2.genomic_results.apol1"],
                         "a bare dataset.table is in the workspace's (billing) project, not the data's")
        self.assertTrue(said[2].startswith("not warmed wb-data-1.omop with bad.d.t (ValueError"), said[2])
        self.assertEqual(said[3], "warmed wb-data-1.omop with q-2.g.t", "one failure does not stop the rest")
        self.assertEqual(made, [("wb-data-1.omop", None), ("wb-data-1.omop,x", ["wb-work-2.genomic_results.apol1"]),
                                ("wb-data-1.omop,x", ["q-2.g.t"])])

    def test_a_horizon_past_the_labeled_history_is_refused(self):
        for days in (29, 1826, 3650):
            with self.assertRaisesRegex(ValueError, "between 30 and 1825"):
                self.svc.forecast(outcome=CKD3, horizon_days=days)

    def test_the_longest_horizon_still_has_labeled_history_to_learn_from(self):
        pd, s = self.pd, self.service
        for as_of in ("2024-02-29", "2025-03-01", "2026-01-01", "2028-12-31"):
            when = pd.Timestamp(as_of)
            oldest = when - pd.DateOffset(years=s.HISTORY_YEARS)
            self.assertLessEqual(oldest + pd.Timedelta(days=s.MAX_HORIZON_DAYS), when)

    def test_the_labeled_cases_learned_from_are_masked(self):
        import types
        from unittest import mock
        pd, s = self.pd, self.service
        from kumo_forecast.dataset import TARGET
        lc = types.SimpleNamespace(session_id="s", version=1, key_data_column="person_id", dataset="d",
                                   billing_project=None)
        ds = types.SimpleNamespace(data_end=pd.Timestamp("2026-01-01"), entities=None, tables_read=lambda: {}, names={})
        scores = pd.DataFrame({"person_id": range(40), "cutoff": pd.Timestamp("2025-01-01"),
                               TARGET: "0", "risk": [i / 40 for i in range(40)]})
        result = {"scores": scores, "pool": scores[["person_id", "cutoff", TARGET]], "labels_known": False,
                  "excluded": {"not_yet_in_the_cohort_on_as_of": 3}, "context_rows": 1200,
                  "context_positives": 15, "seconds": 1.0, "device": "cpu", "peak_gpu_gb": None}
        self.svc._locked = lambda sid, v: lc
        self.svc._schemas = lambda lc: OMOP_SCHEMAS
        self.svc._outcome_dates = lambda lc, o, kt: pd.Series(dtype="datetime64[ns]")
        self.svc.graph = lambda *a: (ds, None)
        self.svc.forecaster = lambda *a: types.SimpleNamespace(run=lambda *a, **k: result)
        self.svc._key_type = lambda ds: "INTEGER"
        self.svc._frame = lambda lc, kt: pd.DataFrame({"person_id": range(43),
                                                       "index_date": pd.Timestamp("2020-01-01")})
        with mock.patch("kumo_forecast.profile.high_risk_profile", return_value=[]):
            out = self.svc.forecast(outcome=CKD3, as_of="2025-01-01")
        self.assertIn("(<20 with the outcome)", out["learned_from"])
        self.assertIn("1,200 labeled histories", out["learned_from"])
        self.assertEqual(out["excluded"], {"not_yet_in_the_cohort_on_as_of": "<20"})

    def _forecast_with_labels(self, n, events):
        """The answer of a forecast over ``n`` members at risk, ``events`` of whom have the outcome."""
        import types
        from unittest import mock
        pd, s = self.pd, self.service
        from kumo_forecast.dataset import TARGET
        lc = types.SimpleNamespace(session_id="s", version=1, key_data_column="person_id", dataset="d",
                                   billing_project=None)
        ds = types.SimpleNamespace(data_end=pd.Timestamp("2026-01-01"), entities=None, tables_read=lambda: {}, names={})
        scores = pd.DataFrame({"person_id": range(n), "cutoff": pd.Timestamp("2025-01-01"),
                               TARGET: ["1" if i < events else "0" for i in range(n)],
                               "risk": [i / n for i in range(n)]})
        result = {"scores": scores, "pool": scores[["person_id", "cutoff", TARGET]], "labels_known": True,
                  "excluded": {}, "context_rows": 4000, "context_positives": 1000, "seconds": 1.0,
                  "device": "cpu", "peak_gpu_gb": None}
        self.svc._locked = lambda sid, v: lc
        self.svc._schemas = lambda lc: OMOP_SCHEMAS
        self.svc._outcome_dates = lambda lc, o, kt: pd.Series(dtype="datetime64[ns]")
        self.svc.graph = lambda *a: (ds, None)
        self.svc.forecaster = lambda *a: types.SimpleNamespace(run=lambda *a, **k: result)
        self.svc._key_type = lambda ds: "INTEGER"
        self.svc._frame = lambda lc, kt: pd.DataFrame({"person_id": range(n),
                                                       "index_date": pd.Timestamp("2020-01-01")})
        with mock.patch("kumo_forecast.profile.high_risk_profile", return_value=[]):
            return self.svc.forecast(outcome=CKD3, as_of="2025-01-01")

    def test_members_without_the_outcome_are_masked_beside_the_members_at_risk(self):
        for events, shown in ((985, ">980"), (981, ">980"), (980, 980), (20, 20), (19, "<20"), (0, 0)):
            out = self._forecast_with_labels(1000, events)
            self.assertEqual(out["observed"]["members_with_the_outcome"], shown, events)

    def test_members_without_the_outcome_are_shown_when_masking_is_off(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"KUMO_FORECAST_SMALL_CELL": "0"}):
            out = self._forecast_with_labels(1000, 985)
        self.assertEqual(out["observed"]["members_with_the_outcome"], 985)

    def test_two_risk_quartile_rates_are_bounds_when_one_is_masked(self):
        # 800 members at risk, 200 a quartile; the highest-risk members come last
        pd = self.pd
        from kumo_forecast.dataset import TARGET
        y = [0] * 800
        for q, ev in enumerate((7, 40, 60, 90)):
            for i in range(ev):
                y[q * 200 + i] = 1
        s = pd.DataFrame({"person_id": range(800), "risk": [i / 800 for i in range(800)],
                          TARGET: [str(v) for v in y]})
        rows = self.service._quartiles(s, True)
        rates = [r["observed_rate"] for r in rows]
        self.assertEqual([r["members"] for r in rows], [200] * 4)
        self.assertEqual(rates[0], "<10.0%")
        self.assertTrue(rates[1].startswith("<"))
        self.assertGreaterEqual(sum(r.endswith("%") and r[0] in "<>" for r in rates), 2)
        self.assertEqual(rates[2:], ["30.0%", "45.0%"])

    def test_quartile_rates_are_exact_when_masking_is_off(self):
        import os
        from unittest import mock
        pd = self.pd
        from kumo_forecast.dataset import TARGET
        y = [0] * 800
        for q, ev in enumerate((7, 40, 60, 90)):
            for i in range(ev):
                y[q * 200 + i] = 1
        s = pd.DataFrame({"person_id": range(800), "risk": [i / 800 for i in range(800)],
                          TARGET: [str(v) for v in y]})
        with mock.patch.dict(os.environ, {"KUMO_FORECAST_SMALL_CELL": "0"}):
            rows = self.service._quartiles(s, True)
        self.assertEqual([r["observed_rate"] for r in rows], ["3.5%", "20.0%", "30.0%", "45.0%"])

    def _select(self, n, top_n):
        from unittest import mock
        pd, s = self.pd, self.service
        from kumo_forecast.dataset import TARGET
        scores = pd.DataFrame({"person_id": range(n), "risk": [i / n for i in range(n)],
                               TARGET: ["0"] * n})
        self.svc._load = lambda run_id: (scores, {"key": "person_id", "labels_known": False})
        with mock.patch.object(s.destination_mod, "check_destination"), \
                mock.patch.object(s.destination_mod, "workspace_resources", return_value=[]), \
                mock.patch.object(s.destination_mod, "copy_to_bucket"):
            return self.svc.select("run-x", "gs://b/", top_n)

    def test_select_reports_the_callers_top_n_and_masks_a_smaller_count_of_the_data(self):
        self.assertEqual(self._select(500, 16)["selected"], 16)
        self.assertEqual(self._select(16, 16)["selected"], 16)
        self.assertEqual(self._select(7, 16)["selected"], "<20")
        self.assertEqual(self._select(0, 16)["selected"], 0)
        self.assertEqual(self._select(30, 50)["selected"], 30)
        self.assertEqual(self._select(7, 16)["rule"], "the 16 highest-risk members")

    def test_select_reports_the_count_selected_when_masking_is_off(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"KUMO_FORECAST_SMALL_CELL": "0"}):
            self.assertEqual(self._select(7, 16)["selected"], 7)

    def test_rows_of_a_table_are_masked_in_get_cohort_info_and_in_the_size_error(self):
        from kumo_forecast import tables
        schemas = {"notes": {"num_rows": 9, "columns": [("person_id", "INTEGER"), ("x", "STRING")]},
                   "big": {"num_rows": 20, "columns": [("person_id", "INTEGER"), ("x", "STRING")]},
                   "edge": {"num_rows": 19, "columns": [("person_id", "INTEGER"), ("x", "STRING")]},
                   "none": {"num_rows": 0, "columns": [("person_id", "INTEGER"), ("x", "STRING")]}}
        rows = {t["table"]: t["rows"] for t in tables.describe_keyed(schemas, "person_id")}
        self.assertEqual(rows, {"notes": "<20", "big": 20, "edge": "<20", "none": 0})
        with self.assertRaises(schema.SchemaError) as e:
            schema.size_guard({"notes": schemas["notes"], "big": schemas["big"]}, ["notes", "big"], limit=5)
        self.assertIn("notes (<20)", str(e.exception))
        self.assertIn("big (20)", str(e.exception))

    def test_the_profile_counts_of_a_small_forecast_are_masked_beside_the_members_at_risk(self):
        pd = self.pd
        from kumo_forecast import profile
        _, ds = _graph(pd)
        scores = pd.DataFrame({"person_id": range(150), "risk": [i / 150 for i in range(150)]})
        first = profile.high_risk_profile(ds, scores, pd.Timestamp("2021-06-01"))[0]
        self.assertEqual((first["top_10pct"], first["rest"]), ("<20", ">130"))   # 15 and 135
        scores = pd.DataFrame({"person_id": range(250), "risk": [i / 250 for i in range(250)]})
        first = profile.high_risk_profile(ds, scores, pd.Timestamp("2021-06-01"))[0]
        self.assertEqual((first["top_10pct"], first["rest"]), (25, 225))


if __name__ == "__main__":
    unittest.main()
