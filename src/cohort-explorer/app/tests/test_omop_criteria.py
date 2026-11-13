import pytest

from omop_criteria import OmopSpecError, check_schema_name
from omop_domains import OMOP_DOMAINS

SCHEMA_MESSAGE = (
    "The schema name may use only letters, digits and underscores, "
    "and must start with a letter or underscore."
)


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
