import pytest

import omop_concept_search
from omop_concept_search import _build_like_pattern, search_concepts
from omop_criteria import OmopSpecError

UNKNOWN_DOMAIN_MESSAGE = (
    "Choose a valid OMOP domain. "
    "Current valid choices: condition, drug, observation, procedure, measurement."
)
SCHEMA_MESSAGE = (
    "The schema name may use only letters, digits and underscores, "
    "and must start with a letter or underscore."
)
TOO_LONG_MESSAGE = "Search text is limited to 200 characters."
TOO_SLOW_MESSAGE = (
    "The search took longer than 15 seconds and was stopped. Try more specific words."
)

METFORMIN_500 = {
    "concept_id": 40000001,
    "name": "Metformin 500 MG Oral Tablet",
    "vocabulary": "RxNorm",
    "persons": 2,
}
METFORMIN_1000 = {
    "concept_id": 40000002,
    "name": "Metformin 1000 MG Oral Tablet",
    "vocabulary": "RxNorm",
    "persons": 1,
}


def found_ids(connection, domain, search_text):
    """Search schema "omop" and return only the concept IDs, in the order returned."""
    return [r["concept_id"] for r in search_concepts(connection, "omop", domain, search_text)]


# ---- turning a word into a pattern (no database needed) ----


def test_like_pattern_wraps_word_with_percent():
    assert _build_like_pattern("metformin") == "%metformin%"


def test_like_pattern_escapes_percent_underscore_and_backslash():
    assert _build_like_pattern("50%_\\") == "%50\\%\\_\\\\%"


# ---- search results (against the test database) ----


def test_search_lists_products_that_exist_most_common_first(omop_connection):
    results = search_concepts(omop_connection, "omop", "drug", "metformin")
    assert results == [METFORMIN_500, METFORMIN_1000]


def test_search_leaves_out_concepts_nobody_has(omop_connection):
    # Concept 1503297 "Metformin" (the ingredient) exists, but no drug row uses it.
    assert 1503297 not in found_ids(omop_connection, "drug", "metformin")


def test_search_ignores_case(omop_connection):
    assert found_ids(omop_connection, "drug", "METFORMIN") == [40000001, 40000002]


def test_search_needs_every_word(omop_connection):
    assert found_ids(omop_connection, "drug", "METFORMIN 500") == [40000001]


def test_search_stays_inside_the_chosen_domain(omop_connection):
    condition_results = search_concepts(omop_connection, "omop", "condition", "diabetes")
    assert condition_results == [
        {
            "concept_id": 201826,
            "name": "Type 2 diabetes mellitus",
            "vocabulary": "SNOMED",
            "persons": 3,
        }
    ]
    assert search_concepts(omop_connection, "omop", "drug", "diabetes") == []


@pytest.mark.parametrize("blank_text", ["", "   ", None])
def test_blank_search_lists_most_common_drugs(omop_connection, blank_text):
    # Persons 2, 1, 1. The last two tie, so the names decide: Lisinopril before Metformin.
    assert found_ids(omop_connection, "drug", blank_text) == [40000001, 40000003, 40000002]


def test_blank_search_lists_most_common_conditions(omop_connection):
    assert found_ids(omop_connection, "condition", "") == [201826, 320128]


def test_search_text_over_200_characters_rejected(omop_connection):
    with pytest.raises(OmopSpecError) as error:
        search_concepts(omop_connection, "omop", "drug", "a" * 201)
    assert str(error.value) == TOO_LONG_MESSAGE


def test_search_text_of_200_characters_accepted(omop_connection):
    assert search_concepts(omop_connection, "omop", "drug", "a" * 200) == []


def test_search_uses_only_the_first_eight_words(omop_connection):
    # The ninth word cannot match anything. It is ignored, so the result is still found.
    text = "metformin 500 mg oral tablet o o o zzzz"
    assert found_ids(omop_connection, "drug", text) == [40000001]


@pytest.mark.parametrize("symbol", ["%", "_", "\\"])
def test_percent_underscore_and_backslash_match_only_themselves(omop_connection, symbol):
    assert search_concepts(omop_connection, "omop", "drug", symbol) == []


def test_search_text_with_nul_character_ignores_it(omop_connection):
    assert found_ids(omop_connection, "drug", "metformin\x00") == [40000001, 40000002]


def test_sql_in_search_text_changes_nothing(omop_connection):
    concept_count_before = omop_connection.execute("SELECT count(*) FROM omop.concept").fetchall()
    assert search_concepts(omop_connection, "omop", "drug", "'; DROP TABLE concept;--") == []
    concept_count_after = omop_connection.execute("SELECT count(*) FROM omop.concept").fetchall()
    assert concept_count_after == concept_count_before


def test_result_has_exactly_four_fields(omop_connection):
    results = search_concepts(omop_connection, "omop", "drug", "")
    assert all(set(r) == {"concept_id", "name", "vocabulary", "persons"} for r in results)


def test_unknown_domain_rejected(omop_connection):
    with pytest.raises(OmopSpecError) as error:
        search_concepts(omop_connection, "omop", "visit", "x")
    assert str(error.value) == UNKNOWN_DOMAIN_MESSAGE


def test_unsafe_schema_name_rejected(omop_connection):
    with pytest.raises(OmopSpecError) as error:
        search_concepts(omop_connection, 'omop"; DROP TABLE person;--', "drug", "x")
    assert str(error.value) == SCHEMA_MESSAGE


