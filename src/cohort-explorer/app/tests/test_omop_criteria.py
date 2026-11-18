import copy

import pytest

from omop_criteria import OmopSpecError, check_schema_name, parse_spec
from omop_domains import OMOP_DOMAINS

# The exact messages below are copied from section 4.6 of omop-poc-spec.md on purpose.
# They are not imported from omop_criteria.py, so a changed message fails a test.
SCHEMA_MESSAGE = (
    "The schema name may use only letters, digits and underscores, "
    "and must start with a letter or underscore."
)
UNKNOWN_DOMAIN_MESSAGE = "Choose a valid OMOP domain. Current valid choices: condition, drug."


def make_spec(**changes):
    """Return a correct spec. Keyword arguments replace top-level keys."""
    spec = {
        "schema": "omop",
        "criteria": [
            {"domain": "condition", "concept_ids": [201826], "exclude": False},
            {"domain": "drug", "concept_ids": [40000001, 40000002], "exclude": True},
        ],
    }
    spec.update(changes)
    return spec


def make_rule(**changes):
    """Return a correct rule. Keyword arguments replace its keys."""
    rule = {"domain": "condition", "concept_ids": [201826], "exclude": False}
    rule.update(changes)
    return rule


def assert_spec_rejected(spec, message):
    with pytest.raises(OmopSpecError) as error:
        parse_spec(spec)
    assert str(error.value) == message


# ---- schema names (AC3) ----


@pytest.mark.parametrize("name", ["omop", "_omop2", "a" * 63])
def test_safe_schema_names_accepted(name):
    assert check_schema_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "a" * 64,
        "1omop",
        'om"op',
        "om op",
        "om:op",
        "om;op",
        "om-op",
        "omop\n",
        None,
        5,
    ],
)
def test_unsafe_schema_names_rejected_with_message(name):
    with pytest.raises(OmopSpecError) as error:
        check_schema_name(name)
    assert str(error.value) == SCHEMA_MESSAGE


def test_every_domain_has_table_and_concept_column():
    for domain, entry in OMOP_DOMAINS.items():
        assert set(entry) == {"table", "concept_column"}, domain


# ---- a correct spec (AC1) ----


def test_correct_spec_accepted_unchanged():
    spec = make_spec()
    assert parse_spec(spec) == spec


def test_missing_exclude_flag_becomes_false():
    spec = make_spec(criteria=[{"domain": "drug", "concept_ids": [40000001]}])
    assert parse_spec(spec)["criteria"][0]["exclude"] is False


def test_twelve_rules_accepted():
    assert len(parse_spec(make_spec(criteria=[make_rule()] * 12))["criteria"]) == 12


def test_five_hundred_concept_ids_accepted():
    spec = make_spec(criteria=[make_rule(concept_ids=list(range(500)))])
    assert len(parse_spec(spec)["criteria"][0]["concept_ids"]) == 500


def test_parse_spec_does_not_modify_its_input():
    spec = make_spec(criteria=[{"domain": "drug", "concept_ids": [1]}])
    before = copy.deepcopy(spec)
    parse_spec(spec)
    assert spec == before


# ---- a wrong spec (AC2) ----


@pytest.mark.parametrize("spec", [None, [], "omop", 5])
def test_spec_that_is_not_an_object_rejected(spec):
    assert_spec_rejected(spec, "The cohort spec is not in the expected shape.")


def test_unknown_domain_rejected_with_list_of_choices():
    spec = make_spec(criteria=[make_rule(domain="procedure")])
    assert_spec_rejected(spec, UNKNOWN_DOMAIN_MESSAGE)


def test_missing_domain_rejected_with_list_of_choices():
    rule = make_rule()
    del rule["domain"]
    assert_spec_rejected(make_spec(criteria=[rule]), UNKNOWN_DOMAIN_MESSAGE)


def test_empty_rule_list_rejected():
    assert_spec_rejected(make_spec(criteria=[]), "Add at least one rule.")


def test_missing_rule_list_rejected():
    spec = make_spec()
    del spec["criteria"]
    assert_spec_rejected(spec, "Add at least one rule.")


def test_rule_list_that_is_not_a_list_rejected():
    assert_spec_rejected(
        make_spec(criteria="condition"), "The cohort spec is not in the expected shape."
    )


