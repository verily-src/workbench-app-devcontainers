"""Checks that need the database: are the OMOP tables there, and how many people match.

Both checks give a plain message (OmopSpecError) that is safe to show the user.
"""
import psycopg

from omop_criteria import OmopSpecError, check_schema_name, parse_spec
from omop_domains import OMOP_DOMAINS

COUNT_TIME_LIMIT_SECONDS = 15

# The message says "took longer", not "too large": a cold database can be slow for a small
# cohort too.
COUNT_TOO_SLOW_MESSAGE = (
    f"The count took longer than {COUNT_TIME_LIMIT_SECONDS} seconds and was stopped. "
    "Try again, or add more rules."
)


def list_tables_needed_by_spec(spec):
    """Return the tables a cohort spec reads: person, concept, then each rule's event table.

    The rules' event tables are in rule order, and each one is listed once.
    """
    clean_spec = parse_spec(spec)
    tables = ["person", "concept"]
    for rule in clean_spec["criteria"]:
        event_table = OMOP_DOMAINS[rule["domain"]]["table"]
        if event_table not in tables:
            tables.append(event_table)
    return tables


def check_tables_exist(connection, schema, table_names):
    """Raise OmopSpecError, naming the first table in table_names that the schema lacks.

    A view counts as a table. The schema name and the table names are bound parameters here.
    """
    check_schema_name(schema)
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_name = ANY(%s)",
        [schema, table_names],
    ).fetchall()

    found_names = {row[0] for row in rows}
    for table_name in table_names:
        if table_name not in found_names:
            raise OmopSpecError(
                "This database does not look like OMOP data. "
                f"Table {table_name} was not found in schema {schema}."
            )


def count_people_with_time_limit(
    connection, person_list_sql, seconds=COUNT_TIME_LIMIT_SECONDS
):
    """Return how many rows the person list SQL gives. Stop and raise if it takes too long."""
    rows = run_query_with_time_limit(
        connection,
        f"SELECT count(*) FROM ({person_list_sql}) AS people",
        None,
        seconds,
        COUNT_TOO_SLOW_MESSAGE,
    )
    return rows[0][0]


def run_query_with_time_limit(connection, sql, parameters, seconds, too_slow_message):
    """Run a SELECT and return all its rows. If it takes longer than the time limit,
    the database stops it and this raises OmopSpecError with too_slow_message.

    This ends the current transaction when it finishes, so the time limit does not stay on
    for the caller's next statement, and the connection can be used again after a time-out.
    """
    try:
        # set_config(..., true) is the same as SET LOCAL, but it accepts a bound parameter.
        connection.execute(
            "SELECT set_config('statement_timeout', %s, true)", [str(int(seconds * 1000))]
        )
        return connection.execute(sql, parameters).fetchall()
    except psycopg.errors.QueryCanceled as error:
        raise OmopSpecError(too_slow_message) from error
    finally:
        connection.rollback()
