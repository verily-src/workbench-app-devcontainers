import pandas as pd
import pytest

import bq
import duck


S3_LS_OUTPUT = """\
                           PRE nested-folder/
2026-10-01 12:00:00    1048576 samples.parquet
2026-10-01 12:00:01       2048 metadata.csv
2026-10-01 12:00:02        512 notes.txt
2026-10-01 12:00:03       4096 model.bin
"""


def test_parse_s3_ls_filters_to_data_files():
    assert duck.parse_s3_ls(S3_LS_OUTPUT) == [
        "samples.parquet", "metadata.csv", "notes.txt"]


def test_parse_s3_ls_empty():
    assert duck.parse_s3_ls("") == []


def test_reader_sql_rejects_quote_injection():
    with pytest.raises(ValueError):
        duck._reader_sql("s3://bucket/x'); DROP TABLE y; --.csv")


def test_fetch_file_reads_local_csv(tmp_path):
    csv = tmp_path / "t.csv"
    pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]}).to_csv(
        csv, index=False)
    df = duck.fetch_file(str(csv), cap=2)
    assert len(df) == 2
    assert list(df.columns) == ["a", "b"]


def test_fetch_file_reads_local_parquet(tmp_path):
    pq = tmp_path / "t.parquet"
    pd.DataFrame({"n": range(10)}).to_parquet(pq)
    df = duck.fetch_file(str(pq), cap=100)
    assert len(df) == 10


def test_bq_rejects_bad_identifiers():
    with pytest.raises(ValueError):
        bq._validate("proj", "data`set; DROP")
