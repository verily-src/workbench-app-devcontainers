import uuid

import pandas as pd
import pytest
from scipy import stats

import compare
import datasets
import db
from scipy import stats


def test_live_compare_uses_full_source_and_null_safe_rest(engine, monkeypatch):
    name = f"compare_{uuid.uuid4().hex[:10]}"
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f'CREATE TABLE public."{name}" '
            '(entity_id integer, metric double precision, unique_metric integer, '
            'category text, cohort text)')
        conn.exec_driver_sql(
            f'INSERT INTO public."{name}" '
            'SELECT n, CASE WHEN n %% 2 = 0 THEN (n %% 30)::float8 '
            'ELSE 100 + (n %% 30)::float8 END, n, '
            "CASE WHEN n <= 30000 THEN 'Other' ELSE 'c' || (n %% 13)::text END, "
            "CASE WHEN n %% 2 = 0 THEN 'A' ELSE 'B' END "
            'FROM generate_series(1, 120000) n')
        conn.exec_driver_sql(
            f'INSERT INTO public."{name}" VALUES (120001, NULL, 120001, NULL, NULL)')
    monkeypatch.setattr(db, "get_engine_for_resource", lambda _rid: engine)
    sample = pd.DataFrame({"entity_id": list(range(1, 21)),
                           "metric": [float(i) for i in range(1, 21)],
                           "unique_metric": [float(i) for i in range(1, 21)],
                           "category": [f"c{i % 4}" for i in range(1, 21)],
                           "cohort": ["A" if i % 2 == 0 else "B" for i in range(1, 21)]})
    opened = datasets.open_dataset(
        sample, "large cohort",
        live_source={"resource_id": "compare-test",
                     "sql": f'SELECT * FROM public."{name}"',
                     "columns": {c: c for c in sample.columns}},
        capped=True)
    try:
        result = compare.compare(
            opened["dataset_id"],
            [{"column": "cohort", "kind": "categorical", "values": ["A"]}],
            [], b_is_rest=True)
        assert result["scope"] == "database"
        assert (result["a_n"], result["b_n"], result["n_overlap"]) == (60000, 60001, 0)
        metric = next(r for r in result["results"] if r["column"] == "metric")
        assert metric["a"]["n"] == 60000
        assert metric["b"]["n"] == 60000
        assert metric["a"]["mean"] == 14.0
        assert metric["b"]["mean"] == 115.0
        assert metric["p"] == 0.0
        category = next(r for r in result["results"] if r["column"] == "category")
        assert category["a"]["n"] == 60000
        assert category["b"]["n"] == 60000
        labels = [item["value"] for item in category["a"]["top"]]
        assert "Other" in labels
        assert "Other (remaining categories)" in labels

        exact = compare.compare(
            opened["dataset_id"],
            [{"column": "cohort", "kind": "categorical", "values": ["A"]},
             {"column": "entity_id", "kind": "range", "min": 1, "max": 16}],
            [{"column": "cohort", "kind": "categorical", "values": ["B"]},
             {"column": "entity_id", "kind": "range", "min": 1, "max": 16}])
        exact_metric = next(r for r in exact["results"] if r["column"] == "metric")
        expected = stats.mannwhitneyu([2, 4, 6, 8, 10, 12, 14, 16],
                                      [101, 103, 105, 107, 109, 111, 113, 115],
                                      alternative="two-sided")
        assert exact_metric["p"] == compare._p(expected.pvalue)

        unbalanced = compare.compare(
            opened["dataset_id"],
            [{"column": "cohort", "kind": "categorical", "values": ["A"]},
             {"column": "entity_id", "kind": "range", "min": 1, "max": 10}],
            [], b_is_rest=True)
        unbalanced_metric = next(r for r in unbalanced["results"]
                                 if r["column"] == "unique_metric")
        excluded = {2, 4, 6, 8, 10}
        reference = stats.mannwhitneyu(
            [2, 4, 6, 8, 10], [i for i in range(1, 120002) if i not in excluded],
            alternative="two-sided", method="asymptotic")
        assert unbalanced_metric["a"]["n"] == 5
        assert unbalanced_metric["b"]["n"] == 119996
        assert unbalanced_metric["p"] == compare._p(reference.pvalue)
        assert "asymptotic" in unbalanced_metric["note"]

        overlap = compare.compare(
            opened["dataset_id"],
            [{"column": "cohort", "kind": "categorical", "values": ["A"]}],
            [{"column": "cohort", "kind": "categorical", "values": ["A", "B"]}])
        assert overlap["n_overlap"] == 60000

        dataset = datasets.get(opened["dataset_id"])
        dataset["column_settings"] = [{"name": "metric", "filter_kind": "categorical"}]
        cohort_a = [{"column": "cohort", "kind": "categorical", "values": ["A"]}]
        cohort_b = [{"column": "cohort", "kind": "categorical", "values": ["B"]}]
        live_override = compare.compare(opened["dataset_id"], cohort_a, cohort_b)
        assert next(r for r in live_override["results"]
                    if r["column"] == "metric")["kind"] == "categorical"

        live_source = dataset.pop("live_source")
        try:
            loaded_override = compare.compare(opened["dataset_id"], cohort_a, cohort_b)
            assert next(r for r in loaded_override["results"]
                        if r["column"] == "metric")["kind"] == "categorical"
            dataset["column_settings"] = [{"name": "metric", "filter_kind": "none"}]
            hidden = compare.compare(opened["dataset_id"], cohort_a, cohort_b)
            assert all(r["column"] != "metric" for r in hidden["results"])
        finally:
            dataset["live_source"] = live_source
    finally:
        datasets.close_dataset(opened["dataset_id"])
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP TABLE public."{name}"')
