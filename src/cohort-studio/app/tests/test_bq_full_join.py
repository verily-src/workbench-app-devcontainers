"""Cross-source joins read BigQuery tables in full (Storage Read API fakes, no network)."""
import threading
import time
import uuid
from types import SimpleNamespace

import duckdb
import pandas as pd
import pyarrow as pa
import pytest

import bq
import data_jobs
import datasets
import disk_data
import joins
import main
import queries

CAP = 50
FULL_ROWS = 180
RID = "bq:variants"


def _full_frame() -> pd.DataFrame:
    ids = list(range(1, FULL_ROWS + 1))
    return pd.DataFrame({
        "person_id": ids,
        "variant": ["ABC"[i % 3] for i in ids],
        "score": [i % 10 for i in ids],
        "tags": [["x", "y"] if i % 2 else ["z"] for i in ids],
        "extra": [f"e{i}" for i in ids],
    })


class FakeBigQuery:
    """Stands in for bigquery.Client and BigQueryReadClient."""

    def __init__(self, table_type="TABLE", num_bytes=40_000, page_rows=45, block_after=None,
                 predicate=None):
        self.table_type, self.num_bytes = table_type, num_bytes
        self.page_rows, self.block_after, self.predicate = page_rows, block_after, predicate
        self.billing, self.sessions, self.cancelled = [], [], threading.Event()
        self.started = threading.Event()

    # bigquery.Client
    def client(self, billing):
        self.billing.append(billing)
        return self

    def get_table(self, name):
        self.table_name = name
        schema = [SimpleNamespace(name=n, field_type=t, mode=m) for n, t, m in [
            ("person_id", "INTEGER", "NULLABLE"), ("variant", "STRING", "NULLABLE"),
            ("score", "INTEGER", "NULLABLE"), ("tags", "STRING", "REPEATED"),
            ("extra", "STRING", "NULLABLE")]]
        return SimpleNamespace(schema=schema, num_rows=FULL_ROWS, num_bytes=self.num_bytes,
                               table_type=self.table_type, modified=None)

    # BigQueryReadClient
    def storage(self, billing):
        self.billing.append(billing)
        return self

    def create_read_session(self, parent, read_session, max_stream_count):
        self.sessions.append({"parent": parent, "table": read_session.table,
                              "fields": list(read_session.read_options.selected_fields),
                              "restriction": read_session.read_options.row_restriction})
        return SimpleNamespace(streams=[SimpleNamespace(name="stream-0")])

    def read_rows(self, name):
        return self

    def cancel(self):
        self.cancelled.set()

    def rows(self, session):
        return self

    @property
    def pages(self):
        frame = _full_frame()
        if self.predicate is not None:
            frame = frame[self.predicate(frame)]
        fields = self.sessions[-1]["fields"]
        if fields:
            frame = frame[fields]
        table = pa.Table.from_pandas(frame, preserve_index=False)
        for n, start in enumerate(range(0, len(frame), self.page_rows)):
            if self.block_after is not None and n == self.block_after:
                self.started.set()
                self.cancelled.wait(10)
                raise RuntimeError("stream cancelled")
            batch = table.slice(start, self.page_rows).combine_chunks().to_batches()[0]
            yield SimpleNamespace(to_arrow=lambda batch=batch: batch)


