"""Date and conditional calculated fields agree on pandas, live PostgreSQL and DuckDB."""
import datetime as dt
import math

import duckdb
import pandas as pd
import pytest
from sqlalchemy import text

import calculations
import database
import datasets
import derive
import main
from source_models import DerivedSpec, source_dict

D = dt.date
ROWS = pd.DataFrame({
    "person_id": [1, 2, 3, 4, 5],
    "birth_date": [D(1980, 2, 29), D(2000, 12, 31), D(1990, 6, 15), D(2010, 1, 31), D(1975, 5, 5)],
    "visit_date": [D(2024, 2, 28), D(2024, 3, 1), None, D(2010, 3, 1), D(2024, 5, 5)],
    "index_text": ["2024-01-15", "2024-02-30", "not a date", "2010-01-31 08:00:00", None],
    "dx": ["E11", "I10", None, "it's", "E11"],
    "hba1c": [7.5, 5.0, None, 6.5, 9.1],
})
PARAMETERS = [{"name": "start", "kind": "date", "value": "2024-02-01"},
              {"name": "cut", "kind": "number", "value": 7}]
FIELDS = {
    "age": "AGE_AT(birth_date, visit_date)",
    "months": "DATEDIFF(month, birth_date, visit_date)",
    "follow_up_days": "DATEDIFF(day, index_text, visit_date)",
    "weeks_back": "DATEDIFF('week', visit_date, DATE '2024-01-01')",
    "age_negated": "-DATEDIFF(year, visit_date, birth_date)",
    "visit_month": "DATE_TRUNC(month, visit_date)",
    "visit_week": "date_trunc(week, visit_date)",
    "visit_or_default": "COALESCE(visit_date, DATE '1999-01-01')",
    "birth_year": "YEAR(birth_date) * 100 + MONTH(birth_date)",
    "has_diabetes": "dx = 'E11' OR hba1c >= 6.5",
    "band": "CASE WHEN dx = 'it''s' THEN 'quoted' WHEN hba1c IS NULL THEN 'unknown' "
            "WHEN hba1c >= 6.5 THEN 'high' ELSE 'normal' END",
    "in_window": "visit_date >= @start AND visit_date < DATE '2024-04-01'",
    "above_cut": "IF(hba1c > @cut, 1, 0)",
    "past_or_missing": "NOT (DATEDIFF(day, visit_date, TODAY()) < 0) OR visit_date IS NULL",
}
EXPECTED = {
    "age": [43, 23, None, 0, 49],
    "months": [527, 278, None, 1, 588],
    "follow_up_days": [44, None, None, 29, None],
    "weeks_back": [-8, -8, None, 722, -17],
    "age_negated": [43, 23, None, 0, 49],
    "visit_month": ["2024-02-01", "2024-03-01", None, "2010-03-01", "2024-05-01"],
    "visit_week": ["2024-02-26", "2024-02-26", None, "2010-03-01", "2024-04-29"],
    "visit_or_default": ["2024-02-28", "2024-03-01", "1999-01-01", "2010-03-01", "2024-05-05"],
    "birth_year": [198002, 200012, 199006, 201001, 197505],
    "has_diabetes": ["true", "false", None, "true", "true"],
    "band": ["high", "normal", "unknown", "quoted", "high"],
    "in_window": ["true", "true", None, "false", "false"],
    "above_cut": [1, 0, 0, 0, 1],
    "past_or_missing": ["true", "true", "true", "true", "true"],
}


def _plain(value):
    if value is None or (isinstance(value, float) and math.isnan(value)) or value is pd.NaT:
        return None
    if isinstance(value, (dt.date, pd.Timestamp)):
        return str(value)[:10]
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    return value


