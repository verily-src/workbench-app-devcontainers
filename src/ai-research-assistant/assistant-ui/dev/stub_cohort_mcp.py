#!/usr/bin/env python3
"""A stand-in for the cohort designer's MCP server, for working on the UI without the GPUs.

It offers the seven tools the sandbox sees (features/src/cohort-designer/sandbox/cohort.yaml)
with the same names, arguments and reply shapes, and walks one scripted conversation: the
first message is answered with choices, the answer to the choices with an approval request
for the lock, and the approval with a locked cohort. The numbers are made up.

usage: stub_cohort_mcp.py [--port 9243] [--delay 4]
"""
import argparse
import asyncio
import time

from fastmcp import FastMCP

mcp = FastMCP("cohort-designer-stub")
DELAY = 4.0
S = {"status": "idle", "stage": "new", "request": "", "ready_at": 0.0, "seq": 0, "locked": False}

FUNNEL = [
    {"step": "All people in the dataset", "n": 25000},
    {"step": "Adults at index (18+)", "n": 21480},
    {"step": "Meets the criteria", "n": 1312},
    {"step": "12 months of prior observation", "n": 1104},
    {"step": "Has a second visit", "n": 141},
]
DEFINITION = {
    "name": "Demo cohort (stand-in)",
    "source": "dataset",
    "index": "first qualifying record",
    "include": ["age >= 18 at index", "criteria met", ">= 365 days prior observation"],
    "exclude": ["no second visit"],
}


def _advance():
    """Moves a working turn on once its delay has passed."""
    if S["status"] != "working" or time.time() < S["ready_at"]:
        return
    S["status"] = "awaiting_approval" if S["stage"] == "locking" else "idle"


def _start(stage):
    S.update(status="working", stage=stage, ready_at=time.time() + DELAY, seq=S["seq"] + 1)


@mcp.tool
async def send_message(text: str, relayed: bool = False) -> dict:
    """Send the user's request to the cohort designer. Returns at once with status 'working'."""
    S["request"] = text
    _start("locking" if S["stage"] == "chosen" else "drafted")
    return {"status": "working", "accepted": "started_turn", "seq": S["seq"]}


@mcp.tool
async def wait_for_reply(timeout_s: int = 20) -> dict:
    """Wait for the cohort designer, then say where it stands. Call again while it returns
    status 'working'."""
    deadline = time.time() + max(1, min(int(timeout_s), 25))
    _advance()
    while S["status"] == "working" and time.time() < deadline:
        await asyncio.sleep(0.5)
        _advance()
    answer = {"status": S["status"], "session": "stub"}
    if S["status"] == "working":
        answer["progress"] = {"tool_calls": 3, "latest": ["list_tables", "profile_column", "count"]}
        answer["next"] = "call wait_for_reply again"
    elif S["status"] == "awaiting_approval":
        answer["approval_request"] = {
            "id": "apr-1", "kind": "approval_request",
            "lines": ["Lock the cohort definition at revision 3?",
                      "141 people; the definition cannot be edited after the lock."]}
        answer["next"] = "show the person these lines, then respond_approval with the request's id"
    elif S["stage"] == "drafted":
        answer["reply"] = ("I drafted a cohort for: " + S["request"] + "\n\n"
                           "It has 1,104 people before the second-visit requirement. One thing is yours to decide.")
        answer["choices"] = {"list_id": "ch-1", "text": (
            "1. Index date: (a) first qualifying record, (b) first qualifying measurement\n"
            "2. Require a second visit: (a) yes, 141 people, (b) no, 1,104 people")}
    elif S["stage"] == "locked":
        answer["reply"] = ("The cohort is locked at revision 3: 141 people, each with a "
                           "second visit. Ask for the funnel or the summary to see the counts.")
    else:
        answer["reply"] = "Recorded. Say when to lock the cohort."
    return answer


@mcp.tool
def get_status() -> dict:
    """One line on whether the designer is working."""
    _advance()
    return {"status": S["status"], "session": "stub", "last_seq": S["seq"]}


@mcp.tool
async def answer_choices(list_id: str, picks: list[str], relayed: bool = False) -> dict:
    """Send the person's picks for the choices now shown."""
    S["stage"] = "chosen"
    _start("locking")
    return {"status": "working", "accepted": True, "list_id": list_id, "picks": picks}


@mcp.tool
def respond_approval(request_id: str, approve: bool, note: str = "") -> dict:
    """Answer an approval request with the person's decision."""
    if S["status"] != "awaiting_approval":
        return {"resolved": False, "note": f"no open approval {request_id!r}"}
    S["locked"] = approve
    _start("locked" if approve else "chosen")
    return {"resolved": True, "decision": "allow" if approve else "deny"}


@mcp.tool
def get_cohort_definition() -> dict:
    """The current cohort definition."""
    return {"revision": 3, "locked": S["locked"], "definition": DEFINITION}


@mcp.tool
def get_results(which: str | None = None) -> dict:
    """The results the designer computed; pass 'which' (summary, funnel) for one block."""
    blocks = {"summary": {"n": 141, "female": 74, "male": 67, "median_age": 58},
              "funnel": FUNNEL}
    if which is None:
        return {**blocks, "current": {k: True for k in blocks}}
    if which not in blocks:
        return {"error": f"unknown result {which!r}; expected one of {list(blocks)}"}
    return {which: blocks[which], "current": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=9243)
    parser.add_argument("--delay", type=float, default=4.0, help="seconds one designer turn takes")
    args = parser.parse_args()
    DELAY = args.delay
    mcp.run(transport="http", host="127.0.0.1", port=args.port)
