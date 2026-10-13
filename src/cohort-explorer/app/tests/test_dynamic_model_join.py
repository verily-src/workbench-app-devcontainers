"""Tests that a join-backed dynamic model actually returns fanned-out rows,
and that it participates in the text-backed-numeric CAST path the same way
a single-table Aurora source does.

A 1:N join (e.g. one person joined to many condition rows) has no natural
column that is unique per output row -- not even the "count distinct by"
entity column, which legitimately repeats once per fanned-out row. If the
ORM's primary key were mapped to such a column, SQLAlchemy's identity map
would silently collapse rows that share it, quietly losing data. These tests
exercise set_active_join_mapping against a real (SQLite) join to prove the
synthetic ROW_NUMBER() row-id avoids that, regardless of fan-out.
"""
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session


def _make_fanned_out_sqlite_db():
    """person(id=1) has 3 condition rows; person(id=2) has 1. A query joining
    them should return 4 rows total, 2 of which share person_id=1."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE "person" (person_id INTEGER, name TEXT)'))
        conn.execute(text('CREATE TABLE "condition_occurrence" (condition_id INTEGER, person_id INTEGER, code TEXT)'))
        conn.execute(text('INSERT INTO "person" VALUES (1, \'alice\'), (2, \'bob\')'))
        conn.execute(text(
            "INSERT INTO \"condition_occurrence\" VALUES "
            "(100, 1, 'A'), (101, 1, 'B'), (102, 1, 'C'), (103, 2, 'D')"
        ))
    return engine


def test_join_mapping_preserves_fanned_out_rows(monkeypatch, tmp_path):
    import dynamic_model

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")
    engine = _make_fanned_out_sqlite_db()

    select_sql = (
        "SELECT ROW_NUMBER() OVER () AS \"_rowid\", "
        "t0.\"person_id\" AS \"person_id\", t0.\"name\" AS \"name\", "
        "t1.\"code\" AS \"code\" "
        "FROM \"person\" AS t0 "
        "LEFT JOIN \"condition_occurrence\" AS t1 ON t0.\"person_id\" = t1.\"person_id\""
    )
    mappings = [
        {"column": "person_id", "type": "integer", "filter": "categorical", "label": "Person Id", "storage_type": "integer"},
        {"column": "name", "type": "text", "filter": "categorical", "label": "Name", "storage_type": "text"},
        {"column": "code", "type": "text", "filter": "categorical", "label": "Code", "storage_type": "text"},
    ]

    dynamic_model.set_active_join_mapping(
        mappings, select_sql, resource_id="test-resource",
        table_name="joined", entity_column="person_id",
    )

    model = dynamic_model.get_active_model()
    with Session(engine) as db:
        rows = db.execute(select(model)).scalars().all()

    # All 4 fanned-out rows must come back -- if the ORM had mapped person_id
    # (non-unique) as the primary key instead of the synthetic row-id, the
    # identity map would have collapsed alice's 3 rows down to 1.
    assert len(rows) == 4
    assert sorted(r.code for r in rows) == ["A", "B", "C", "D"]
    assert dynamic_model.get_pk_name() == "_rowid"
    assert dynamic_model.get_entity_column() == "person_id"


def test_join_schema_persists_and_reloads(monkeypatch, tmp_path):
    import dynamic_model

    schema_file = tmp_path / "schema.json"
    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", schema_file)

    select_sql = 'SELECT ROW_NUMBER() OVER () AS "_rowid", t0."id" AS "id" FROM "t" AS t0'
    mappings = [{"column": "id", "type": "integer", "filter": "none", "label": "Id", "storage_type": "integer"}]
    dynamic_model.set_active_join_mapping(mappings, select_sql, resource_id="r1", entity_column="id")

    assert schema_file.exists()

    # Simulate a uvicorn restart: clear in-memory state, reload from disk.
    dynamic_model._active_mapping = None
    dynamic_model._active_model = None
    dynamic_model.DynamicBase.metadata.clear()

    dynamic_model.load_schema_from_disk()

    assert dynamic_model.get_active_mapping() == mappings
    assert dynamic_model.get_entity_column() == "id"
    assert dynamic_model.get_pk_name() == "_rowid"


def test_join_text_backed_numeric_column_is_mapped_as_text(monkeypatch, tmp_path):
    """A join output column reclassified integer/float from Aurora `text`
    storage must still be mapped as SQLAlchemy Text, exactly like a
    single-table Aurora source (dynamic_model.set_active_mapping) -- loading
    it as Integer/Float would hit the same driver failure CLAUDE.md's
    "Aurora numeric-text failure" lessons describe. Filtering/sorting then
    goes through main._query_column's CAST, not the storage type."""
    import dynamic_model
    from sqlalchemy import Text as SaText

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")

    select_sql = (
        'SELECT ROW_NUMBER() OVER () AS "_rowid", t0."score" AS "score" FROM "t" AS t0'
    )
    mappings = [{"column": "score", "type": "float", "filter": "range", "label": "Score", "storage_type": "text"}]

    dynamic_model.set_active_join_mapping(mappings, select_sql, resource_id="r1")

    model = dynamic_model.get_active_model()
    assert isinstance(model.__table__.c["score"].type, SaText)


def test_join_text_backed_numeric_range_filter_casts(monkeypatch, tmp_path):
    """End-to-end: main._query_column must CAST a join's text-backed numeric
    column, the same way it does for a single-table Aurora source, so a range
    filter compares numerically instead of lexicographically ("9" < "10")."""
    import dynamic_model
    import main
    from sqlalchemy.dialects import postgresql

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")
    select_sql = 'SELECT ROW_NUMBER() OVER () AS "_rowid", t0."score" AS "score" FROM "t" AS t0'
    mappings = [{"column": "score", "type": "float", "filter": "range", "label": "Score", "storage_type": "text"}]
    dynamic_model.set_active_join_mapping(mappings, select_sql, resource_id="r1")

    expression = main._query_column(dynamic_model.get_active_model(), "score")
    sql = str(expression.compile(dialect=postgresql.dialect()))

    assert "CAST(nullif(joined.score" in sql
    assert "AS FLOAT)" in sql
