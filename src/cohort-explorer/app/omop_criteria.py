"""Checks and builds OMOP cohort rules for the cohort builder.

This file grows over several commits. The full contract is in omop-poc-spec.md.
"""
import re

# fullmatch, not match: a pattern that ends with $ would also accept a name that ends
# with a new line.
SCHEMA_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")

SCHEMA_NAME_MESSAGE = (
    "The schema name may use only letters, digits and underscores, "
    "and must start with a letter or underscore."
)


class OmopSpecError(ValueError):
    """A cohort spec is wrong. The message is plain text that is safe to show the user."""


def check_schema_name(schema):
    """Return the schema name if it is safe to put in SQL. Raise OmopSpecError if not."""
    if not isinstance(schema, str) or not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise OmopSpecError(SCHEMA_NAME_MESSAGE)
    return schema
