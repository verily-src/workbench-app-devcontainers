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

S3_LS_RECURSIVE = """\
2026-10-01 12:00:00    1048576 folder-id/sub/dir/counts.parquet
2026-10-01 12:00:01       2048 folder-id/top.csv
2026-10-01 12:00:03       4096 folder-id/sub/model.bin
"""


def test_parse_s3_ls_filters_to_data_files():
    assert duck.parse_s3_ls(S3_LS_OUTPUT) == [
        "samples.parquet", "metadata.csv", "notes.txt"]


def test_parse_s3_ls_recursive_strips_folder_prefix():
    assert duck.parse_s3_ls(S3_LS_RECURSIVE, prefix="folder-id") == [
        "sub/dir/counts.parquet", "top.csv"]


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


def test_connect_builds_config_secret_from_exported_creds(monkeypatch):
    calls = []

    class FakeCon:
        def execute(self, sql):
            calls.append(sql)
        def close(self):
            pass

    monkeypatch.setattr(duck.duckdb, "connect", lambda: FakeCon())
    monkeypatch.setattr(duck, "_resolve_credentials", lambda profile: {
        "AccessKeyId": "AKIA", "SecretAccessKey": "sk/+=",
        "SessionToken": "tok", "Expiration": "2026-01-01T00:00:00Z"})

    duck._connect("bench9232_scimilarity_data", region="us-east-1")
    secret_sql = next(c for c in calls if "CREATE OR REPLACE SECRET" in c)
    assert "PROVIDER config" in secret_sql
    assert "credential_chain" not in secret_sql  # the bug we fixed
    assert "KEY_ID 'AKIA'" in secret_sql
    assert "SESSION_TOKEN 'tok'" in secret_sql
    assert "REGION 'us-east-1'" in secret_sql


def test_connect_no_profile_skips_secret(monkeypatch):
    calls = []

    class FakeCon:
        def execute(self, sql):
            calls.append(sql)
        def close(self):
            pass

    monkeypatch.setattr(duck.duckdb, "connect", lambda: FakeCon())
    duck._connect(None)
    assert not any("SECRET" in c for c in calls)


def test_resolve_credentials_falls_back_to_credential_process(
        monkeypatch, tmp_path):
    # Simulate an old aws CLI: export-credentials prints usage, exits 2.
    class Usage:
        returncode = 2
        stdout = "usage: aws <command> <subcommand> help"
        stderr = ""

    # A config file whose profile's credential_process emits the JSON contract.
    emitter = tmp_path / "creds.sh"
    emitter.write_text(
        '#!/bin/sh\necho \'{"Version":1,"AccessKeyId":"AK",'
        '"SecretAccessKey":"SK","SessionToken":"TK"}\'\n')
    emitter.chmod(0o755)
    cfg = tmp_path / "ws.conf"
    cfg.write_text(
        "[profile bench9232_ho_data_internal]\n"
        f"credential_process = {emitter}\n")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(cfg))

    real_run = duck.subprocess.run

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["aws", "configure", "export-credentials"]:
            return Usage()
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(duck.subprocess, "run", fake_run)
    creds = duck._resolve_credentials("bench9232_ho_data_internal")
    assert creds["AccessKeyId"] == "AK"
    assert creds["SessionToken"] == "TK"
