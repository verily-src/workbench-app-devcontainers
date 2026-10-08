"""MCP server: lets external agents drive the cohort builder.

Exposes the same engine layer the UI uses as MCP tools over streamable
HTTP at /mcp. An agent (Claude Code, a Managed Agent, any MCP client)
can list datasources, open tables, and run cross-filtered queries.

Reachability note: on a Workbench VM the public URL sits behind the app
proxy, which requires browser cookies — so external agents typically
connect from inside the workspace (localhost:8080/mcp on the VM, or a
port-forward). The import is guarded so the app runs without the `mcp`
package installed.
"""

import json
import logging

logger = logging.getLogger(__name__)

try:
    from mcp.server.mcpserver import MCPServer  # mcp >= 2
    AVAILABLE = True
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer  # mcp 1.x
        AVAILABLE = True
    except ImportError:
        AVAILABLE = False
        mcp = None

if AVAILABLE:
    mcp = MCPServer(
        name="cohort-studio",
        instructions=(
            "Cohort exploration over a Verily Workbench workspace. "
            "Flow: list_datasources -> list_tables -> open_dataset -> "
            "query_dataset with filters."),
    )

    def http_app():
        """ASGI app served at the /mcp mount (path '/' inside the mount)."""
        return mcp.streamable_http_app(stateless_http=True,
                                       streamable_http_path="/")

    @mcp.tool()
    def list_datasources() -> str:
        """List available datasources (Aurora databases, S3 folders,
        BigQuery datasets) in the workspace."""
        import db
        sources = ([{"kind": "aurora", "id": r["id"]}
                    for r in db.list_aurora_resources()]
                   + [{"kind": "s3", "id": r["id"]}
                      for r in db.list_s3_folders()]
                   + [{"kind": "bq", "id": r["id"]}
                      for r in db.list_bq_datasets()])
        return json.dumps({"ready": db.resources_ready(), "sources": sources})

    @mcp.tool()
    def list_tables(kind: str, resource_id: str) -> str:
        """List tables (Aurora/BigQuery) or data files (S3) in a
        datasource. kind is 'aurora', 's3', or 'bq'."""
        import bq
        import db
        import duck
        if kind == "aurora":
            items = [t["name"] for t in db.list_aurora_tables(resource_id)]
        elif kind == "s3":
            items = duck.list_s3_files(resource_id)
        elif kind == "bq":
            for d in db.list_bq_datasets():
                if d["id"] == resource_id:
                    items = bq.list_tables(d["project"], d["dataset"])
                    break
            else:
                raise ValueError(f"Unknown BigQuery dataset: {resource_id}")
        else:
            raise ValueError(f"Unknown kind: {kind}")
        return json.dumps(items)

    @mcp.tool()
    def open_dataset(kind: str, resource_id: str, table: str) -> str:
        """Load a table into memory for querying. Returns a dataset_id
        and a column profile (names, filter kinds, categorical values,
        numeric ranges)."""
        import bq
        import datasets
        import db
        import duck
        import queries
        if kind == "aurora":
            df = db.fetch_aurora_table(resource_id, table, queries.ROW_CAP)
        elif kind == "s3":
            df = duck.fetch_s3_file(resource_id, table, queries.ROW_CAP)
        elif kind == "bq":
            for d in db.list_bq_datasets():
                if d["id"] == resource_id:
                    df = bq.fetch_table(d["project"], d["dataset"], table,
                                        queries.ROW_CAP)
                    break
            else:
                raise ValueError(f"Unknown BigQuery dataset: {resource_id}")
        else:
            raise ValueError(f"Unknown kind: {kind}")
        return json.dumps(
            datasets.open_dataset(df, f"{resource_id} / {table}"))

    @mcp.tool()
    def query_dataset(dataset_id: str, filters_json: str = "[]",
                      page: int = 0, page_size: int = 50) -> str:
        """Query an opened dataset with cross-filtering. filters_json is
        a JSON array of {column, kind: 'categorical'|'range',
        values?: [..], min?: n, max?: n}. Returns total/filtered counts
        and a page of rows."""
        import datasets
        filters = json.loads(filters_json)
        result = datasets.query(dataset_id, filters, [], page=page,
                                page_size=page_size)
        return json.dumps({k: result[k] for k in ("total", "filtered", "rows")})
