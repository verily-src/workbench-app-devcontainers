"""Parquet folders and gzipped CSV from S3; Parquet and gzip in local upload."""
import gzip
import io
from datetime import datetime

import duckdb
import pytest
from fastapi.testclient import TestClient

import datasets
import disk_data
import duck
import joins
import main


def _write_parquet(path, sql):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET)")
    con.close()


def test_parquet_parts_group_into_folder_entries():
    entries = [
        {"name": "events/year=2024/part-0.parquet", "bytes": 10, "modified": "2024-01-02 00:00:00"},
        {"name": "events/year=2025/part-0.parquet", "bytes": 15, "modified": "2025-03-01 00:00:00"},
        {"name": "flat/part-0.parquet", "bytes": 1},
        {"name": "flat/part-1.parquet", "bytes": 2},
        {"name": "flat/readme.csv", "bytes": 99},
        {"name": "single/only.parquet", "bytes": 5},
        {"name": "top.parquet", "bytes": 5},
        {"name": "flat/upper.PARQUET", "bytes": 50},
    ]
    folders = duck.parquet_folders(entries)
    assert [f["name"] for f in folders] == ["events/", "flat/"]
    events = folders[0]
    assert events["parts"] == 2 and events["bytes"] == 25
    assert events["modified"] == "2025-03-01 00:00:00"
    assert events["detail"] == "Parquet folder · 2 parts"
    assert folders[1]["bytes"] == 3


def test_describe_lists_folders_before_files_and_csv_gz(monkeypatch):
    lines = [f"2024-01-01 00:00:00 {size} pre/{name}" for size, name in [
        (10, "events/year=2024/a.parquet"), (20, "events/year=2025/b.parquet"),
        (30, "claims.csv.gz"), (40, "notes.pdf")]]
    monkeypatch.setattr(duck, "_registered_s3_files", lambda *a, **k: None)
    monkeypatch.setattr(duck, "_s3_ls", lambda rid: ("\n".join(lines), "pre"))
    names = [entry["name"] for entry in duck.describe_s3_files("bucket")]
    assert names == ["events/", "events/year=2024/a.parquet",
                     "events/year=2025/b.parquet", "claims.csv.gz"]


def test_folder_grouping_sees_parts_past_the_listing_cap(monkeypatch):
    lines = [f"2024-01-01 00:00:00 1 pre/aaa/part-{i:04}.parquet"
             for i in range(duck.MAX_LISTING + 20)]
    lines.append("2024-01-01 00:00:00 1 pre/zzz/part-0.parquet")
    lines.append("2024-01-01 00:00:00 1 pre/zzz/part-1.parquet")
    monkeypatch.setattr(duck, "_registered_s3_files", lambda *a, **k: None)
    monkeypatch.setattr(duck, "_s3_ls", lambda rid: ("\n".join(lines), "pre"))
    folders = [e for e in duck.describe_s3_files("bucket") if e["name"].endswith("/")]
    assert [(f["name"], f["parts"]) for f in folders] == [
        ("aaa/", duck.MAX_LISTING + 20), ("zzz/", 2)]


@pytest.mark.parametrize("name", ["events/", "a/b/", "claims.csv.gz"])
def test_folder_and_gzip_keys_validate(name):
    assert duck._validate_relative_key(name) == name


@pytest.mark.parametrize("name", ["/", "../up/", "a//", "./", "a/../b/", "bad'quote/", "a*/"])
def test_unsafe_folder_keys_are_rejected(name):
    with pytest.raises(ValueError):
        duck._validate_relative_key(name)


def test_folder_reader_reads_every_part_with_partitions(tmp_path):
    _write_parquet(tmp_path / "events/year=2024/p.parquet", "SELECT 1 AS id")
    _write_parquet(tmp_path / "events/year=2025/p.parquet", "SELECT 2 AS id, 'x' AS extra")
    sql = duck._reader_sql(f"{tmp_path}/events/")
    rows = duckdb.connect().execute(f"SELECT id, year, extra FROM {sql} ORDER BY id").fetchall()
    assert rows == [(1, 2024, None), (2, 2025, "x")]


