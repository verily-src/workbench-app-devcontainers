"""The workspace's BigQuery datasets from inside the sandbox, described in one call each.

    import wbdata
    print(wbdata.survey())                         # every dataset: its tables, rows, date columns
    print(wbdata.describe("project.dataset"))      # one dataset: every table with its columns
    print(wbdata.find_columns(r"date|_dt$"))       # columns whose name matches, in every dataset
    rows = wbdata.query("SELECT ... LIMIT 10")     # a list of dicts

Or from the shell: `python -m wbdata survey`, `python -m wbdata describe project.dataset`,
`python -m wbdata find 'date|time'`.

Why: an agent learning what a dataset holds otherwise lists its tables and then reads them one
by one, a model step and a query each (20 steps for one "what data is here?"). These read two
metadata tables per dataset (`__TABLES__` for rows and `INFORMATION_SCHEMA.COLUMNS` for columns),
for all datasets at once. The datasets are the ones /sandbox/data-access.md lists, the same
credential and rules as any other query.
"""
import re
import sys
from concurrent.futures import ThreadPoolExecutor

NOTES = "/sandbox/data-access.md"
DATE_TYPES = ("DATE", "DATETIME", "TIMESTAMP")
# The most columns shown per table by describe(), and tables per dataset by survey().
MAX_COLUMNS = 60
MAX_TABLES = 200
_client = None


def _bigquery():
    global _client
    if _client is None:
        from google.cloud import bigquery
        _client = bigquery.Client(project=_project())
    return _client


def _notes():
    try:
        with open(NOTES, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _project():
    """The project queries run in, from the notes ("Queries run as jobs in project `x`")."""
    found = re.search(r"jobs in project `([^`]+)`", _notes())
    return found.group(1) if found else None


def datasets():
    """The BigQuery datasets the notes list, as "project.dataset"."""
    return re.findall(r"^- `([A-Za-z0-9_.:-]+\.[A-Za-z0-9_]+)`", _notes(), flags=re.M)


def _ref(dataset, table):
    """`project.dataset.table`, quoted, for a dataset named as the notes name it."""
    project, _, name = dataset.replace(":", ".").rpartition(".")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", project) or not re.fullmatch(r"\w+", name):
        raise ValueError(f"not a project.dataset name: {dataset!r}")
    return f"`{project}.{name}.{table}`"


def query(sql, **job):
    """The rows of a query, as a list of dicts."""
    return [dict(row.items()) for row in _bigquery().query(sql, **job).result()]


def _tables(dataset):
    """{table: {"rows": n, "columns": [(name, type), ...]}} from two metadata queries."""
    rows = {r["table_id"]: r["row_count"] for r in query(
        f"SELECT table_id, row_count FROM {_ref(dataset, '__TABLES__')}")}
    columns = {}
    for r in query(f"SELECT table_name, column_name, data_type FROM {_ref(dataset, 'INFORMATION_SCHEMA.COLUMNS')} "
                   "ORDER BY table_name, ordinal_position"):
        columns.setdefault(r["table_name"], []).append((r["column_name"], r["data_type"]))
    return {t: {"rows": rows.get(t), "columns": columns.get(t, [])} for t in sorted(set(rows) | set(columns))}


def _short(err):
    """One line for a dataset that could not be read."""
    text = str(err)
    if "403" in text or "Access Denied" in text:
        return ("Google refused it (403). Tell the user which dataset; do not look for other data in "
                "its place (the user's Workbench proxy group may not have been granted it).")
    return text.splitlines()[0][:300] if text else type(err).__name__


def _each(names):
    """{dataset: tables or the error}, the datasets read in parallel."""
    def read(name):
        try:
            return name, _tables(name)
        except Exception as err:  # noqa: BLE001 - one unreadable dataset must not hide the rest
            return name, RuntimeError(_short(err))
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(pool.map(read, names))


def _rows(n):
    return "rows unknown (a view)" if n is None else f"{n:,} rows"


def survey(names=None):
    """Every dataset (or those named): its tables with rows, column count and date columns."""
    names = names or datasets()
    if not names:
        return f"No BigQuery datasets are listed in {NOTES}."
    out = []
    for name, tables in _each(names).items():
        if isinstance(tables, Exception):
            out.append(f"{name}: could not be read: {tables}")
            continue
        out.append(f"{name}: {len(tables)} tables")
        for table, info in list(tables.items())[:MAX_TABLES]:
            dates = [c for c, t in info["columns"] if t.split("<")[0] in DATE_TYPES]
            line = f"  {table}: {_rows(info['rows'])}, {len(info['columns'])} columns"
            out.append(line + (f"; dates: {', '.join(dates)}" if dates else "; no date columns"))
        if len(tables) > MAX_TABLES:
            out.append(f"  ... and {len(tables) - MAX_TABLES} more tables")
    return "\n".join(out)


def describe(dataset, tables=None):
    """One dataset: each table (or those named) with its rows and its columns and types."""
    found = _each([dataset])[dataset]
    if isinstance(found, Exception):
        return f"{dataset}: could not be read: {found}"
    out = [f"{dataset}: {len(found)} tables"]
    for table, info in found.items():
        if tables and table not in tables:
            continue
        cols = ", ".join(f"{c} {t}" for c, t in info["columns"][:MAX_COLUMNS])
        more = len(info["columns"]) - MAX_COLUMNS
        out.append(f"  {table} ({_rows(info['rows'])}): {cols}" + (f", ... and {more} more" if more > 0 else ""))
    return "\n".join(out)


def find_columns(pattern, names=None):
    """Columns whose name matches the regular expression (case-insensitive), in every dataset."""
    match = re.compile(pattern, re.I)
    out = []
    for name, tables in _each(names or datasets()).items():
        if isinstance(tables, Exception):
            out.append(f"{name}: could not be read: {tables}")
            continue
        for table, info in tables.items():
            hits = [f"{c} {t}" for c, t in info["columns"] if match.search(c)]
            if hits:
                out.append(f"{name}.{table} ({_rows(info['rows'])}): {', '.join(hits)}")
    return "\n".join(out) or f"No column matches {pattern!r}."


def main(argv):
    usage = "usage: python -m wbdata survey | describe <project.dataset> [table ...] | find <regex>"
    if not argv:
        return usage
    command, args = argv[0], argv[1:]
    if command == "survey":
        return survey(args or None)
    if command == "describe" and args:
        return describe(args[0], args[1:] or None)
    if command == "find" and args:
        return find_columns(args[0])
    return usage


if __name__ == "__main__":
    print(main(sys.argv[1:]))