def test_rule_that_is_not_an_object_rejected():
    assert_spec_rejected(
        make_spec(criteria=["condition"]), "The cohort spec is not in the expected shape."
    )


def test_thirteen_rules_rejected():
    assert_spec_rejected(make_spec(criteria=[make_rule()] * 13), "Use at most 12 rules.")


def test_rule_without_concept_ids_rejected():
    assert_spec_rejected(
        make_spec(criteria=[make_rule(concept_ids=[])]),
        "Pick at least one item for every rule.",
    )


def test_rule_with_missing_concept_ids_rejected():
    rule = make_rule()
    del rule["concept_ids"]
    assert_spec_rejected(make_spec(criteria=[rule]), "Pick at least one item for every rule.")


def test_501_concept_ids_rejected():
    spec = make_spec(criteria=[make_rule(concept_ids=list(range(501)))])
    assert_spec_rejected(spec, "Too many items picked in one rule. Use at most 500.")


@pytest.mark.parametrize("bad_id", [True, False, "5", 1.5, 2.0, None])
def test_concept_ids_that_are_not_whole_numbers_rejected(bad_id):
    spec = make_spec(criteria=[make_rule(concept_ids=[201826, bad_id])])
    assert_spec_rejected(spec, "Concept IDs must be whole numbers.")


def test_concept_ids_at_database_limits_accepted():
    spec = make_spec(criteria=[make_rule(concept_ids=[-2147483648, 2147483647])])
    assert parse_spec(spec)["criteria"][0]["concept_ids"] == [-2147483648, 2147483647]


@pytest.mark.parametrize(
    "too_big_or_small",
    [
        pytest.param(2147483648, id="just-above-the-limit"),
        pytest.param(-2147483649, id="just-below-the-limit"),
        pytest.param(10**5000, id="number-with-5000-digits"),
    ],
)
def test_concept_ids_outside_database_range_rejected(too_big_or_small):
    spec = make_spec(criteria=[make_rule(concept_ids=[too_big_or_small])])
    assert_spec_rejected(spec, "Concept IDs must be between -2147483648 and 2147483647.")


@pytest.mark.parametrize("bad_flag", ["yes", 1, 0, None])
def test_exclude_flag_that_is_not_true_or_false_rejected(bad_flag):
    spec = make_spec(criteria=[make_rule(exclude=bad_flag)])
    assert_spec_rejected(spec, "The Has / Does not have choice must be true or false.")


def test_unexpected_key_in_spec_rejected():
    assert_spec_rejected(make_spec(limit=10), "Unexpected field: limit.")


def test_unexpected_key_in_rule_rejected():
    spec = make_spec(criteria=[make_rule(descendants=True)])
    assert_spec_rejected(spec, "Unexpected field: descendants.")


def test_bad_schema_name_in_spec_rejected():
    assert_spec_rejected(make_spec(schema='omop"; DROP TABLE person;--'), SCHEMA_MESSAGE)


def test_missing_schema_in_spec_rejected():
    spec = make_spec()
    del spec["schema"]
    assert_spec_rejected(spec, SCHEMA_MESSAGE)


def test_injection_text_as_concept_id_rejected():
    spec = make_spec(criteria=[make_rule(concept_ids=["1); DROP TABLE person;--"])])
    assert_spec_rejected(spec, "Concept IDs must be whole numbers.")


# ---- domains live in one place (AC42) ----


@pytest.fixture
def procedure_domain_added(monkeypatch):
    """Add a procedure domain to the one dictionary, and change no other code."""
    monkeypatch.setitem(
        OMOP_DOMAINS,
        "procedure",
        {"table": "procedure_occurrence", "concept_column": "procedure_concept_id"},
    )


def test_added_domain_passes_spec_check(procedure_domain_added):
    spec = make_spec(criteria=[make_rule(domain="procedure")])
    assert parse_spec(spec)["criteria"][0]["domain"] == "procedure"


def test_added_domain_listed_in_unknown_domain_message(procedure_domain_added):
    spec = make_spec(criteria=[make_rule(domain="visit")])
    assert_spec_rejected(
        spec, "Choose a valid OMOP domain. Current valid choices: condition, drug, procedure."
    )