def check(dataset_id):
    result = None
    for name, expression in FIELDS.items():
        result = derive.derive(dataset_id, {"op": "expression", "name": name,
                                            "expression": expression, "parameters": PARAMETERS})
    rows = datasets.query(dataset_id, [], [], 0, 20)["rows"]
    by_id = {row[rows["columns"].index("person_id")]: dict(zip(rows["columns"], row))
             for row in rows["data"]}
    for name, expected in EXPECTED.items():
        assert [_plain(by_id[i][name]) for i in range(1, 6)] == expected, name
    profiles = {column["name"]: column for column in result["columns"]}
    month = profiles["visit_month"]
    assert month["filter_kind"] == "date"
    assert (month["min_date"], month["max_date"]) == ("2010-03-01", "2024-05-01")
    assert profiles["has_diabetes"]["filter_kind"] == "categorical"
    assert set(profiles["has_diabetes"]["values"]) == {"true", "false"}
    assert profiles["age"]["filter_kind"] == "range"
    assert (profiles["age"]["min"], profiles["age"]["max"]) == (0, 49)
    filtered = datasets.query(dataset_id, [
        {"column": "visit_month", "kind": "date", "start": "2024-01-01", "end": "2024-03-31"},
        {"column": "has_diabetes", "kind": "categorical", "values": ["true"]}], [], 0, 20)
    assert filtered["filtered"] == 1
    return result


def test_pandas_date_and_conditional_fields():
    opened = datasets.open_dataset(ROWS.copy(), "memory")
    try:
        check(opened["dataset_id"])
    finally:
        datasets.close_dataset(opened["dataset_id"])


def test_duckdb_date_and_conditional_fields(tmp_path):
    path = str(tmp_path / "dates.duckdb")
    con = duckdb.connect(path)
    con.register("frame", ROWS)
    con.execute("CREATE TABLE data AS SELECT person_id, CAST(birth_date AS DATE) AS birth_date, "
                "CAST(visit_date AS DATE) AS visit_date, index_text, dx, hba1c FROM frame")
    preview = con.execute("SELECT * FROM data").df()
    con.close()
    source = {"path": path, "table": "data", "columns": list(ROWS.columns), "rows": len(ROWS)}
    opened = datasets.open_dataset(preview, "disk", disk_source=source)
    try:
        check(opened["dataset_id"])
    finally:
        datasets.close_dataset(opened["dataset_id"])


@pytest.fixture
def date_table(engine, monkeypatch):
    monkeypatch.setattr(database, "get_engine_for_resource", lambda rid: engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS public.calc_dates_test"))
        conn.execute(text("CREATE TABLE public.calc_dates_test (person_id integer, birth_date date, "
                          "visit_date timestamp, index_text text, dx text, hba1c double precision)"))
        for row in ROWS.to_dict("records"):
            conn.execute(text("INSERT INTO public.calc_dates_test VALUES "
                              "(:person_id, :birth_date, :visit_date, :index_text, :dx, :hba1c)"),
                         {**row, "hba1c": None if pd.isna(row["hba1c"]) else row["hba1c"]})
    yield {"kind": "aurora", "resource_id": "omopdb", "schema": "public", "table": "calc_dates_test"}
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE public.calc_dates_test"))


def test_postgres_date_and_conditional_fields_and_recipe(date_table):
    opened = main._open_source(date_table)
    try:
        result = check(opened["dataset_id"])
        assert result["query_scope"] == "database"
        spec = result["source_ref"]["spec"]
        assert spec["expression"] == FIELDS["past_or_missing"]
        assert spec["parameters"][0] == {"name": "start", "kind": "date", "value": "2024-02-01"}
        reopened = main._open_source(result["source_ref"])
        try:
            rows = datasets.query(reopened["dataset_id"], [], [], 0, 20)["rows"]
            index = rows["columns"].index("in_window")
            ids = rows["columns"].index("person_id")
            assert {row[ids]: row[index] for row in rows["data"]}[1] == "true"
            kinds = {c["name"]: c["filter_kind"] for c in reopened["columns"]}
            assert kinds["visit_month"] == "date" and kinds["has_diabetes"] == "categorical"
        finally:
            datasets.close_dataset(reopened["dataset_id"])
    finally:
        datasets.close_dataset(opened["dataset_id"])


PAIRS = [("2024-01-31", "2024-02-29"), ("2024-02-29", "2024-03-31"), ("2023-01-31", "2023-02-28"),
         ("2020-02-29", "2023-02-28"), ("2020-02-29", "2024-02-29"), ("2010-01-31", "2010-03-01"),
         ("2024-03-15", "2024-03-15"), ("1999-12-31", "2000-01-01"), ("2024-05-31", "2023-06-30"),
         ("2024-03-01", "2024-01-31"), ("2024-02-29", "2020-02-29"), ("1980-07-10", "2025-07-09")]


def test_month_and_year_differences_match_postgres_age(engine):
    frame = pd.DataFrame({"s": [D.fromisoformat(a) for a, _ in PAIRS],
                          "e": [D.fromisoformat(b) for _, b in PAIRS]})
    types = {"s": "date", "e": "date"}
    months = calculations.parse("DATEDIFF(month, s, e)", ["s", "e"], types)
    years = calculations.parse("DATEDIFF(year, s, e)", ["s", "e"], types)
    params = {}

    def bind(value):
        params[f"p{len(params)}"] = value
        return f":p{len(params) - 1}"
    ours = [calculations.sql(calc, "postgres", lambda name: f"t.{name}", bind) for calc in (months, years)]
    values = ", ".join(f"(CAST(:s{i} AS date), CAST(:e{i} AS date))" for i in range(len(PAIRS)))
    for i, (a, b) in enumerate(PAIRS):
        params[f"s{i}"], params[f"e{i}"] = a, b
    sql = (f"SELECT {ours[0]}, {ours[1]}, "
           "EXTRACT(YEAR FROM age(t.e, t.s)) * 12 + EXTRACT(MONTH FROM age(t.e, t.s)), "
           f"EXTRACT(YEAR FROM age(t.e, t.s)) FROM (VALUES {values}) AS t(s, e)")
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).all()
    assert [(float(r[0]), float(r[1])) for r in rows] == [(float(r[2]), float(r[3])) for r in rows]
    local_months = calculations.evaluate(months, frame).tolist()
    local_years = calculations.evaluate(years, frame).tolist()
    assert local_months == [float(r[2]) for r in rows]
    assert local_years == [float(r[3]) for r in rows]


