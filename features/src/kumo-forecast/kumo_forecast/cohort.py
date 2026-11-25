"""The cohort designer's locked cohorts, read from its session files. Standard library only.

A cohort is a set of entities: the lock's key column says which (``person_id`` in a patient
cohort, a visit id in a cohort of visits), and the dataset's tables that have that column are what
a forecast reads.

The designer saves each session as ``<state>/sessions/<id>.json`` (its ``file_safety``), beside a
``.journal.jsonl`` and a ``.messages.json``. A lock in ``locks`` freezes the export statement
(``statement.sql``) and its columns (``export.columns``), each with what it holds (``meaning``)
and, for a key, the grain it keys and the data column it is read from. Reading the file rather
than asking the designer keeps the designer unchanged and keeps the statement, often several
kilobytes, out of the driving model's context.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

_SESSION_ID = re.compile(r"^[0-9]{8}-[0-9]{6}(?:-[0-9]+)?$")
_TABLE = re.compile(r"^`?([a-z][a-z0-9-]{4,28}[a-z0-9])`?\.`?([A-Za-z_][A-Za-z0-9_]*)`?\.`?([A-Za-z_][A-Za-z0-9_]*)`?$")


class CohortError(ValueError):
    """A session or lock this server cannot use, with what to do about it."""


@dataclass(frozen=True)
class LockedCohort:
    session_id: str
    version: int
    locked_at: str
    sql: str
    key_column: str             # the export column holding the entity's key (a person, a stay, ...)
    key_data_column: str | None  # the data column the key is read from, such as person_id; None
                                 # until resolve_key reads it from the schema, where the lock names none
    key_grain: str | None       # the grain whose key it is, as the designer named it (a patient, a stay)
    index_column: str | None    # the export column holding each member's time-zero date
    dataset: str                # project.dataset the statement reads the key's table from, or every
                                # dataset it reads joined by commas (tables.datasets_of)
    tables: tuple[str, ...]     # every table the statement reads, project.dataset.table
    question: str | None        # the first request the designer was given, as relayed
    billing_project: str | None  # the project the designer ran BigQuery jobs in


def session_files(sessions_dir: Path) -> list[Path]:
    """The session state files, newest first. Journals and message logs are skipped."""
    files = [p for p in Path(sessions_dir).glob("*.json") if _SESSION_ID.match(p.stem)]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def load_session(sessions_dir: Path, session_id: str = "latest") -> dict:
    """The saved state of a session: the newest one that holds a lock for ``latest``."""
    sessions_dir = Path(sessions_dir)
    if session_id != "latest":
        if not _SESSION_ID.match(session_id):
            raise CohortError(f"{session_id!r} is not a cohort designer session id (like 20261111-224856)")
        path = sessions_dir / f"{session_id}.json"
        if not path.is_file():
            raise CohortError(f"no cohort designer session {session_id} in {sessions_dir}")
        return _read(path)
    for path in session_files(sessions_dir):
        data = _read(path)
        if data.get("locks"):
            return data
    raise CohortError("no locked cohort yet: lock one in the cohort designer first")


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        raise CohortError(f"cannot read the session file {path.name}: {err}") from err
    if not isinstance(data, dict) or "session_id" not in data:
        raise CohortError(f"{path.name} is not a cohort designer session file")
    return data


def locked_cohort(data: dict, version: int | None = None) -> LockedCohort:
    """The newest lock of a session (or lock ``version``) as a cohort of people."""
    locks = data.get("locks") or []
    if not locks:
        raise CohortError(f"session {data.get('session_id')} has no locked cohort yet")
    if version is None:
        lock = locks[-1]
    else:
        found = [lk for lk in locks if lk.get("version") == version]
        if not found:
            raise CohortError(f"session {data['session_id']} has no lock version {version}; "
                              f"it has {', '.join(str(lk.get('version')) for lk in locks)}")
        lock = found[0]
    columns = lock["export"]["columns"]
    key = next((c for c in columns if c.get("meaning") == "person_key"), None) \
        or next((c for c in columns if c.get("meaning") == "key" and c.get("column")), None)
    if key is None:
        raise CohortError("this cohort has no key column naming its members (its columns are "
                          f"{', '.join(c['name'] for c in columns) or 'none'}); lock a cohort with one row per entity")
    key_data_column = key.get("column") or None
    index = next((c["name"] for c in columns if c.get("meaning") == "time_zero_date"), None)
    tables = []
    for t in lock.get("evidence", {}).get("tables", []):
        # TableEvidence: {"table": {"name": "project.dataset.table", "read": ...}, "columns": ...}
        name = None
        if isinstance(t, dict):
            inner = t.get("table")
            name = inner.get("name") if isinstance(inner, dict) else t.get("name")
        if name and _TABLE.match(name):
            tables.append(name)
    # The dataset of the key's own table (person for person_id), else the one dataset read.
    own = (key_data_column[:-3] if key_data_column.endswith("_id") else key_data_column) if key_data_column else None
    datasets = {".".join(_TABLE.match(n).groups()[:2]) for n in tables
                if own and _TABLE.match(n).group(3).lower() == own.lower()}
    if not datasets:
        # No table named for the key (OMOP's person for person_id): every dataset the statement
        # reads, as a study that keeps its forms in several datasets does.
        datasets = {".".join(_TABLE.match(n).groups()[:2]) for n in tables}
    if not datasets:
        raise CohortError("cannot tell which dataset the cohort is drawn from (it reads no named table)")
    billing = next((src.split(":", 1)[1] for src in (lock.get("executor") or {}).get("source", [])
                    if isinstance(src, str) and src.startswith("billing:")), None)
    question = next((m.get("text") for m in data.get("messages") or []
                     if isinstance(m, dict) and m.get("text")), None)
    return LockedCohort(session_id=data["session_id"], version=int(lock["version"]),
                        locked_at=lock["locked_at"], sql=lock["statement"]["sql"],
                        key_column=key["name"], key_data_column=key_data_column, key_grain=key.get("grain"),
                        index_column=index, dataset=",".join(sorted(datasets)),
                        tables=tuple(tables), question=question,
                        billing_project=billing)


def resolve_key(lc: LockedCohort, schemas: dict[str, dict]) -> LockedCohort:
    """``lc`` with its key's data column, where the lock names none (only the person's key may
    print without one, ``locked_cohort``): the first of the grain's id
    (``patient_id`` for a patient), the grain's own name, and ``person_id`` (OMOP's, whatever the
    grain is called) that a table the lock read holds (a vocabulary it joins holds none). ``schemas`` is
    ``tables.read_schemas`` of the lock's dataset."""
    if lc.key_data_column:
        return lc
    read = [m.group(3) for m in map(_TABLE.match, lc.tables)
            if ".".join(m.groups()[:2]) == lc.dataset and m.group(3) in schemas] or list(schemas)
    held = [{c for c, _ in schemas[t]["columns"]} for t in read]
    grain = (lc.key_grain or "").strip()
    candidates = [c for c in (f"{grain}_id" if grain else "", grain, "person_id") if c]
    found = next((c for c in candidates if any(c in cols for cols in held)), None)
    if found is None:
        raise CohortError(f"the lock does not say which data column its key {lc.key_column} is read from, "
                          f"and no column named {', '.join(candidates)} is in a table it reads "
                          f"({', '.join(read) or 'none'}); lock a cohort whose key is a stored column")
    return replace(lc, key_data_column=found)