# ---- how many results come back (a scratch schema with 60 drugs) ----


@pytest.fixture
def sixty_drugs(omop_connection):
    """Create a scratch schema named omop_many with 60 drugs. The connection fixture undoes it."""
    for statement in [
        "CREATE SCHEMA omop_many",
        "CREATE TABLE omop_many.concept (concept_id integer, concept_name text, "
        "domain_id text, vocabulary_id text)",
        "CREATE TABLE omop_many.drug_exposure (person_id integer, drug_concept_id integer)",
        "INSERT INTO omop_many.concept SELECT n, 'Item ' || n, 'Drug', 'RxNorm' "
        "FROM generate_series(1, 60) n",
        "INSERT INTO omop_many.drug_exposure SELECT n, n FROM generate_series(1, 60) n",
    ]:
        omop_connection.execute(statement)


def test_search_returns_at_most_50_results(omop_connection, sixty_drugs):
    assert len(search_concepts(omop_connection, "omop_many", "drug", "item")) == 50


def test_blank_search_returns_at_most_10_results(omop_connection, sixty_drugs):
    assert len(search_concepts(omop_connection, "omop_many", "drug", "")) == 10


# ---- the time limit (AC44) ----


@pytest.fixture
def search_that_takes_two_seconds(monkeypatch):
    """Make every search run a slow query, and shorten the limit so the test stays fast."""
    monkeypatch.setattr(
        omop_concept_search, "_build_search_sql", lambda *arguments: ("SELECT 1 FROM pg_sleep(2)", [])
    )
    monkeypatch.setattr(omop_concept_search, "SEARCH_TIME_LIMIT_SECONDS", 0.2)


def test_search_time_limit_is_15_seconds():
    assert omop_concept_search.SEARCH_TIME_LIMIT_SECONDS == 15


def test_slow_search_rejected_with_reason(omop_connection, search_that_takes_two_seconds):
    with pytest.raises(OmopSpecError) as error:
        search_concepts(omop_connection, "omop", "drug", "metformin")
    assert str(error.value) == TOO_SLOW_MESSAGE


def test_connection_usable_after_slow_search(omop_connection, search_that_takes_two_seconds):
    with pytest.raises(OmopSpecError):
        search_concepts(omop_connection, "omop", "drug", "metformin")
    assert omop_connection.execute("SELECT 1").fetchall() == [(1,)]


# ---- the observation, procedure and measurement domains (AC55) ----


def test_search_lists_the_concepts_of_each_new_domain(omop_connection):
    assert found_ids(omop_connection, "observation", "smoker") == [4100001, 4100002]
    assert found_ids(omop_connection, "procedure", "scopy") == [4000001]
    assert found_ids(omop_connection, "measurement", "hemoglobin") == [4200001]


def test_new_domain_search_stays_inside_its_domain(omop_connection):
    assert found_ids(omop_connection, "measurement", "colonoscopy") == []
    assert found_ids(omop_connection, "procedure", "hemoglobin") == []


def test_blank_search_lists_most_common_measurements(omop_connection):
    # Both items have 2 persons (hemoglobin A1c: 1 and 3, body mass index: 2 and 4). The names decide.
    assert found_ids(omop_connection, "measurement", "") == [4200002, 4200001]


# ---- the lowest and highest number of a measurement (AC57) ----


def search_result(connection, domain, search_text, concept_id):
    results = search_concepts(connection, "omop", domain, search_text)
    return next(result for result in results if result["concept_id"] == concept_id)


def test_measurement_result_shows_the_lowest_and_highest_number_in_the_data(omop_connection):
    result = search_result(omop_connection, "measurement", "hemoglobin", 4200001)
    assert (result["value_min"], result["value_max"]) == (5.2, 7.4)


def test_numbers_are_floats(omop_connection):
    result = search_result(omop_connection, "measurement", "hemoglobin", 4200001)
    assert type(result["value_min"]) is float and type(result["value_max"]) is float


def test_row_with_no_number_is_ignored_in_the_lowest_and_highest(omop_connection):
    # Body mass index: person 2 has 27.5, person 4 has a row with no number.
    result = search_result(omop_connection, "measurement", "body mass", 4200002)
    assert (result["value_min"], result["value_max"]) == (27.5, 27.5)


def test_measurement_with_only_empty_numbers_has_no_lowest_or_highest(omop_connection):
    omop_connection.execute("INSERT INTO omop.concept VALUES (4200003, 'Throat culture', 'Measurement', 'LOINC')")
    omop_connection.execute("INSERT INTO omop.measurement VALUES (1, 4200003, '2020-01-01', NULL)")
    result = search_result(omop_connection, "measurement", "throat", 4200003)
    assert (result["value_min"], result["value_max"]) == (None, None)


def test_measurement_result_has_exactly_six_fields(omop_connection):
    results = search_concepts(omop_connection, "omop", "measurement", "")
    expected = {"concept_id", "name", "vocabulary", "persons", "value_min", "value_max"}
    assert all(set(result) == expected for result in results)


def test_drug_result_still_has_exactly_four_fields(omop_connection):
    results = search_concepts(omop_connection, "omop", "drug", "")
    assert all(set(result) == {"concept_id", "name", "vocabulary", "persons"} for result in results)