def test_open_parquet_folder_through_the_api(tmp_path, monkeypatch):
    for part in range(3):
        _write_parquet(tmp_path / f"cohort/part-{part}.parquet",
                       f"SELECT {part} AS id, 'p{part}' AS label")
    seen = []

    def folder_size(resource_id, folder):
        seen.append((resource_id, folder))
        return 123, f"{tmp_path}/{folder}", "us-east-1", False

    monkeypatch.setattr(disk_data, "_folder_size", folder_size)
    monkeypatch.setattr(disk_data, "_object_size",
                        lambda *_: pytest.fail("folders must not use head_object"))
    monkeypatch.setattr(duck, "_connect", lambda *a, **k: duckdb.connect())
    client = TestClient(main.app)
    response = client.post("/api/datasets/open",
                           json={"kind": "s3", "resource_id": "fixture", "table": "cohort/"})
    assert response.status_code == 200, response.text
    body = response.json()
    try:
        assert seen == [("fixture", "cohort/")]
        assert body["rows"] == 3
        assert {c["name"] for c in body["columns"]} >= {"id", "label"}
    finally:
        datasets.close_dataset(body["dataset_id"])


class _FakeS3:
    def __init__(self, pages):
        self.pages = pages
        self.requests = []

    def list_objects_v2(self, **request):
        self.requests.append(request)
        return self.pages[len(self.requests) - 1]


def test_folder_size_sums_parquet_parts_across_pages(monkeypatch):
    fake = _FakeS3([
        {"Contents": [{"Key": "pre/ev/a.parquet", "Size": 10},
                      {"Key": "pre/ev/_SUCCESS", "Size": 0}],
         "NextContinuationToken": "t1"},
        {"Contents": [{"Key": "pre/ev/year=1/b.parquet", "Size": 5},
                      {"Key": "pre/ev/year=1/c.PARQUET", "Size": 7}]},
    ])
    monkeypatch.setattr(disk_data, "_s3_client", lambda rid, name: (
        fake, "bucket", "pre/ev/", "s3://bucket/pre/ev/", "us-east-1", True))
    assert disk_data._folder_size("rid", "ev/") == (15, "s3://bucket/pre/ev/", "us-east-1", True)
    # c.PARQUET is not matched by the case-sensitive folder glob, so it is not counted.
    assert fake.requests[0]["Prefix"] == "pre/ev/"
    assert fake.requests[1]["ContinuationToken"] == "t1"


def test_folder_size_rejects_empty_and_oversized_folders(monkeypatch):
    empty = _FakeS3([{"Contents": [{"Key": "pre/ev/notes.txt", "Size": 1}]}])
    monkeypatch.setattr(disk_data, "_s3_client", lambda rid, name: (
        empty, "bucket", "pre/ev/", "s3://bucket/pre/ev/", "us-east-1", True))
    with pytest.raises(ValueError, match="No Parquet files"):
        disk_data._folder_size("rid", "ev/")
    monkeypatch.setattr(disk_data, "MAX_FOLDER_PARTS", 1)
    many = _FakeS3([{"Contents": [{"Key": f"pre/ev/{i}.parquet", "Size": 1} for i in range(2)]}])
    monkeypatch.setattr(disk_data, "_s3_client", lambda rid, name: (
        many, "bucket", "pre/ev/", "s3://bucket/pre/ev/", "us-east-1", True))
    with pytest.raises(disk_data.OperationTooLarge, match="narrower subfolder"):
        disk_data._folder_size("rid", "ev/")


def test_open_csv_gz_from_s3(tmp_path, monkeypatch):
    path = tmp_path / "claims.csv.gz"
    with gzip.open(path, "wt") as stream:
        stream.write("id,cost\n1,2.5\n2,3.5\n")
    monkeypatch.setattr(disk_data, "_object_size",
                        lambda *_: (path.stat().st_size, str(path), "us-east-1", False))
    monkeypatch.setattr(duck, "_connect", lambda *a, **k: duckdb.connect())
    frame, source = disk_data.open_s3({"resource_id": "fixture", "table": "claims.csv.gz"})
    try:
        assert source["rows"] == 2
        assert frame["cost"].tolist() == [2.5, 3.5]
    finally:
        disk_data.remove(source)


def _upload(name, payload):
    response = TestClient(main.app).post(
        "/api/datasets/upload", files={"file": (name, payload, "application/octet-stream")})
    if response.status_code == 200:
        datasets.close_dataset(response.json()["dataset_id"])
    return response


