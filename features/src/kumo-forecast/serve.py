#!/usr/bin/env python3
"""Serves the Kumo forecast MCP server for the AI Research Assistant app.

It forecasts an outcome for the entities of a cohort the cohort designer locked, with NVIDIA Kumo
Relational over the tables of the cohort's dataset the agent chooses (default: every table with the
cohort's key column), compares it with classical baselines, and writes the highest-risk members to a controlled bucket of the
workspace. The outcome is described as rows of one of the dataset's tables (kumo_forecast.outcome),
checked against the schema and sent as query parameters. The cohort is read from the designer's
session files (kumo_forecast.cohort), so nothing the driving model writes is executed and the
designer is unchanged.

usage: serve.py --sessions-dir <designer sessions/> --state-dir <dir> [--bind 127.0.0.1]
           [--port 9244] [--allowed-host <name>]... [--gpu-gb 5]
"""
import argparse
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

from fastmcp import FastMCP

from kumo_forecast.cohort import CohortError
from kumo_forecast.schema import SchemaError
from kumo_forecast.service import Service

mcp = FastMCP("forecast", instructions=(
    "Forecasts an outcome for a locked cohort from the cohort designer with NVIDIA Kumo Relational, "
    "compares Kumo with classical baselines, and writes the highest-risk members to a controlled bucket."))
SERVICE: Service | None = None


async def _call(fn, *args, **kwargs) -> dict:
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except (CohortError, SchemaError, ValueError) as err:
        return {"error": str(err)}


# The longest a tool holds its request open, under the agent's own call timeout (60 s for
# OpenCode), with room for the sandbox's proxy: a forecast on a CPU, or a dataset's first read,
# takes longer, and a call that timed out was sent again and again while each one kept computing.
# Progress notifications cannot stretch it: the proxy delivers a response whole.
WAIT_S = 50
# Work still running past WAIT_S, by job id, and the job id of each call's arguments, so the same
# call made again while it runs waits on the same work instead of starting more.
JOBS: dict[str, asyncio.Task] = {}
RUNNING: dict[tuple, str] = {}
# When each job finished, and how long a finished job whose answer was never collected is kept:
# a new job drops the older ones.
FINISHED: dict[str, float] = {}
KEEP_FINISHED_S = 3600


def _forget(job_id: str) -> None:
    JOBS.pop(job_id, None)
    FINISHED.pop(job_id, None)


def _drop_stale() -> None:
    now = time.monotonic()
    for job_id in [j for j, at in FINISHED.items() if now - at > KEEP_FINISHED_S]:
        _forget(job_id)


async def _answer(job_id: str, wait_s: int) -> dict:
    task = JOBS[job_id]
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=max(1, min(int(wait_s), WAIT_S)))
    except asyncio.TimeoutError:
        return {"status": "running", "job_id": job_id,
                "next": "call wait_for_result with this job_id until it returns the answer; do not "
                        "call the tool again"}
    except Exception as err:  # noqa: BLE001 - any failure of the work is the answer
        _forget(job_id)
        return {"error": f"{type(err).__name__}: {err}"}
    _forget(job_id)
    return task.result()


async def _waited(name: str, fn, *args) -> dict:
    """``_call``, answered within WAIT_S: the result, or a job id for wait_for_result."""
    key = (name, repr(args))
    job_id = RUNNING.get(key)
    if job_id is None or job_id not in JOBS:
        _drop_stale()
        job_id = uuid.uuid4().hex[:12]
        task = asyncio.create_task(_call(fn, *args))
        task.add_done_callback(lambda _t, k=key, j=job_id: (RUNNING.pop(k, None),
                                                            FINISHED.__setitem__(j, time.monotonic())))
        JOBS[job_id], RUNNING[key] = task, job_id
    return await _answer(job_id, WAIT_S)


@mcp.tool
async def get_cohort_info(cda_session_id: str = "latest", lock_version: int | None = None,
                          time_columns: dict[str, str] | None = None) -> dict:
    """Describe a cohort the cohort designer locked: its request, size, the dataset it is drawn
    from, the key that identifies its members, the date the data ends and every table with that key
    (rows, the column that dates its rows, its first 20 column names) to choose from for forecast_risk. cda_session_id is "latest" (the newest
    session with a lock) or a designer session id. time_columns ({table: column}) overrides the
    column chosen to date a table. Counts under 20 show as "<20"; no participant is named."""
    return await _waited("get_cohort_info", SERVICE.cohort_info, cda_session_id, lock_version, time_columns)


