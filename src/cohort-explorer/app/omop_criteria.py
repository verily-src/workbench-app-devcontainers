"""Checks and builds OMOP cohort rules for the cohort builder.

This file grows over several commits. The full contract is in omop-poc-spec.md.
"""
import re

from omop_domains import OMOP_DOMAINS

# fullmatch, not match: a pattern that ends with $ would also accept a name that ends
# with a new line.
SCHEMA_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")

# These two limits must equal the limits in the frontend rule panel. There is no shared
# constant between Python and TypeScript, so a comment in each file points at the other.
MAX_RULES = 12
MAX_CONCEPT_IDS = 500

SPEC_KEYS = {"schema", "criteria"}
RULE_KEYS = {"domain", "concept_ids", "exclude"}

SCHEMA_NAME_MESSAGE = (
    "The schema name may use only letters, digits and underscores, "
    "and must start with a letter or underscore."
)
BAD_SHAPE_MESSAGE = "The cohort spec is not in the expected shape."
NO_RULES_MESSAGE = "Add at least one rule."
TOO_MANY_RULES_MESSAGE = f"Use at most {MAX_RULES} rules."
NO_CONCEPTS_MESSAGE = "Pick at least one item for every rule."
TOO_MANY_CONCEPTS_MESSAGE = f"Too many items picked in one rule. Use at most {MAX_CONCEPT_IDS}."
CONCEPT_NOT_WHOLE_NUMBER_MESSAGE = "Concept IDs must be whole numbers."
EXCLUDE_NOT_BOOLEAN_MESSAGE = "The Has / Does not have choice must be true or false."


class OmopSpecError(ValueError):
    """A cohort spec is wrong. The message is plain text that is safe to show the user."""


def check_schema_name(schema):
    """Return the schema name if it is safe to put in SQL. Raise OmopSpecError if not."""
    if not isinstance(schema, str) or not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise OmopSpecError(SCHEMA_NAME_MESSAGE)
    return schema


def parse_spec(spec):
    """Check a cohort spec and return a clean copy. Raise OmopSpecError if it is wrong.

    The clean copy has the keys "schema" and "criteria". Every rule in "criteria" has the
    keys "domain", "concept_ids" and "exclude" (false when the caller left it out).
    """
    if not isinstance(spec, dict):
        raise OmopSpecError(BAD_SHAPE_MESSAGE)
    _check_no_unexpected_keys(spec, SPEC_KEYS)

    schema = check_schema_name(spec.get("schema"))

    rules = spec.get("criteria", [])
    if not isinstance(rules, list):
        raise OmopSpecError(BAD_SHAPE_MESSAGE)
    if len(rules) == 0:
        raise OmopSpecError(NO_RULES_MESSAGE)
    if len(rules) > MAX_RULES:
        raise OmopSpecError(TOO_MANY_RULES_MESSAGE)

    return {"schema": schema, "criteria": [_parse_one_rule(rule) for rule in rules]}


def _parse_one_rule(rule):
    """Check one rule and return a clean copy of it."""
    if not isinstance(rule, dict):
        raise OmopSpecError(BAD_SHAPE_MESSAGE)
    _check_no_unexpected_keys(rule, RULE_KEYS)

    domain = rule.get("domain")
    _check_domain_name(domain)

    concept_ids = rule.get("concept_ids")
    _check_concept_ids(concept_ids)

    exclude = rule.get("exclude", False)
    _check_exclude_flag(exclude)

    return {"domain": domain, "concept_ids": list(concept_ids), "exclude": exclude}


def _check_no_unexpected_keys(data, allowed_keys):
    """Raise OmopSpecError for the first key (in alphabetical order) that is not allowed."""
    for key in sorted(data, key=str):
        if key not in allowed_keys:
            raise OmopSpecError(f"Unexpected field: {key}.")


def _check_domain_name(domain):
    """Raise OmopSpecError unless the domain is one of the names in OMOP_DOMAINS."""
    if not isinstance(domain, str) or domain not in OMOP_DOMAINS:
        raise OmopSpecError(_build_unknown_domain_message())


def _build_unknown_domain_message():
    """Return the unknown-domain message, listing the domains that are allowed right now."""
    return "Choose a valid OMOP domain. Current valid choices: " + ", ".join(OMOP_DOMAINS) + "."


def _check_concept_ids(concept_ids):
    """Raise OmopSpecError unless concept_ids is a list of 1 to MAX_CONCEPT_IDS whole numbers."""
    if concept_ids is None or concept_ids == []:
        raise OmopSpecError(NO_CONCEPTS_MESSAGE)
    if not isinstance(concept_ids, list):
        raise OmopSpecError(BAD_SHAPE_MESSAGE)
    if len(concept_ids) > MAX_CONCEPT_IDS:
        raise OmopSpecError(TOO_MANY_CONCEPTS_MESSAGE)
    for concept_id in concept_ids:
        # type() is int, not isinstance: True and False are ints in Python, and must not pass.
        if type(concept_id) is not int:
            raise OmopSpecError(CONCEPT_NOT_WHOLE_NUMBER_MESSAGE)


def _check_exclude_flag(exclude):
    """Raise OmopSpecError unless exclude is exactly True or False."""
    if type(exclude) is not bool:
        raise OmopSpecError(EXCLUDE_NOT_BOOLEAN_MESSAGE)