@pytest.fixture
def setup(client, engine, monkeypatch, tmp_path):
    monkeypatch.setattr(disk_data, "_ROOT", tmp_path)
    monkeypatch.setattr(disk_data, "_MIN_FREE_BYTES", 0)
    monkeypatch.setattr(queries, "ROW_CAP", CAP)
    monkeypatch.setattr(main.db, "list_bq_datasets", lambda *a, **k: [{
        "id": RID, "project": "data-proj", "dataset": "genomics", "table": "",
        "billing_project": "my-billing"}])
    monkeypatch.setattr(bq, "fetch_table", lambda project, dataset, table, cap, billing="":
                        bq.flatten(_full_frame().head(cap)))
    fake = FakeBigQuery()
    monkeypatch.setattr(bq, "_client", lambda billing: fake.client(billing))
    monkeypatch.setattr(bq, "_storage_client", lambda billing: fake.storage(billing))
    table = f"studio_bq_people_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE TABLE public."{table}" (person_id BIGINT, status TEXT)')
        conn.exec_driver_sql(f'INSERT INTO public."{table}" SELECT i, '
                             f"CASE WHEN i %% 2 = 0 THEN 'case' ELSE 'control' END "
                             f"FROM generate_series(1, {FULL_ROWS}) i")
    opened = []

    def open_ref(ref):
        response = client.post("/api/datasets/open", json={"source_ref": ref})
        assert response.status_code == 200, response.text
        opened.append(response.json()["dataset_id"])
        return response.json()

    state = SimpleNamespace(client=client, fake=fake, table=table, open=open_ref,
                            opened=opened, root=tmp_path)
    yield state
    for dataset_id in opened:
        datasets.close_dataset(dataset_id)
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS public."{table}"')


def _open_pair(state):
    people = state.open({"kind": "aurora", "resource_id": "omopdb", "schema": "public",
                         "table": state.table})
    variants = state.open({"kind": "bq", "resource_id": RID, "table": "variants"})
    assert variants["sampled"] is True and variants["rows"] == CAP
    return people, variants


