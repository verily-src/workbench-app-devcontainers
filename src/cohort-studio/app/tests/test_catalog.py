"""Views-only DuckDB catalogs over local Parquet, no network: build,
attach READ_ONLY, list, fetch, and the layout-change workflow."""

import duckdb
import pandas as pd
import pytest

import catalog


@pytest.fixture
def data_dir(tmp_path):
    root = tmp_path / "bucket"
    (root / "services" / "year=2024").mkdir(parents=True)
    (root / "services" / "year=2025").mkdir(parents=True)
    pd.DataFrame({"sample_id": [f"s{i}" for i in range(20)],
                  "tissue": ["liver", "lung"] * 10}).to_parquet(
        root / "samples.parquet")
    pd.DataFrame({"train": [1, 2, 3], "station": ["a", "b", "c"]}).to_parquet(
        root / "services" / "year=2024" / "part0.parquet")
    pd.DataFrame({"train": [4, 5], "station": ["d", "e"]}).to_parquet(
        root / "services" / "year=2025" / "part0.parquet")
    return root


FILES = ["samples.parquet", "services/year=2024/part0.parquet",
         "services/year=2025/part0.parquet"]


@pytest.fixture
def built(data_dir, tmp_path):
    views, skipped = catalog.plan_views(FILES, str(data_dir))
    path = str(tmp_path / "rail_catalog.duckdb")
    out = catalog.build_catalog_file(path, views)
    assert skipped == [] and out["skipped"] == []
    return path


def test_plan_views_groups_hive_partitions_and_uses_absolute_paths(data_dir):
    views, skipped = catalog.plan_views(FILES, str(data_dir))
    by_name = dict(views)
    assert set(by_name) == {"samples", "services"}
    assert f"'{data_dir}/samples.parquet'" in by_name["samples"]
    assert f"'{data_dir}/services/*=*/*.parquet'" in by_name["services"]
    assert "hive_partitioning = true" in by_name["services"]
    assert skipped == []


def test_plan_views_sanitizes_dedupes_and_skips_own_artefacts():
    views, skipped = catalog.plan_views(
        ["a-b.csv", "sub/a_b.csv", "2024 data.parquet", "a-b.parquet",
         "_catalog/old.parquet", "_studio_views/v.json",
         "bad'name.csv"], "s3://bucket/folder", reserved={"a_b"})
    names = [n for n, _ in views]
    assert len(names) == len(set(names))
    assert "a_b" not in names                     # reserved by a user view
    assert {"a_b_2", "a_b_3", "sub_a_b", "v_2024_data"} == set(names)
    assert all("_catalog" not in sql and "_studio_views" not in sql
               for _, sql in views)
    assert [s["name"] for s in skipped] == ["bad'name.csv"]


def test_catalog_lists_views_and_holds_no_data(built):
    objects = catalog.list_objects(built)
    assert [(o["name"], o["kind"]) for o in objects] == [
        ("samples", "view"), ("services", "view")]
    assert "read_parquet" in objects[0]["sql"]
    assert catalog.verify_views_only(built) == 2
    con = duckdb.connect()
    con.execute(f"ATTACH '{built}' AS c (READ_ONLY)")
    assert con.execute("SELECT count(*) FROM duckdb_tables() "
                       "WHERE database_name = 'c'").fetchone()[0] == 0
    con.close()
    import os
    assert os.path.getsize(built) < 1024 * 1024


def test_fetch_view_respects_cap(built):
    assert len(catalog.fetch_view(built, "samples", cap=5)) == 5
    assert len(catalog.fetch_view(built, "samples", cap=100)) == 20


def test_glob_view_reads_every_partition(built):
    df = catalog.fetch_view(built, "services", cap=100)
    assert sorted(df["train"]) == [1, 2, 3, 4, 5]
    assert sorted(df["year"].astype(int).unique()) == [2024, 2025]


def test_read_only_attachment_rejects_writes(built):
    con = catalog._attach(built, None)
    try:
        for sql in ("CREATE TABLE cat.t AS SELECT 1 AS x",
                    "CREATE OR REPLACE VIEW cat.samples AS SELECT 1",
                    "INSERT INTO cat.samples VALUES ('x', 'y')"):
            with pytest.raises(duckdb.Error):
                con.execute(sql)
    finally:
        con.close()
    assert catalog.verify_views_only(built) == 2


