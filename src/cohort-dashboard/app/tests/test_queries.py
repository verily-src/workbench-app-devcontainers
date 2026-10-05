import pandas as pd
import pytest

import queries


def test_quote_rejects_injection():
    with pytest.raises(ValueError):
        queries._quote('films"; DROP TABLE films; --')


def test_quote_accepts_plain_identifier():
    assert queries._quote("film_list") == '"film_list"'


def test_create_s3_foreign_table_rejects_non_s3_location():
    with pytest.raises(ValueError):
        queries.create_s3_foreign_table(
            engine=None, name="t", location="http://evil", file_format="parquet",
            region="us-east-1")


def test_create_s3_foreign_table_rejects_unknown_format():
    with pytest.raises(ValueError):
        queries.create_s3_foreign_table(
            engine=None, name="t", location="s3://bucket/x", file_format="csv",
            region="us-east-1")


def test_infer_filter_kinds():
    df = pd.DataFrame({
        "tissue": (["liver", "lung", "heart", "skin"] * 25),
        "rin_score": [float(i) / 10 for i in range(100)],
        "sample_id": [f"GTEX-{i}" for i in range(100)],
        "flag": [True, False] * 50,
        "empty": [None] * 100,
    })
    kinds = queries.infer_filter_kinds(df)
    assert kinds["tissue"] == "categorical"
    assert kinds["rin_score"] == "range"
    assert kinds["sample_id"] == "none"
    assert kinds["flag"] == "categorical"
    assert kinds["empty"] == "none"
