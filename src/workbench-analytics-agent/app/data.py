"""BigQuery access for the app.

The app runs queries with whatever Google credentials its environment already
has. In Workbench that is the service account Workbench creates for the person
who launched the app, so they only see data they have been given access to.

Nothing in this file names a dataset or a table. The dataset comes from the
person using the app, and the two built-in queries work on any dataset.

Every query goes through `run_select`, which enforces the limits below.
"""

from __future__ import annotations

import concurrent.futures
import re
from dataclasses import dataclass

import google.auth
from google.api_core import exceptions as api_errors
from google.auth import exceptions as auth_errors
from google.auth.transport import requests as auth_requests
from google.cloud import bigquery

# Limits applied to every query the app runs.
MAX_BYTES_BILLED = 5 * 1024**3
QUERY_TIMEOUT_SECONDS = 30
MAX_ROWS_SHOWN = 500
MAX_TABLES_LISTED = 500

_PROJECT_PATTERN = r"[a-z][a-z0-9-]{4,28}[a-z0-9]"
_NAME_PATTERN = r"[A-Za-z0-9_]{1,1024}"


class DataError(Exception):
    """A problem the page can show to the person as it is.

    `kind` is one of: bad_input, no_credentials, no_access, not_found,
    not_read_only, too_big, timeout, other.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ConnectionInfo:
    identity: str
    project: str


@dataclass(frozen=True)
class QueryResult:
    rows: list[dict]
    sql: str
    bytes_processed: int
    truncated: bool


def connect() -> tuple[bigquery.Client, ConnectionInfo]:
    """Create a BigQuery client from the environment's own credentials."""
    try:
        credentials, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
    except auth_errors.DefaultCredentialsError as error:
        raise DataError(
            "no_credentials",
            "No Google credentials were found in this environment.",
        ) from error
    if not project:
        raise DataError(
            "no_credentials",
            "Google credentials were found, but no project to run queries in.",
        )
    client = bigquery.Client(project=project, credentials=credentials)
    return client, ConnectionInfo(identity=_identity_of(credentials), project=project)


def _identity_of(credentials) -> str:
    """Describe who the credentials belong to, without failing the connection."""
    email = getattr(credentials, "service_account_email", "") or ""
    if email in ("", "default"):
        # On a cloud VM the real address is only known after a refresh.
        try:
            credentials.refresh(auth_requests.Request())
        except Exception:  # the identity is informational only
            pass
        email = getattr(credentials, "service_account_email", "") or ""
    if email and email != "default":
        return email
    account = getattr(credentials, "account", "") or ""
    return account or "your own Google login"


def parse_dataset(path: str) -> tuple[str, str]:
    """Split "project.dataset" (or "project:dataset") into its two parts."""
    match = re.fullmatch(
        rf"\s*({_PROJECT_PATTERN})[.:]({_NAME_PATTERN})\s*", path or ""
    )
    if not match:
        raise DataError(
            "bad_input",
            "Enter the dataset as project.dataset, for example my-project.my_dataset.",
        )
    return match.group(1), match.group(2)


def list_tables(client: bigquery.Client, dataset_path: str) -> list[dict]:
    """Return the tables and views in a dataset, as {"name", "type"} rows."""
    project, dataset = parse_dataset(dataset_path)
    try:
        tables = client.list_tables(
            f"{project}.{dataset}", max_results=MAX_TABLES_LISTED
        )
        return sorted(
            (
                {"name": table.table_id, "type": table.table_type.lower()}
                for table in tables
            ),
            key=lambda row: row["name"],
        )
    except Exception as error:
        raise _explain(error, what=f"the dataset {project}.{dataset}") from error


def count_rows(client: bigquery.Client, dataset_path: str, table: str) -> QueryResult:
    """Count the rows of one table or view in the dataset."""
    project, dataset = parse_dataset(dataset_path)
    if not re.fullmatch(_NAME_PATTERN, table or ""):
        raise DataError("bad_input", "That is not a valid table name.")
    sql = f"SELECT COUNT(*) AS row_count FROM `{project}.{dataset}.{table}`"
    return run_select(client, sql, what=f"the table {table}")


def run_select(client: bigquery.Client, sql: str, what: str = "the data") -> QueryResult:
    """Run one read-only query under the app's limits.

    The query is first checked without running it. Anything that is not a
    plain SELECT is refused, and a query that would read more than the limit
    never starts.
    """
    try:
        check = client.query(
            sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        )
        if check.statement_type != "SELECT":
            raise DataError("not_read_only", "Only read-only queries are allowed.")
        if (check.total_bytes_processed or 0) > MAX_BYTES_BILLED:
            raise DataError("too_big", _too_big_message())

        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED),
        )
        try:
            iterator = job.result(
                timeout=QUERY_TIMEOUT_SECONDS, max_results=MAX_ROWS_SHOWN + 1
            )
        except concurrent.futures.TimeoutError as error:
            job.cancel()
            raise DataError(
                "timeout",
                f"The query took longer than {QUERY_TIMEOUT_SECONDS} seconds and was stopped.",
            ) from error
        rows = [dict(row.items()) for row in iterator]
    except DataError:
        raise
    except Exception as error:
        raise _explain(error, what=what) from error

    return QueryResult(
        rows=rows[:MAX_ROWS_SHOWN],
        sql=sql,
        bytes_processed=job.total_bytes_processed or 0,
        truncated=len(rows) > MAX_ROWS_SHOWN,
    )


def _too_big_message() -> str:
    limit_gb = MAX_BYTES_BILLED / 1024**3
    return f"The query would read more than the {limit_gb:g} GB limit, so it was not run."


def _explain(error: Exception, what: str) -> DataError:
    """Turn a Google error into a message for the person using the app."""
    if isinstance(error, api_errors.Forbidden):
        return DataError(
            "no_access",
            f"You do not have access to {what}. "
            "Ask the data's owner for read access, then try again.",
        )
    if isinstance(error, api_errors.NotFound):
        return DataError(
            "not_found",
            f"Could not find {what}. Check the name. "
            "If it is right, you may not have access to it.",
        )
    if isinstance(error, api_errors.BadRequest) and "bytesBilledLimitExceeded" in str(error):
        return DataError("too_big", _too_big_message())
    if isinstance(error, auth_errors.GoogleAuthError):
        return DataError(
            "no_credentials",
            "Google would not accept this environment's credentials.",
        )
    return DataError("other", f"The query failed: {error}")