def _request(people, variants, **step):
    return {"base_id": people["dataset_id"], "allow_loaded": True, "steps": [{
        "right_id": variants["dataset_id"], "how": "inner", "alias": "v", "columns": None,
        "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}], **step}]}


def _rows(dataset_id, sql):
    disk = datasets.get(dataset_id)["disk_source"]
    con = duckdb.connect(disk["path"], read_only=True)
    try:
        return con.execute(sql.format(t=f'"{disk["table"]}"')).fetchall()
    finally:
        con.close()


def test_join_reads_every_bigquery_row_billed_to_billing_project(setup):
    people, variants = _open_pair(setup)
    request = _request(people, variants, columns=["variant", "tags"])
    check = setup.client.post("/api/datasets/join/validate", json=request).json()
    assert check["ok"] and check["engine"] == "duckdb" and check["capped_inputs"] == []
    response = setup.client.post("/api/datasets/join", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    setup.opened.append(result["dataset_id"])
    stats = result["join"]
    assert stats["rows"] == FULL_ROWS > CAP
    assert stats["complete_source"] is True and stats["capped_inputs"] == []
    assert result["sampled"] is False
    assert any("Read every row" in note for note in stats["notes"])
    session = setup.fake.sessions[-1]
    assert session["parent"] == "projects/my-billing"
    assert set(setup.fake.billing) == {"my-billing"}
    assert session["table"] == "projects/data-proj/datasets/genomics/tables/variants"
    assert session["fields"] == ["person_id", "variant", "tags"]      # projected
    assert session["restriction"] == ""
    rows = _rows(result["dataset_id"],
                 'SELECT person_id, status, "v → variant", "v → tags" FROM {t} ORDER BY person_id')
    expected = [(i, "case" if i % 2 == 0 else "control", "ABC"[i % 3],
                 "x, y" if i % 2 else "z") for i in range(1, FULL_ROWS + 1)]
    assert rows == expected
    assert not list(setup.root.glob("dataset-*.duckdb.tmp*"))


def test_join_filters_are_pushed_into_the_bigquery_read(setup):
    setup.fake.predicate = lambda f: f["variant"].isin(["A", "B"]) & (f["score"] >= 5)
    people, variants = _open_pair(setup)
    request = _request(people, variants, filters=[
        {"column": "variant", "op": "in", "value": ["A", "B"]},
        {"column": "score", "op": ">=", "value": 5},
        {"column": "extra", "op": "contains", "value": "1"},       # stays in DuckDB
    ])
    response = setup.client.post("/api/datasets/join", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    setup.opened.append(result["dataset_id"])
    session = setup.fake.sessions[-1]
    assert session["restriction"] == "(`variant` IN ('A', 'B')) AND (`score` >= 5)"
    full = _full_frame()
    want = full[full.variant.isin(["A", "B"]) & (full.score >= 5)
                & full.extra.str.contains("1")]
    assert result["join"]["rows"] == len(want) > 0
    assert result["join"]["complete_source"] is True
    got = _rows(result["dataset_id"], "SELECT person_id FROM {t} ORDER BY person_id")
    assert [r[0] for r in got] == sorted(want.person_id.tolist())


def test_repeated_field_filter_stays_in_duckdb_on_the_flattened_value(setup):
    setup.fake.predicate = lambda f: f["variant"] == "A"
    people, variants = _open_pair(setup)
    request = _request(people, variants, columns=["variant"], filters=[
        {"column": "variant", "op": "=", "value": "A"},
        {"column": "tags", "op": "=", "value": "x, y"},        # REPEATED STRING
        {"column": "tags", "op": "is not null"},
    ])
    response = setup.client.post("/api/datasets/join", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    setup.opened.append(result["dataset_id"])
    session = setup.fake.sessions[-1]
    assert session["restriction"] == "(`variant` = 'A')"
    assert "tags" in session["fields"]                   # read so DuckDB can filter it
    full = _full_frame()
    want = full[(full.variant == "A") & full.tags.map(lambda t: t == ["x", "y"])]
    assert result["join"]["rows"] == len(want) > 0
    assert result["join"]["complete_source"] is True
    got = _rows(result["dataset_id"], "SELECT person_id FROM {t} ORDER BY person_id")
    assert [r[0] for r in got] == sorted(want.person_id.tolist())


def test_row_restriction_never_pushes_repeated_or_record_fields():
    kinds = {"tags": "text", "info": "text"}
    raw = [{"column": "tags", "op": "=", "value": "x, y"},
           {"column": "tags", "op": "is null"},
           {"column": "info", "op": "is not null"}]
    checked = [joins._check_filter(f, kinds, "t") for f in raw]
    restriction, residual = bq.row_restriction(
        checked, {"tags": "STRING", "info": "RECORD"}, {"tags": "REPEATED", "info": "NULLABLE"})
    assert restriction == ""
    assert residual == checked


def test_bigquery_read_over_budget_is_refused_before_reading(setup):
    setup.fake.num_bytes = disk_data.MAX_OPERATION_BYTES + 1
    people, variants = _open_pair(setup)
    response = setup.client.post("/api/datasets/join", json=_request(people, variants))
    assert response.status_code == 413, response.text
    assert "1 TB" in response.text
    assert setup.fake.sessions == []
    assert not list(setup.root.glob("dataset-*.duckdb"))


def test_cancel_mid_stream_removes_the_staging_file(setup):
    setup.fake.block_after = 1
    people, variants = _open_pair(setup)
    steps = _request(people, variants)["steps"]
    manager = data_jobs.DataJobs(setup.root / "jobs.sqlite3", workers=1)
    try:
        job_id = manager.submit("join", "owner", lambda: joins.run(
            people["dataset_id"], steps, allow_loaded=True), lambda _: None)["job_id"]
        assert setup.fake.started.wait(10)
        assert list(setup.root.glob("dataset-*.duckdb"))
        manager.cancel(job_id, "owner")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = manager.get(job_id, "owner")
            if job["status"] in {"cancelled", "failed", "succeeded"}:
                break
            time.sleep(.02)
        assert job["status"] == "cancelled", job
        assert setup.fake.cancelled.is_set()          # the read stream was cancelled
        assert not list(setup.root.glob("dataset-*.duckdb"))
    finally:
        manager.shutdown()


def test_preview_uses_loaded_bigquery_rows_and_says_so(setup):
    people, variants = _open_pair(setup)
    response = setup.client.post("/api/datasets/join/preview", json=_request(people, variants))
    assert response.status_code == 200, response.text
    preview = response.json()
    assert setup.fake.sessions == []
    assert preview["rows"] == CAP
    assert preview["complete_source"] is False
    assert preview["capped_inputs"] == [variants["source"]]
    assert any("Preview used the loaded" in note and "reads every row" in note
               for note in preview["notes"])


def test_bigquery_view_keeps_loaded_rows_and_reports_it(setup):
    setup.fake.table_type = "VIEW"
    people, variants = _open_pair(setup)
    response = setup.client.post("/api/datasets/join", json=_request(people, variants))
    assert response.status_code == 200, response.text
    result = response.json()
    setup.opened.append(result["dataset_id"])
    assert setup.fake.sessions == []
    assert result["join"]["rows"] == CAP
    assert result["join"]["complete_source"] is False
    assert result["join"]["capped_inputs"] == [variants["source"]]
    assert result["sampled"] is True
    assert any("views cannot be read in full" in n for n in result["join"]["notes"])


def test_capped_aurora_frame_is_read_from_its_table(setup, engine):
    # A frame loaded straight from an Aurora table (e.g. via MCP) with only
    # its capped rows, joined with an upload: staged from the table in full.
    loaded = pd.read_sql_query(f'SELECT * FROM public."{setup.table}" LIMIT {CAP}', engine)
    base = datasets.open_dataset(loaded, f"omopdb / {setup.table}", capped=True,
                                 origin=joins.aurora_origin("omopdb", setup.table))
    upload = datasets.open_dataset(pd.DataFrame({"person_id": range(1, FULL_ROWS + 1),
                                                 "site": "s"}), "sites.csv", capped=False)
    setup.opened.extend([base["dataset_id"], upload["dataset_id"]])
    steps = [{"right_id": upload["dataset_id"], "how": "inner", "alias": "u",
              "columns": None, "conditions": [{"left": "person_id", "op": "=",
                                                "right": "person_id"}]}]
    assert joins.validate(base["dataset_id"], steps)["capped_inputs"] == []
    out = joins.run(base["dataset_id"], steps)
    assert out["stats"]["rows"] == FULL_ROWS
    assert out["stats"]["complete_source"] is True
    disk_data.remove(out["disk_source"])


def test_row_restriction_renders_safe_literals_and_keeps_inexact_filters():
    kinds = {"name": "text", "n": "number", "flag": "bool", "day": "time", "ts": "time"}
    raw = [{"column": "name", "op": "=", "value": "O'Brien \\ x"},
           {"column": "n", "op": "not in", "value": [1, 2.5]},
           {"column": "flag", "op": "=", "value": "true"},
           {"column": "day", "op": "<", "value": "2024-01-31"},
           {"column": "ts", "op": ">", "value": "2024-01-31"},
           {"column": "name", "op": "is not null"},
           {"column": "name", "op": "contains", "value": "x"}]
    checked = [joins._check_filter(f, kinds, "t") for f in raw]
    types = {"name": "STRING", "n": "INT64", "flag": "BOOL", "day": "DATE", "ts": "TIMESTAMP"}
    restriction, residual = bq.row_restriction(checked, types)
    assert restriction == ("(`name` = 'O\\'Brien \\\\ x') AND (`n` NOT IN (1, 2.5)) "
                           "AND (`flag` = TRUE) AND (`day` < DATE '2024-01-31') "
                           "AND (`name` IS NOT NULL)")
    assert [f["column"] for f in residual] == ["ts", "name"]


def test_bigquery_only_join_needs_approval_to_read_in_full(setup):
    """No database input, so the old cross-source check never fired; a full
    BigQuery read is billed, so it needs the same approval. Previews don't."""
    left = setup.open({"kind": "bq", "resource_id": RID, "table": "variants"})
    right = setup.open({"kind": "bq", "resource_id": RID, "table": "variants"})
    body = {"base_id": left["dataset_id"], "steps": [{
        "right_id": right["dataset_id"], "how": "inner", "alias": "v2", "columns": None,
        "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}]}]}
    refused = setup.client.post("/api/datasets/join", json=body)
    assert refused.status_code == 400 and "BigQuery" in refused.text
    assert setup.fake.sessions == []
    preview = setup.client.post("/api/datasets/join/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert setup.fake.sessions == []
    approved = setup.client.post("/api/datasets/join", json={**body, "allow_loaded": True})
    assert approved.status_code == 200, approved.text
    assert setup.fake.sessions