@mcp.tool
async def forecast_risk(outcome: dict, as_of: str | None = None, horizon_days: int = 365,
                        cda_session_id: str = "latest", lock_version: int | None = None,
                        time_columns: dict[str, str] | None = None,
                        tables: list[str] | None = None) -> dict:
    """Forecast, for each member of the locked cohort at risk on as_of (YYYY-MM-DD), whether the
    outcome starts within horizon_days (30 to 1825), with NVIDIA Kumo Relational reading the
    dataset's tables in context (no training, no hand-built features). outcome is rows of one of
    the dataset's tables with the cohort's key; a member has it from the date of its first such row:
    {"table": "condition_occurrence", "where": [{"column": "condition_concept_id", "op": "in",
    "value": [443597]}]}. op is one of in, =, !=, <, <=, >, >= or between ([low, high]); several
    conditions must all hold (a lab: the concept, then "value_as_number" "<" 60); no conditions means
    any row (a death). "time_column" overrides the column that dates the rows. as_of defaults to
    the data end less horizon_days, so the outcome can be checked; the answer says the date used.
    Returns a run_id for compare_to_baselines and select_highest_risk, risk quartiles, what the top
    10% have in common against the rest (high_risk_profile), the tables read, and where the outcome
    is already observed, the observed rates and the AUROC. Takes about a minute (longer the first
    time a dataset is read, or without a GPU): past 50 seconds it returns a job_id for
    wait_for_result. tables: the dataset's tables to read (choose from get_cohort_info's tables);
    each must have the cohort's key. Default: all of them."""
    return await _waited("forecast_risk", SERVICE.forecast, outcome, cda_session_id, as_of, horizon_days,
                         lock_version, time_columns, tables)


@mcp.tool
async def compare_to_baselines(run_id: str) -> dict:
    """Compare a forecast_risk run with logistic regression and gradient-boosted trees trained on
    features built by rule from the same history: AUROC and the observed rate in each model's top
    10%. Needs a run whose outcome window has been observed. Takes about a minute."""
    return await _waited("compare_to_baselines", SERVICE.compare, run_id)


@mcp.tool
async def wait_for_result(job_id: str, wait_s: int = 50) -> dict:
    """The answer of a get_cohort_info, forecast_risk or compare_to_baselines call that returned
    status 'running' and a job_id: the work goes on after the call returns. Waits up to wait_s
    (at most 50) and returns the answer, or status 'running' again: call it again. Never call the
    original tool again for the same work."""
    if job_id not in JOBS:
        return {"error": f"no running job {job_id}: its answer was already returned, or the server restarted"}
    return await _answer(job_id, wait_s)


@mcp.tool
async def select_highest_risk(run_id: str, destination: str, top_n: int = 16) -> dict:
    """Write the top_n highest-risk members of a forecast_risk run to destination, a CSV with the
    key column and risk. destination is a gs:// URL of a file in a controlled bucket resource of the
    workspace; any other is refused. Returns how many were selected, where they were written and,
    where known, the observed outcome rate among them against all at risk. Ids are not returned."""
    return await _call(SERVICE.select, run_id, destination, top_n)


TOOLS = ("get_cohort_info", "forecast_risk", "compare_to_baselines", "select_highest_risk", "wait_for_result")


def main():
    global SERVICE
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], prog="serve.py")
    p.add_argument("--sessions-dir", required=True, help="the cohort designer's sessions folder")
    p.add_argument("--state-dir", required=True, help="where runs and the table cache are kept")
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9244)
    p.add_argument("--allowed-host", action="append", default=[], help="a host name the server also answers to")
    p.add_argument("--gpu-gb", type=float, default=float(os.environ.get("KUMO_FORECAST_GPU_GB", "5")),
                   help="the most GPU memory the model may use")
    p.add_argument("--billing-project", default=os.environ.get("KUMO_FORECAST_BILLING_PROJECT"),
                   help="the project BigQuery jobs run in (default: the one the designer used)")
    p.add_argument("--context", type=int, default=int(os.environ.get("KUMO_FORECAST_CONTEXT", "3000")),
                   help="labeled histories the model reads in context; GPU memory grows with it")
    p.add_argument("--estimators", type=int, default=int(os.environ.get("KUMO_FORECAST_ESTIMATORS", "2")),
                   help="ensemble size; 4 steadies the run-to-run spread for about 3x the time")
    a = p.parse_args()
    SERVICE = Service(Path(a.sessions_dir), Path(a.state_dir), a.billing_project, a.gpu_gb, a.context, a.estimators)
    options = {"host": a.bind, "port": a.port, "host_origin_protection": "auto",
               # The wire form the sandbox's proxy carries, as the cohort designer's server uses:
               # plain JSON replies and no MCP session id. Every tool here is stateless (run_id).
               "json_response": True, "stateless_http": True,
               # Idle connections stay open for an hour (uvicorn's default is 5 s): the sandbox's
               # proxy does not pass the server's close on, so the agent's next call failed once.
               "uvicorn_config": {"timeout_keep_alive": 3600}}
    if a.allowed_host:
        options["allowed_hosts"] = list(dict.fromkeys(a.allowed_host))
    print(f"kumo-forecast on {a.bind}:{a.port}/mcp; sessions {a.sessions_dir}; GPU cap {a.gpu_gb} GB",
          file=sys.stderr, flush=True)
    mcp.run("http", show_banner=False, **options)


if __name__ == "__main__":
    main()
