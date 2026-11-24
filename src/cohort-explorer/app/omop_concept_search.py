"""Search OMOP concepts by name, for the search box in the cohort builder.

A concept is listed only if at least one person has it in the chosen domain's event table.
So every concept the user picks finds at least one person.
"""
from omop_criteria import (
    BAD_SHAPE_MESSAGE,
    OmopSpecError,
    check_domain_name,
    check_schema_name,
    quote_name,
)
from omop_database_checks import run_query_with_time_limit
from omop_domains import OMOP_DOMAINS

MAX_SEARCH_CHARS = 200
MAX_SEARCH_WORDS = 8
MAX_RESULTS = 50
MAX_RESULTS_FOR_BLANK_SEARCH = 10

# Searching a large vocabulary can take long. This is below the 30 seconds the frontend waits.
SEARCH_TIME_LIMIT_SECONDS = 15

SEARCH_TOO_LONG_MESSAGE = f"Search text is limited to {MAX_SEARCH_CHARS} characters."
SEARCH_TOO_SLOW_MESSAGE = (
    f"The search took longer than {SEARCH_TIME_LIMIT_SECONDS} seconds and was stopped. "
    "Try more specific words."
)


def search_concepts(connection, schema, domain, search_text):
    """Return the concepts whose name matches the search text.

    connection is an open psycopg connection. Every word of the search text must appear in
    the concept name, in any case. A blank search text returns the most common concepts.
    Each result is a dictionary with the keys concept_id, name, vocabulary and persons
    (how many different people have that concept). The most common concepts come first,
    then the names in alphabetical order. For a domain with a value column (measurement), each
    result also has value_min and value_max: the lowest and highest number in the data, or None.
    """
    check_schema_name(schema)
    check_domain_name(domain)
    words = _split_search_text(search_text)

    sql, parameters = _build_search_sql(schema, domain, words)
    rows = run_query_with_time_limit(
        connection, sql, parameters, SEARCH_TIME_LIMIT_SECONDS, SEARCH_TOO_SLOW_MESSAGE
    )
    domain_has_values = "value_column" in OMOP_DOMAINS[domain]
    results = []
    for row in rows:
        result = {"concept_id": row[0], "name": row[1], "vocabulary": row[2], "persons": row[3]}
        if domain_has_values:
            result["value_min"] = row[4]
            result["value_max"] = row[5]
        results.append(result)
    return results


def _split_search_text(search_text):
    """Return the first MAX_SEARCH_WORDS words of the search text. A blank text gives none."""
    if search_text is None:
        return []
    if not isinstance(search_text, str):
        raise OmopSpecError(BAD_SHAPE_MESSAGE)
    if len(search_text) > MAX_SEARCH_CHARS:
        raise OmopSpecError(SEARCH_TOO_LONG_MESSAGE)
    # Postgres cannot store a NUL character in text, and psycopg raises an error for it.
    search_text = search_text.replace("\x00", "")
    return search_text.split()[:MAX_SEARCH_WORDS]


def _build_search_sql(schema, domain, words):
    """Return (sql, parameters). The words are bound parameters, never part of the SQL text."""
    entry = OMOP_DOMAINS[domain]
    quoted_schema = quote_name(schema)
    event_table = quote_name(entry["table"])
    concept_column = quote_name(entry["concept_column"])

    name_tests = " AND ".join("c.concept_name ILIKE %s ESCAPE '\\'" for _ in words)
    where_line = f"WHERE {name_tests}\n" if words else ""
    limit = MAX_RESULTS if words else MAX_RESULTS_FOR_BLANK_SEARCH

    value_selects = ""
    if "value_column" in entry:
        value_column = quote_name(entry["value_column"])
        value_selects = (
            f", CAST(MIN(e.{value_column}) AS double precision) AS value_min"
            f", CAST(MAX(e.{value_column}) AS double precision) AS value_max"
        )

    sql = (
        "SELECT c.concept_id, c.concept_name, c.vocabulary_id, "
        f"COUNT(DISTINCT e.person_id) AS persons{value_selects}\n"
        f'FROM {quoted_schema}."concept" c\n'
        f"JOIN {quoted_schema}.{event_table} e ON e.{concept_column} = c.concept_id\n"
        f"{where_line}"
        "GROUP BY c.concept_id, c.concept_name, c.vocabulary_id\n"
        "ORDER BY persons DESC, c.concept_name\n"
        f"LIMIT {limit}"
    )
    parameters = [_build_like_pattern(word) for word in words]
    return sql, parameters


def _build_like_pattern(word):
    """Return a LIKE pattern that matches the word anywhere, and treats % and _ as plain text.

    In a LIKE pattern, % means "any text" and _ means "any one character". The backslash
    is the escape character, so each of the three is escaped with a backslash.
    """
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
