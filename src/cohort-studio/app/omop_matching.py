import difflib
import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def required_columns() -> dict[str, frozenset[str]]:
    ddl = (Path(__file__).parent / "omop_ddl" / "OMOPCDM_postgresql_5.4_ddl.sql").read_text()
    tables = {}
    for name, body in re.findall(r"CREATE TABLE @cdmDatabaseSchema\.(\w+)\s*\((.*?)\);", ddl, re.I | re.S):
        columns = set()
        for column in body.split(","):
            match = re.match(r"\s*(\w+)\s+\w+.*\bNOT NULL\b", column, re.I | re.S)
            if match:
                columns.add(match.group(1).lower())
        tables[name.lower()] = frozenset(columns)
    return tables


def suggestions(tables: dict[str, list[str]], expected: set[str]) -> dict[str, list[str]]:
    """Suggest renamed tables with matching required OMOP columns, without selecting one."""
    signatures = required_columns()
    missing = expected - tables.keys()
    unused = tables.keys() - expected
    out = {}
    for name in sorted(missing):
        required = signatures.get(name, frozenset())
        if not required:
            continue
        ranked = []
        for physical in unused:
            if not required <= set(tables[physical]):
                continue
            left = re.sub(r"[^a-z0-9]", "", name.casefold())
            right = re.sub(r"[^a-z0-9]", "", physical.casefold())
            score = difflib.SequenceMatcher(None, left, right).ratio()
            if score >= 0.8:
                ranked.append((score, physical))
        if ranked:
            out[name] = [physical for _, physical in sorted(ranked, key=lambda item: (-item[0], item[1]))[:3]]
    return out


def resolve(tables: dict[str, list[str]], expected: set[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    matches = {name: name for name in expected if name in tables}
    candidates = suggestions(tables, expected)
    reverse: dict[str, list[str]] = {}
    for logical, names in candidates.items():
        for name in names:
            reverse.setdefault(name, []).append(logical)
    for logical, names in candidates.items():
        if len(names) == 1 and len(reverse[names[0]]) == 1:
            matches[logical] = names[0]
    return matches, {name: names for name, names in candidates.items() if name not in matches}