@pytest.mark.parametrize("expression, message", [
    ("FOO(1)", "Unknown function FOO()"),
    ("DATEDIFF(hour, birth_date, visit_date)", "Unknown unit 'hour'"),
    ("DATEDIFF(birth_date, visit_date)", "Unknown unit 'birth_date'"),
    ("DATEDIFF(day, birth_date)", "Write DATEDIFF(unit, start, end)"),
    ("AGE_AT(birth_date)", "Write AGE_AT(birth_date, index_date)"),
    ("YEAR(hba1c)", "Column hba1c holds numbers"),
    ("visit_date + 1", "Column visit_date holds dates"),
    ("IF(hba1c, 1, 0)", "true/false condition"),
    ("IF(hba1c > 1, 1, 'x')", "IF results must all be one type"),
    ("CASE WHEN hba1c > 1 THEN DATE '2024-01-01' ELSE 2 END", "CASE results must all be one type"),
    ("dx < 'E'", "compares numbers or dates"),
    ("hba1c = 'x'", "Column hba1c holds numbers"),
    ("dx = NULL", "Use IS NULL"),
    ("DATE '2024-02-30'", "not a real date"),
    ("DATE '24-1-1'", "YYYY-MM-DD"),
    ("hba1c > 1 > 0", "Combine comparisons with AND / OR"),
    ("CASE WHEN hba1c > 1 THEN 1", "Expected END"),
    ("@missing + 1", "Unknown parameter @missing"),
    ("hba1c ** 2", "Powers"),
    ("hba1c; DROP TABLE x", "Unexpected character ';'"),
    ("nope + 1", "Unknown column: nope"),
    ("NULL", "can't be only NULL"),
    ("COALESCE(hba1c)", "COALESCE takes 2 to 10 values"),
    ("TODAY(1)", "Write TODAY()"),
    ("(" * 30 + "1" + ")" * 30, "too deeply nested"),
    ("+".join(["1"] * 300), "too complex"),
])
def test_invalid_expressions_name_the_problem(expression, message):
    types = calculations.column_types(ROWS)
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)").replace("*", r"\*")):
        calculations.parse(expression, ROWS.columns, types, PARAMETERS)


