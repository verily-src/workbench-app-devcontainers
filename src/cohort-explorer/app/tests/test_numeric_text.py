from types import SimpleNamespace


def test_text_backed_float_uses_cast_and_returns_number(monkeypatch, tmp_path):
    import dynamic_model
    import main
    from sqlalchemy.dialects import postgresql
    from dynamic_model import get_active_model, set_active_mapping

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")
    mappings = [{
        "column": "score",
        "type": "float",
        "filter": "range",
        "label": "Score",
        "storage_type": "text",
    }]
    set_active_mapping(mappings, table_name="samples", needs_pk=False)

    expression = main._query_column(get_active_model(), "score")
    sql = str(expression.compile(dialect=postgresql.dialect()))

    assert "CAST(nullif(samples.score" in sql
    assert "AS FLOAT)" in sql
    assert main._row_value(SimpleNamespace(score="1.5"), "score") == 1.5
    assert main._row_value(SimpleNamespace(score=""), "score") is None


def test_confirm_restores_missing_aurora_storage_type(monkeypatch):
    import main

    activated = {}
    monkeypatch.setattr(main, "get_active_resource_id", lambda: "database")
    monkeypatch.setattr(
        main,
        "get_aurora_storage_types",
        lambda resource_id, table: {"score": "text"},
    )
    monkeypatch.setattr(
        main,
        "set_active_mapping",
        lambda mappings, **kwargs: activated.update(mapping=mappings, **kwargs),
    )

    result = main.api_confirm_schema({
        "table_name": "samples",
        "mappings": [{
            "column": "score",
            "type": "float",
            "filter": "range",
            "label": "Score",
        }],
    })

    assert result == {"confirmed": True, "columns": 1, "seeded": 0}
    assert activated["mapping"][0]["storage_type"] == "text"


def test_samples_include_columns_without_filters(monkeypatch, tmp_path):
    import dynamic_model
    import main
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from starlette.requests import Request
    from dynamic_model import DynamicBase, get_active_model, set_active_mapping

    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")
    mappings = [
        {"column": "sample_id", "type": "text", "filter": "categorical", "label": "Sample"},
        {"column": "fastq1_path", "type": "text", "filter": "none", "label": "FASTQ 1"},
    ]
    set_active_mapping(mappings)
    engine = create_engine("sqlite://")
    DynamicBase.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(get_active_model()(sample_id="S1", fastq1_path="s3://reads/S1_R1.fastq.gz"))
        db.commit()
        request = Request({"type": "http", "query_string": b""})
        rows = main.get_samples(request, db)

    assert rows[0]["fastq1_path"] == "s3://reads/S1_R1.fastq.gz"
