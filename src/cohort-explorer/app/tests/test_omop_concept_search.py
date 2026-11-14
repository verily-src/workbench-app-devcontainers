import pytest

from omop_concept_search import _build_like_pattern, search_concepts
from omop_criteria import OmopSpecError

UNKNOWN_DOMAIN_MESSAGE = "Choose a valid OMOP domain. Current valid choices: condition, drug."
SCHEMA_MESSAGE = (
    "The schema name may use only letters, digits and underscores, "
    "and must start with a letter or underscore."
)
TOO_LONG_MESSAGE = "Search text is limited to 200 characters."

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
    assert search_concepts(omop_connection, "omop", "drug", "'; DROP TABLE concept;--") == []
    rows = omop_connection.execute("SELECT count(*) FROM omop.concept").fetchall()
    assert rows == [(12,)]


def test_result_has_exactly_four_fields(omop_connection):
    results = search_concepts(omop_connection, "omop", "drug", "")
    assert all(set(r) == {"concept_id", "name", "vocabulary", "persons"} for r in results)


def test_unknown_domain_rejected(omop_connection):
    with pytest.raises(OmopSpecError) as error:
        search_concepts(omop_connection, "omop", "procedure", "x")
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