def test_upload_parquet(tmp_path):
    path = tmp_path / "local.parquet"
    _write_parquet(path, "SELECT * FROM (VALUES (1, 'a'), (2, 'b')) t(id, label)")
    response = _upload("local.parquet", path.read_bytes())
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == 2


@pytest.mark.parametrize("name,text", [("local.csv.gz", "id,x\n1,2\n2,3\n"),
                                       ("local.tsv.gz", "id\tx\n1\t2\n2\t3\n")])
def test_upload_gzipped_delimited(name, text):
    response = _upload(name, gzip.compress(text.encode()))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rows"] == 2
    assert [c["name"] for c in body["columns"]][:2] == ["id", "x"]


def test_upload_rejects_corrupt_parquet_and_unknown_types():
    bad = _upload("broken.parquet", b"not parquet")
    assert bad.status_code == 400 and "as Parquet" in bad.json()["detail"]
    other = _upload("reads.vcf.gz", gzip.compress(b"##fileformat=VCFv4.2\n"))
    assert other.status_code == 400 and "Unsupported file type" in other.json()["detail"]


def test_join_alias_for_folders_and_gzip():
    assert joins.default_alias("bucket / events/") == "events"
    assert joins.default_alias("bucket / claims.csv.gz") == "claims"


def test_uppercase_parts_are_neither_counted_nor_read(tmp_path):
    """The folder glob is case-sensitive, so counts must match what it reads."""
    _write_parquet(tmp_path / "mixed/a.parquet", "SELECT 1 AS id")
    _write_parquet(tmp_path / "mixed/b.parquet", "SELECT 2 AS id")
    _write_parquet(tmp_path / "mixed/c.PARQUET", "SELECT 3 AS id")
    names = [{"name": f"mixed/{p.name}", "bytes": 1} for p in (tmp_path / "mixed").iterdir()]
    assert duck.parquet_folders(names)[0]["parts"] == 2
    sql = duck._reader_sql(f"{tmp_path}/mixed/")
    assert duckdb.connect().execute(f"SELECT count(*) FROM {sql}").fetchone()[0] == 2


def _registered(monkeypatch, keys, sizes=1):
    import boto3
    import source_registry

    monkeypatch.setattr(source_registry, "s3_location",
                        lambda rid: ("s3://lake/pre", "us-east-1", "pre"))
    monkeypatch.setattr(source_registry, "get",
                        lambda kind, rid: {"bucket": "lake", "prefix": "pre"})

    class Client:
        def list_objects_v2(self, **request):
            start = int(request.get("ContinuationToken") or 0)
            page = keys[start:start + request["MaxKeys"]]
            out = {"Contents": [{"Key": f"pre/{k}", "Size": sizes} for k in page]}
            if start + len(page) < len(keys):
                out["NextContinuationToken"] = str(start + len(page))
            return out

    class Session:
        def __init__(self, **kwargs):
            pass

        def client(self, *args, **kwargs):
            return Client()

    monkeypatch.setattr(boto3, "Session", Session)


def test_registered_folders_count_parts_past_the_file_cap(monkeypatch):
    keys = [f"big/part-{i:04}.parquet" for i in range(duck.MAX_LISTING + 100)]
    keys += ["zzz/a.parquet", "zzz/b.parquet"]
    _registered(monkeypatch, keys, sizes=2)
    listed = duck.describe_s3_files("s3:lake")
    folders = {e["name"]: e for e in listed if e["name"].endswith("/")}
    assert folders["big/"]["parts"] == duck.MAX_LISTING + 100
    assert folders["big/"]["bytes"] == 2 * (duck.MAX_LISTING + 100)
    assert folders["zzz/"]["parts"] == 2
    assert len([e for e in listed if not e["name"].endswith("/")]) == duck.MAX_LISTING


def test_registered_folders_are_lower_bounds_when_the_scan_stops(monkeypatch):
    monkeypatch.setattr(duck, "MAX_FOLDER_SCAN", 3)
    _registered(monkeypatch, [f"ev/{i}.parquet" for i in range(5)])
    folder = duck.describe_s3_files("s3:lake")[0]
    assert folder["name"] == "ev/" and folder["partial"] is True
    assert folder["detail"] == "Parquet folder · at least 3 parts"
    assert "bytes" not in folder