def test_keyword_named_columns_and_text_literals_stay_safe():
    frame = pd.DataFrame({"end": [1.0, 2.0], "null": [3.0, None], "date": ["2024-01-01", "x"]})
    calc = calculations.parse("end + null + YEAR(date)", frame.columns, calculations.column_types(frame))
    assert calculations.evaluate(calc, frame).tolist()[0] == 2028
    hostile = calculations.parse("CASE WHEN date = 'x'') OR 1=1 --' THEN 1 ELSE 0 END", frame.columns,
                                 calculations.column_types(frame))
    assert "OR 1=1" in calculations.sql(hostile, "duckdb", lambda n: f'"{n}"')
    assert "''" in calculations.sql(hostile, "duckdb", lambda n: f'"{n}"')
    params = {}
    pg = calculations.sql(hostile, "postgres", lambda n: f'"{n}"',
                          lambda v: params.setdefault(f":p{len(params)}", v) and f":p{len(params) - 1}")
    assert "OR 1=1" not in pg and "x') OR 1=1 --" in params.values()


def test_spec_validation_is_pydantic_and_reaches_the_api(client):
    with pytest.raises(ValueError, match="Unknown function"):
        DerivedSpec.model_validate({"op": "expression", "name": "x", "expression": "bad(1)"})
    with pytest.raises(ValueError, match="Unknown parameter @idx"):
        DerivedSpec.model_validate({"op": "expression", "name": "x", "expression": "@idx"})
    with pytest.raises(ValueError, match="valid YYYY-MM-DD"):
        DerivedSpec.model_validate({"op": "expression", "name": "x", "expression": "@idx",
                                    "parameters": [{"name": "idx", "kind": "date", "value": "soon"}]})
    ref = {"kind": "derived", "base": {"kind": "aurora", "resource_id": "omopdb", "table": "person"},
           "spec": {"op": "expression", "name": "age", "expression": "AGE_AT(b, @idx)",
                    "parameters": [{"name": "idx", "kind": "date", "value": "2024-01-01"}]}}
    assert source_dict(ref)["spec"]["parameters"][0]["value"] == "2024-01-01"
    opened = datasets.open_dataset(ROWS.copy(), "memory")
    try:
        url = f"/api/datasets/{opened['dataset_id']}/derive"
        bad = client.post(url, json={"op": "expression", "name": "x", "expression": "DATEDIFF(hour, a, b)"})
        assert bad.status_code == 422
        assert "Unknown unit 'hour'" in bad.json()["detail"][0]["msg"]
        typed = client.post(url, json={"op": "expression", "name": "x", "expression": "YEAR(hba1c)"})
        assert typed.status_code == 400 and "holds numbers" in typed.json()["detail"]
        good = client.post(url, json={"op": "expression", "name": "index age",
                                      "expression": "AGE_AT(birth_date, @idx)",
                                      "parameters": [{"name": "idx", "kind": "date", "value": "2024-01-01"}]})
        assert good.status_code == 200, good.text
        assert {c["name"]: c["filter_kind"] for c in good.json()["columns"]}["index age"] == "range"
    finally:
        datasets.close_dataset(opened["dataset_id"])


def test_compiled_sql_stays_bounded():
    columns = ["a", "b"]
    types = {"a": "text", "b": "text"}
    nested = "DATEDIFF(month, COALESCE(a, b), COALESCE(b, a))"
    calc = calculations.parse(f"DATEDIFF(year, DATE_TRUNC(month, COALESCE(a, b)), COALESCE(b, a)) + {nested}",
                              columns, types)
    assert len(calculations.sql(calc, "postgres", lambda n: f'"{n}"', lambda v: ":p")) < calculations.MAX_SQL
    huge = " + ".join([nested] * 12)
    with pytest.raises(ValueError, match="too complex"):
        calculations.sql(calculations.parse(huge, columns, types), "postgres", lambda n: f'"{n}"', lambda v: ":p")
