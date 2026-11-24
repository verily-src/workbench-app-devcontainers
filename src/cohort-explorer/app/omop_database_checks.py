"""Checks that need the database: are the OMOP tables there, and how many people match.

Both checks give a plain message (OmopSpecError) that is safe to show the user.
"""
import psycopg

from omop_criteria import OmopSpecError, check_domain_name, check_schema_name, has_value_range, parse_spec
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


def list_event_columns_needed_by_spec(spec):
    """Return (table, column) pairs that the rules read in the event tables, each pair once.

    Every rule reads person_id and the concept column. Only a "Has" rule reads the start date,
    for the first date summary column. A rule with a value range also reads the value column.
    """
    clean_spec = parse_spec(spec)
    pairs = []
    for rule in clean_spec["criteria"]:
        domain = OMOP_DOMAINS[rule["domain"]]
        columns = ["person_id", domain["concept_column"]]
        if not rule["exclude"]:
            columns.append(domain["date_column"])
        if has_value_range(rule):
            columns.append(domain["value_column"])
        for column in columns:
            pair = (domain["table"], column)
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def list_event_columns_needed_by_search(domain):
    """Return (table, column) pairs that a concept search reads in the domain's event table.

    A domain with a value column is also searched for its lowest and highest number.
    """
    check_domain_name(domain)
    entry = OMOP_DOMAINS[domain]
    pairs = [(entry["table"], "person_id"), (entry["table"], entry["concept_column"])]
    if "value_column" in entry:
        pairs.append((entry["table"], entry["value_column"]))
    return pairs


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


def check_columns_exist(connection, schema, table_columns):
    """Raise OmopSpecError, naming the first (table, column) pair that the schema lacks.

    The tables must exist already (check_tables_exist). A view counts as a table.
    """
    check_schema_name(schema)
    rows = connection.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND (table_name, column_name) IN "
        "(SELECT * FROM unnest(%s::text[], %s::text[]))",
        [schema, [table for table, _ in table_columns], [column for _, column in table_columns]],
    ).fetchall()

    found_pairs = {(row[0], row[1]) for row in rows}
    for table_name, column_name in table_columns:
        if (table_name, column_name) not in found_pairs:
            raise OmopSpecError(
                "This database does not look like OMOP data. "
                f"Column {column_name} was not found in table {table_name} of schema {schema}."
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
