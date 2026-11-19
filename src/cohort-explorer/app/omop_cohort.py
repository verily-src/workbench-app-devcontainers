"""Make an OMOP cohort the active cohort of the Cohort Explorer.

The grid, the filters and the charts all read from the active model, so activating a cohort
switches all three to it.
"""
import logging
import subprocess

import psycopg

from db import set_active_resource
from dynamic_model import set_active_join_mapping
from omop_concept_search import search_concepts
from omop_criteria import (
    OmopSpecError,
    build_person_list_sql,
    check_domain_name,
    check_schema_name,
    get_summary_column_names,
    parse_spec,
)
from omop_database_checks import (
    check_tables_exist,
    count_people_with_time_limit,
    list_tables_needed_by_spec,
)
from omop_domains import OMOP_DOMAINS
from schema import _connect_aurora

logger = logging.getLogger(__name__)

NO_DATABASE_MESSAGE = "Choose a database first."
CANNOT_CONNECT_MESSAGE = "Could not connect to the database. Check the database choice and try again."

# The first columns the person list SQL returns, in this order (omop-poc-spec.md section 4.5).
# The row ID column _rowid is not listed: the model adds it itself.
OMOP_COLUMN_MAPPINGS = [
    {"column": "person_id", "type": "integer", "filter": "none", "label": "Person"},
    {"column": "gender", "type": "text", "filter": "categorical", "label": "Gender"},
    {"column": "race", "type": "text", "filter": "categorical", "label": "Race"},
    {"column": "ethnicity", "type": "text", "filter": "categorical", "label": "Ethnicity"},
    {"column": "year_of_birth", "type": "integer", "filter": "range", "label": "Year of birth"},
]


def build_column_mappings(clean_spec):
    """Return the base columns, then two summary columns for each "Has" rule."""
    mappings = [dict(mapping) for mapping in OMOP_COLUMN_MAPPINGS]
    for rule_number, rule in enumerate(clean_spec["criteria"], start=1):
        if rule["exclude"]:
            continue
        items, first_date = get_summary_column_names(rule_number)
        label = f"{rule['domain'].capitalize()} (rule {rule_number})"
        mappings.append({"column": items, "type": "text", "filter": "none", "label": f"{label}: items"})
        mappings.append({"column": first_date, "type": "text", "filter": "none", "label": f"{label}: first date"})
    return mappings


def activate_omop_cohort(resource_id, spec):
    """Check the request, then make the cohort the active one. Return how many people match.

    Raise OmopSpecError, with a plain message, if anything is wrong. Nothing in the app
    changes unless every check passes, so a failed request leaves the previous cohort active.
    """
    if not isinstance(resource_id, str) or resource_id.strip() == "":
        raise OmopSpecError(NO_DATABASE_MESSAGE)
    clean_spec = parse_spec(spec)
    person_list_sql = build_person_list_sql(clean_spec)

    people_count = _check_database_and_count_people(resource_id, clean_spec, person_list_sql)

    set_active_resource(resource_id)
    set_active_join_mapping(
        build_column_mappings(clean_spec),
        person_list_sql,
        resource_id,
        table_name=f"omop:{clean_spec['schema']}",
        entity_column="person_id",
    )
    return people_count


def find_omop_concepts(resource_id, schema, domain, search_text):
    """Check the request, then return the concepts that match the search text.

    Raise OmopSpecError, with a plain message, if anything is wrong. The search only reads data.
    """
    if not isinstance(resource_id, str) or resource_id.strip() == "":
        raise OmopSpecError(NO_DATABASE_MESSAGE)
    check_schema_name(schema)
    check_domain_name(domain)

    connection = _open_connection_or_raise_plain_message(resource_id)
    with connection:
        tables_needed = ["concept", OMOP_DOMAINS[domain]["table"]]
        check_tables_exist(connection, schema, tables_needed)
        return search_concepts(connection, schema, domain, search_text)


def _check_database_and_count_people(resource_id, clean_spec, person_list_sql):
    """Open a short connection, check the OMOP tables exist, and count the matching people."""
    connection = _open_connection_or_raise_plain_message(resource_id)
    with connection:
        check_tables_exist(
            connection, clean_spec["schema"], list_tables_needed_by_spec(clean_spec)
        )
        return count_people_with_time_limit(connection, person_list_sql)


def _open_connection_or_raise_plain_message(resource_id):
    """Open a database connection. The technical error goes to the log, not to the user."""
    try:
        return _connect_aurora(resource_id)
    except (subprocess.CalledProcessError, psycopg.OperationalError) as error:
        logger.warning("Could not connect to %s: %s", resource_id, error)
        raise OmopSpecError(CANNOT_CONNECT_MESSAGE) from error
