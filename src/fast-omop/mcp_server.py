from mcp.server.fastmcp import FastMCP
import json
import subprocess
from datetime import datetime
from pathlib import Path
import sqlglot.errors
import os
import sys
import sqlglot

mcp = FastMCP("FastOMOP")    

def run_bq_query(query, project_id, output_format="csv"):
    """Execute a BigQuery query and return results."""
    cmd = [
        "bq", "query",
        f"--project_id={project_id}",
        "--use_legacy_sql=false",
        f"--format={output_format}",
        query
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # print(f"Error executing query: {result.stderr}", file=sys.stderr)
        return f"Error executing query: {result.stderr}"
    return result.stdout



@mcp.tool()
def Select_Query(query: str) -> str:
    project_id = os.getenv("PROJECT_ID")

    try:
        sqlglot.transpile(query)
        results = run_bq_query(query, project_id)

        # TODO: Write to output

        if not results:
            print(f"  ⚠ No results")
        
        return results

    except sqlglot.errors.ParseError as e:
        return f"SQL validation error: {e}"


@mcp.tool()                                           
def Get_Information_Schema() -> str:
    project_id = os.getenv("PROJECT_ID")
    dataset_id = os.getenv("DATASET_ID")
    return f"{project_id}.{dataset_id}"

if __name__ == "__main__":
    mcp.run()