@pytest.mark.parametrize("bad", [
    "samples; DROP VIEW services", '"samples"', "nope", "cat.samples",
    "samples' --"])
def test_fetch_view_rejects_names_not_in_catalog(built, bad):
    with pytest.raises(catalog.UnknownView):
        catalog.fetch_view(built, bad, cap=5)


def test_layout_change_absorbed_by_replacing_views(built, data_dir):
    # Edit a local copy (writable), as a publisher would before re-upload.
    con = duckdb.connect(built)
    con.execute(
        "CREATE OR REPLACE VIEW services AS SELECT * EXCLUDE (station), "
        "station AS station_name FROM read_parquet("
        f"'{data_dir}/services/year=2025/*.parquet')")
    con.close()
    df = catalog.fetch_view(built, "services", cap=100)
    assert sorted(df["train"]) == [4, 5]
    assert "station_name" in df.columns and "station" not in df.columns
    assert catalog.verify_views_only(built) == 2


def test_missing_source_error_names_the_source(built, data_dir):
    (data_dir / "samples.parquet").unlink()
    with pytest.raises(RuntimeError) as err:
        catalog.fetch_view(built, "samples", cap=5)
    assert f"{data_dir}/samples.parquet" in str(err.value)
    assert "samples" in str(err.value)


def test_verify_views_only_rejects_tables(tmp_path):
    path = str(tmp_path / "bad.duckdb")
    con = duckdb.connect(path)
    con.execute("CREATE TABLE leaked AS SELECT 1 AS x")
    con.close()
    with pytest.raises(RuntimeError, match="leaked"):
        catalog.verify_views_only(path)


def test_build_skips_unreadable_auto_views_but_fails_strict(data_dir,
                                                            tmp_path):
    views = [("ok", f"SELECT * FROM read_parquet('{data_dir}/samples.parquet')"),
             ("gone", f"SELECT * FROM read_parquet('{data_dir}/none.parquet')")]
    out = catalog.build_catalog_file(str(tmp_path / "a.duckdb"), views)
    assert out["views"] == ["ok"]
    assert [s["name"] for s in out["skipped"]] == ["gone"]
    with pytest.raises(ValueError, match="gone"):
        catalog.build_catalog_file(str(tmp_path / "b.duckdb"), views,
                                   strict={"gone"})


def test_select_sql_accepts_one_select_only():
    assert catalog.select_sql(
        "WITH a AS (SELECT 1 AS x) SELECT * FROM a;  ") == \
        "WITH a AS (SELECT 1 AS x) SELECT * FROM a"
    for bad in ("SELECT 1; DROP TABLE x", "CREATE TABLE t AS SELECT 1",
                "INSERT INTO t VALUES (1)", "ATTACH 'x.db'", "SELEC 1"):
        with pytest.raises(ValueError):
            catalog.select_sql(bad)


def test_resolve_ids(monkeypatch):
    monkeypatch.setattr(catalog.db, "resolve_s3_uri",
                        lambda rid: f"s3://bkt/{rid}")
    assert catalog.resolve("folder1/_catalog/c.duckdb") == (
        "s3://bkt/folder1/_catalog/c.duckdb", "folder1")
    with pytest.raises(ValueError):
        catalog.resolve("folder1/data.parquet")
    with pytest.raises(ValueError):
        catalog.resolve("https://evil.example/c.duckdb")
    monkeypatch.setenv("STUDIO_CATALOG_URLS",
                       "https://data.example/rail.duckdb, ftp://x/y.duckdb")
    assert catalog.resolve("https://data.example/rail.duckdb") == (
        "https://data.example/rail.duckdb", None)


def test_attach_rejects_quote_in_uri():
    with pytest.raises(ValueError):
        catalog.list_objects("/tmp/x'; ATTACH 'y.duckdb")


def test_discover_lists_catalogs_and_configured_urls(monkeypatch):
    catalog.invalidate()
    monkeypatch.setattr(catalog.duck, "list_s3_catalogs", lambda rid: {
        "f1": ["_catalog/rail.duckdb"], "f2": []}[rid])
    monkeypatch.setenv("STUDIO_CATALOG_URLS", "https://data.example/r.duckdb")
    sources, pending = catalog.discover(["f1", "f2"], wait=5)
    assert pending is False
    assert [s["id"] for s in sources] == [
        "f1/_catalog/rail.duckdb", "https://data.example/r.duckdb"]
    assert all(s["kind"] == "catalog" for s in sources)
    catalog.invalidate()
