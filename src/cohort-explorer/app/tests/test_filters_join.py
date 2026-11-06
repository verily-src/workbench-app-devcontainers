"""get_filters used to run one query per filterable column. Against a plain
Aurora table that's cheap, but a join-backed model's __table__ is the whole
multi-way JOIN, so every one of those per-column queries re-ran the entire
join from scratch -- the more tables joined, the more that cost multiplied,
until it blew past the frontend's request timeout.

These tests exercise get_filters against a real (SQLite) 3-table fan-out
join and check that results match the pre-refactor per-column semantics
exactly -- categorical counts, cross-filter exclusion, and a text-backed
numeric range -- while only materializing the join once per request.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from starlette.requests import Request


def _make_three_table_join_db():
    """person(1, west) has 2 conditions and 1 measurement; person(2, east)
    has 1 condition and 1 measurement -- 3 joined rows total."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "person" (person_id INTEGER, region TEXT)'))
        conn.execute(text('CREATE TABLE "condition_occurrence" (person_id INTEGER, code TEXT)'))
        conn.execute(text('CREATE TABLE "measurement" (person_id INTEGER, score TEXT)'))
        conn.execute(text('INSERT INTO "person" VALUES (1, \'west\'), (2, \'east\')'))
        conn.execute(text(
            'INSERT INTO "condition_occurrence" VALUES (1, \'A\'), (1, \'B\'), (2, \'C\')'
        ))
        conn.execute(text(
            'INSERT INTO "measurement" VALUES (1, \'10.5\'), (2, \'20.0\')'
        ))
    return engine


def _activate_join_mapping(dynamic_model):
    select_sql = (
        'SELECT ROW_NUMBER() OVER () AS "_rowid", '
        't0."person_id" AS "person_id", t0."region" AS "region", '
        't1."code" AS "code", t2."score" AS "score" '
        'FROM "person" AS t0 '
        'LEFT JOIN "condition_occurrence" AS t1 ON t0."person_id" = t1."person_id" '
        'LEFT JOIN "measurement" AS t2 ON t0."person_id" = t2."person_id"'
    )
    mappings = [
        {"column": "person_id", "type": "integer", "filter": "none", "label": "Person Id", "storage_type": "integer"},
        {"column": "region", "type": "text", "filter": "categorical", "label": "Region", "storage_type": "text"},
        {"column": "code", "type": "text", "filter": "categorical", "label": "Code", "storage_type": "text"},
        {"column": "score", "type": "float", "filter": "range", "label": "Score", "storage_type": "text"},
    ]
    dynamic_model.set_active_join_mapping(
        mappings, select_sql, resource_id="test-resource",
        table_name="joined", entity_column="person_id",
    )


def _request(query_string: str = "") -> Request:
    return Request({"type": "http", "query_string": query_string.encode()})


def test_get_filters_on_join_with_no_filters(monkeypatch, tmp_path):
    import dynamic_model
    import main

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")
    _activate_join_mapping(dynamic_model)
    engine = _make_three_table_join_db()

    with Session(engine) as db:
        result = main.get_filters(_request(), db)

    assert result["region"] == [
        {"value": "east", "label": "east", "count": 1},
        {"value": "west", "label": "west", "count": 2},
    ]
    assert result["code"] == [
        {"value": "A", "label": "A", "count": 1},
        {"value": "B", "label": "B", "count": 1},
        {"value": "C", "label": "C", "count": 1},
    ]
    assert result["score"] == {"min": 10.5, "max": 20.0}


def test_get_filters_on_join_applies_cross_filter_exclusion(monkeypatch, tmp_path):
    import dynamic_model
    import main

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")
    _activate_join_mapping(dynamic_model)
    engine = _make_three_table_join_db()

    with Session(engine) as db:
        result = main.get_filters(_request("region=west"), db)

    # region excludes its own filter, so it still shows every option.
    assert result["region"] == [
        {"value": "east", "label": "east", "count": 1},
        {"value": "west", "label": "west", "count": 2},
    ]
    # code and score are restricted to person 1's (west's) rows.
    assert result["code"] == [
        {"value": "A", "label": "A", "count": 1},
        {"value": "B", "label": "B", "count": 1},
    ]
    assert result["score"] == {"min": 10.5, "max": 10.5}


def test_get_filters_on_join_is_repeatable_on_same_session(monkeypatch, tmp_path):
    """The temp table used to materialize the join must not leak across
    requests on a pooled connection -- calling get_filters twice on the same
    session must not fail with "table already exists"."""
    import dynamic_model
    import main

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")
    _activate_join_mapping(dynamic_model)
    engine = _make_three_table_join_db()

    with Session(engine) as db:
        first = main.get_filters(_request(), db)
        second = main.get_filters(_request(), db)

    assert first == second


def test_get_filters_on_plain_single_table_still_works(monkeypatch, tmp_path):
    """Non-join sources also go through the new materialized-base path;
    confirm that doesn't change their (already correct) behavior."""
    import dynamic_model
    import main
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from dynamic_model import DynamicBase, get_active_model, set_active_mapping

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")
    mappings = [
        {"column": "sample_id", "type": "text", "filter": "categorical", "label": "Sample"},
        {"column": "score", "type": "float", "filter": "range", "label": "Score"},
    ]
    set_active_mapping(mappings)
    engine = create_engine("sqlite://")
    DynamicBase.metadata.create_all(engine)

    with Session(engine) as db:
        model = get_active_model()
        db.add(model(sample_id="S1", score=1.5))
        db.add(model(sample_id="S2", score=3.5))
        db.commit()
        result = main.get_filters(_request(), db)

    assert result["sample_id"] == [
        {"value": "S1", "label": "S1", "count": 1},
        {"value": "S2", "label": "S2", "count": 1},
    ]
    assert result["score"] == {"min": 1.5, "max": 3.5}
