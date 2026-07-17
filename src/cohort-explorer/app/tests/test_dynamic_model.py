"""Tests for the dynamic model built from user-confirmed schema mappings."""


def test_get_all_columns_returns_mapping_order(monkeypatch, tmp_path):
    """Column order in /api/samples and /api/export must match the mapping
    order the user saved in the schema review — not alphabetical, not
    dir()-based. Bug we hit: _find_column used dir(model) (alphabetical),
    matched dbgap_sample_id (NULL) before gtex_sample_id, producing empty
    workflow rows."""
    import dynamic_model
    from dynamic_model import set_active_mapping, get_all_columns

    # Isolate: don't clobber the dev's active_schema.json
    monkeypatch.setattr(dynamic_model, "_SCHEMA_FILE", tmp_path / "schema.json")

    mappings = [
        {"column": "z_last",   "type": "text", "filter": "none", "label": ""},
        {"column": "a_first",  "type": "text", "filter": "none", "label": ""},
        {"column": "m_middle", "type": "text", "filter": "none", "label": ""},
    ]
    set_active_mapping(mappings, needs_pk=True)

    assert get_all_columns() == ["z_last", "a_first", "m_middle"]
