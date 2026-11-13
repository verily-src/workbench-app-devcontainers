import pytest

import cohort_save

LIVE = {
    "resource_id": "r",
    "sql": 'SELECT * FROM "public"."observation"',
    "columns": {"person_id": "person_id", "observation_date": "observation_date",
                "observation_source_value": "observation_source_value"},
}


@pytest.mark.parametrize("schema", ["public", "PUBLIC", "information_schema", "pg_catalog", "pg_temp_3"])
def test_protected_schemas_are_refused(schema):
    with pytest.raises(cohort_save.CohortSaveError, match="read-only|separate results schema"):
        cohort_save.validate_target(schema, "cohort")


@pytest.mark.parametrize("schema,table", [("res ult", "cohort"), ('re"sult', "cohort"), ("result", "co;hort"),
                                          ("1result", "cohort"), ("result", ""), ("a" * 64, "cohort")])
def test_bad_identifiers_are_refused(schema, table):
    with pytest.raises(cohort_save.CohortSaveError):
        cohort_save.validate_target(schema, table)


def test_result_schema_is_accepted():
    assert cohort_save.validate_target("result", "cohort") == ("result", "cohort")


def test_insert_selects_one_row_per_person_with_the_filters():
    filters = [{"column": "observation_source_value", "kind": "categorical",
                "values": ["rdGWAS_mpn_narrow", "beighton_hypermobility_qtl"]}]
    sql, params = cohort_save.build_insert(LIVE, filters, "person_id", "result", "cohort")
    assert sql.startswith('INSERT INTO "result"."cohort" (cohort_definition_id, subject_id, '
                          'cohort_start_date, cohort_end_date, cohort_name)')
    assert 'GROUP BY live."person_id"' in sql
    assert 'live."person_id" IS NOT NULL' in sql
    assert "observation_source_value" in sql
    assert "rdGWAS_mpn_narrow" not in sql          # values are bound, never inlined
    assert "rdGWAS_mpn_narrow" in str(params.values())
    assert "CAST(NULL AS date)" in sql


def test_insert_without_filters_still_has_a_where():
    sql, _ = cohort_save.build_insert(LIVE, [], "person_id", "result", "cohort")
    assert "WHERE (TRUE)" in sql or "WHERE (true)" in sql.lower()


def test_dates_come_from_the_chosen_column():
    sql, _ = cohort_save.build_insert(LIVE, [], "person_id", "result", "cohort", "observation_date")
    assert 'MIN(CAST(live."observation_date" AS date))' in sql
    assert 'MAX(CAST(live."observation_date" AS date))' in sql


def test_unknown_columns_are_refused():
    with pytest.raises(cohort_save.CohortSaveError):
        cohort_save.build_insert(LIVE, [], "nope", "result", "cohort")
    with pytest.raises(cohort_save.CohortSaveError):
        cohort_save.build_insert(LIVE, [], "person_id", "result", "cohort", "nope")


def test_injection_in_a_filter_value_is_bound_not_inlined():
    evil = "x'); DROP TABLE result.cohort;--"
    sql, params = cohort_save.build_insert(
        LIVE, [{"column": "observation_source_value", "kind": "categorical", "values": [evil]}],
        "person_id", "result", "cohort")
    assert "DROP TABLE" not in sql
    assert evil in str(params.values())


def test_target_listing_query_protects_schemas_and_avoids_percent_signs():
    # The listing must exclude the protected schemas by parameter and must not contain a literal %,
    # which the SQL driver would treat as a placeholder.
    assert ":blocked" in cohort_save._TARGETS_SQL
    assert "%" not in cohort_save._TARGETS_SQL
    assert cohort_save.BLOCKED_SCHEMAS >= {"public", "information_schema"}
    assert len(cohort_save.COHORT_COLUMNS) == 5
