"""Live evaluation of the Studio platform agent (Agent page) through the app's HTTP API.

The harness sends golden tasks to a running app exactly as the browser does
(``POST /api/agent/chat/stream``, NDJSON events, owner cookie, ``session_id`` for
follow-up turns) and scores the replies. It uses only the standard library and
imports nothing from ``app/``, so it can run against a local app or a Workbench
deployment.

Safety: the HTTP client allowlists the requests it may make (GET config/plans,
POST chat stream and run cancel). It can never call ``/approve`` and never
changes settings. After each task it re-reads the session's workflow plans and
fails the task if any plan was submitted. Running tasks still writes normal
agent-session history and may open ephemeral or saved agent dashboards, as any
chat does.

Examples (run from src/cohort-studio):

    python3 scripts/evaluate_agent_live.py --self-test
    python3 scripts/evaluate_agent_live.py --base-url http://127.0.0.1:8000 \\
        --provider anthropic --model claude-opus-5-5 --repeat 3
    python3 scripts/evaluate_agent_live.py --base-url https://<workbench-app-url> \\
        --header "Authorization: Bearer $(gcloud auth print-access-token)" \\
        --tasks omop_total_persons,followup_restrict_to_women

``--provider``/``--model`` only label the run. The app's configured model is what
runs; it is read from ``GET /api/config`` and recorded, with a warning (or an
abort with ``--require-config-match``) on mismatch. Results go to
``.eval-results/agent-live-<timestamp>/results.json`` unless ``--output`` is set.
Exit code is 0 only if every run of every selected task passed.
"""
from __future__ import annotations

import argparse
import http.cookies
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_TASKS = HERE / "agent_eval_tasks.json"
DEFAULT_FIXTURES = HERE / "agent_eval_fixtures.json"
HARNESS_VERSION = 1

LAUNCHED_STATUSES = {"submitting", "submission_unknown", "submitted", "running", "completed", "failed"}
CHECK_TYPES = {"count", "tool_called", "tool_not_called", "reply_contains", "reply_not_contains",
               "concept_id", "join_keys", "workflow_ready", "same_session", "completion_reason", "no_limit"}
MAX_MESSAGE = 8000
TURN_DEADLINE_SECONDS = 900
SOCKET_TIMEOUT_SECONDS = 60
_COUNT_KEY = re.compile(r"(^|_)(rows|count|total|persons|people|filtered|distinct|entities)($|_)", re.I)


# --------------------------------------------------------------------------- transport

class UnsafeRequest(RuntimeError):
    """Raised when the harness is asked to make a request outside its allowlist."""


_ALLOWED = [
    ("GET", re.compile(r"^/api/config$")),
    ("GET", re.compile(r"^/api/agent/workflows$")),
    ("GET", re.compile(r"^/api/agent/chat/history$")),
    ("POST", re.compile(r"^/api/agent/chat/stream$")),
    ("POST", re.compile(r"^/api/agent/chat/runs/[0-9a-fA-F-]{36}/cancel$")),
]


def check_request_allowed(method: str, path: str):
    """Structural guard: the harness never approves workflows or writes settings."""
    bare = urllib.parse.urlsplit(path).path
    if "approve" in bare.lower():
        raise UnsafeRequest(f"Refusing {method} {bare}: the harness never approves workflows.")
    if not any(method == m and pattern.match(bare) for m, pattern in _ALLOWED):
        raise UnsafeRequest(f"Refusing {method} {bare}: not in the evaluation allowlist.")


class ApiClient:
    def __init__(self, base_url: str, headers: dict | None = None, cookies: dict | None = None):
        self.base_url = base_url.rstrip("/")
        # Cookies are managed by hand: user-supplied auth cookies (--cookie) plus
        # cookies the app sets, notably the Agent owner cookie. urllib's cookie
        # processor skips its jar whenever a Cookie header is already present.
        self.headers = {k: v for k, v in (headers or {}).items() if k.lower() != "cookie"}
        self.cookies = dict(cookies or {})
        for header, value in (headers or {}).items():
            if header.lower() == "cookie":
                for part in value.split(";"):
                    if "=" in part:
                        name, val = part.split("=", 1)
                        self.cookies[name.strip()] = val.strip()
        self.opener = urllib.request.build_opener()

    def _remember(self, response_headers):
        for value in response_headers.get_all("Set-Cookie") or []:
            parsed = http.cookies.SimpleCookie()
            try:
                parsed.load(value)
            except http.cookies.CookieError:
                continue
            for name, morsel in parsed.items():
                self.cookies[name] = morsel.value

    def _open(self, method, path, body=None, timeout=SOCKET_TIMEOUT_SECONDS):
        check_request_allowed(method, path)
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json, application/x-ndjson", **self.headers}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            resp = self.opener.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            self._remember(exc.headers)
            raise
        self._remember(resp.headers)
        return resp

    def get_json(self, path):
        with self._open("GET", path) as resp:
            return json.loads(resp.read().decode())

    def stream_chat(self, message, session_id=None, new_session=False):
        """Yield raw byte chunks of the NDJSON agent stream; retries 429 (all slots busy)."""
        body = {"message": message, "new_session": bool(new_session)}
        if session_id:
            body["session_id"] = session_id
        for attempt in range(6):
            try:
                resp = self._open("POST", "/api/agent/chat/stream", body)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 5:
                    time.sleep(5 * (attempt + 1))
                    continue
                raise
        with resp:
            while True:
                chunk = resp.read1(65536) if hasattr(resp, "read1") else resp.read(4096)
                if not chunk:
                    return
                yield chunk

    def cancel(self, run_id):
        try:
            with self._open("POST", f"/api/agent/chat/runs/{run_id}/cancel", {}):
                return True
        except Exception:
            return False


def parse_ndjson(chunks):
    """Incrementally decode NDJSON from byte/str chunks. Malformed lines become _malformed events."""
    pending = ""
    for chunk in chunks:
        pending += chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            if line.strip():
                yield _decode_line(line)
    if pending.strip():
        yield _decode_line(pending)


def _decode_line(line):
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return {"type": "_malformed", "raw": line[:200]}
    return value if isinstance(value, dict) else {"type": "_malformed", "raw": line[:200]}


# --------------------------------------------------------------------------- turn collection

def collect_turn(events, deadline=None, on_started=None):
    """Fold stream events into a turn record. Tolerates unknown event types and extra fields."""
    turn = {"run_id": None, "result": None, "error": None, "error_event": None, "cancelled": None,
            "ended": False, "events": 0, "heartbeats": 0, "model_steps": 0, "tool_starts": [],
            "tool_errors": [], "runtime_limits": [], "approval_required": False, "malformed": 0,
            "stages": {}, "timed_out": False}
    for event in events:
        kind = event.get("type")
        turn["events"] += 1
        if kind == "heartbeat":
            turn["heartbeats"] += 1
        elif kind == "started":
            turn["run_id"] = event.get("run_id")
            if on_started:
                on_started(turn["run_id"])
        elif kind == "progress":
            stage = event.get("stage", "step")
            turn["stages"][stage] = turn["stages"].get(stage, 0) + 1
            if stage == "model_start":
                turn["model_steps"] += 1
            elif stage == "tool_start":
                turn["tool_starts"].append(event.get("tool_name") or "")
            elif stage == "tool_end" and event.get("error_code"):
                turn["tool_errors"].append({"tool": event.get("tool_name"), "code": event.get("error_code")})
            elif stage == "runtime_limit":
                turn["runtime_limits"].append(event.get("reason") or "limit")
            elif stage == "approval_required":
                turn["approval_required"] = True
        elif kind == "result":
            turn["result"] = event.get("result") if isinstance(event.get("result"), dict) else {}
        elif kind == "error":
            turn["error"] = str(event.get("message") or "error")
            turn["error_event"] = event
        elif kind == "cancelled":
            turn["cancelled"] = event
        elif kind == "end":
            turn["ended"] = True
            break
        elif kind == "_malformed":
            turn["malformed"] += 1
        if deadline is not None and time.monotonic() > deadline:
            turn["timed_out"] = True
            break
    return turn


def run_turn(client, message, session_id, new_session):
    started = time.monotonic()
    deadline = started + TURN_DEADLINE_SECONDS
    run_ids = []
    try:
        turn = collect_turn(parse_ndjson(client.stream_chat(message, session_id, new_session)),
                            deadline=deadline, on_started=run_ids.append)
    except KeyboardInterrupt:
        for run_id in run_ids:
            client.cancel(run_id)
        raise
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode()[:300]
        except Exception:
            pass
        turn = collect_turn([])
        turn["error"] = f"HTTP {exc.code}: {detail}"
    except Exception as exc:  # network failure, socket timeout
        turn = collect_turn([])
        turn["error"] = f"{type(exc).__name__}: {exc}"
        for run_id in run_ids:
            client.cancel(run_id)
    if turn["timed_out"] and turn["run_id"]:
        client.cancel(turn["run_id"])
        turn["error"] = turn["error"] or f"Harness turn deadline ({TURN_DEADLINE_SECONDS}s) exceeded; run cancelled."
    if not turn["ended"] and not turn["error"]:
        turn["error"] = "Stream ended before the end event."
    turn["message"] = message
    turn["wall_seconds"] = round(time.monotonic() - started, 2)
    return turn


# --------------------------------------------------------------------------- evidence helpers

def _payload(turn):
    """Result payload, falling back to fields carried by error events (future backend shape)."""
    result = turn.get("result")
    if isinstance(result, dict):
        return result
    event = turn.get("error_event") or {}
    return {k: event[k] for k in ("reply", "actions", "workflow_plans", "downloads", "tool_calls",
                                  "tool_results", "usage") if k in event}


def reply_text(turn):
    payload = _payload(turn)
    reply = payload.get("reply")
    if not reply and turn.get("cancelled"):
        reply = turn["cancelled"].get("reply")
    return str(reply or "")


def tool_names(turn):
    names = list(_payload(turn).get("tool_calls") or [])
    return names or list(turn.get("tool_starts") or [])


def _walk(value, key=None):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _walk(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v, key)
    else:
        yield key, value


def structured_numbers(turn):
    """Integer counts the app returned in structured fields (dashboards, plans, tool summaries)."""
    payload = _payload(turn)
    found = set()
    for field in ("actions", "workflow_plans", "downloads", "tool_results"):
        for key, value in _walk(payload.get(field) or [], field):
            if key in ("usage", "step_usage"):
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if key and _COUNT_KEY.search(str(key)):
                found.add(int(value))
    return found


_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(\s*(?:million|thousand|[kKmM])\b)?")


def prose_numbers(text):
    found = set()
    for match in _NUMBER.finditer(text):
        whole = int(match.group(1).replace(",", ""))
        frac = match.group(2)
        unit = (match.group(3) or "").strip().lower()
        scale = {"million": 1_000_000, "m": 1_000_000, "thousand": 1_000, "k": 1_000}.get(unit, 1)
        if scale == 1:
            found.add(whole)
        else:
            found.add(int(round(float(f"{whole}.{frac or 0}") * scale)))
    return found


def _within(value, expected, tol, rel):
    return abs(value - expected) <= max(tol, abs(expected) * rel)


def _structured_strings(turn, fields):
    payload = _payload(turn)
    out = set()
    for action in payload.get("actions") or []:
        if not isinstance(action, dict):
            continue
        for field in fields:
            container = action.get(field)
            if field == "source_ref" and isinstance(action.get("dataset"), dict):
                container = action["dataset"].get("source_ref")
            for _, value in _walk(container):
                if value is not None and not isinstance(value, bool):
                    out.add(str(value))
    for plan in payload.get("workflow_plans") or []:
        if isinstance(plan, dict):
            for _, value in _walk(plan.get("column_mapping") or {}):
                out.add(str(value))
    return out


# --------------------------------------------------------------------------- checks

def _result(check, ok, reason, evidence=None):
    return {"check": check["type"], "label": check.get("label"), "severity": check.get("severity", "hard"),
            "ok": bool(ok), "reason": reason, "evidence": evidence}


def evaluate_check(check, turn, previous):
    kind = check["type"]
    reply = reply_text(turn)
    lower = reply.lower()
    names = tool_names(turn)
    payload = _payload(turn)
    if kind == "count":
        expected = int(check["expected"])
        tol, rel = int(check.get("tolerance", 0)), float(check.get("rel_tolerance", 0.0))
        structured = {n for n in structured_numbers(turn) if _within(n, expected, tol, rel)}
        prose = {n for n in prose_numbers(reply) if _within(n, expected, tol, rel)}
        if check.get("absent"):
            hit = structured or prose
            return _result(check, not hit, f"{expected:,} {'appeared' if hit else 'absent'} as required absent",
                           "structured" if structured else "prose" if prose else None)
        need = check.get("evidence", "any")
        if structured:
            return _result(check, True, f"{expected:,} found in structured response fields", "structured")
        if prose and need != "structured":
            return _result(check, True, f"{expected:,} found in reply text only (no structured count exposed)", "prose")
        seen = sorted(prose_numbers(reply) | structured_numbers(turn))
        return _result(check, False, f"expected {expected:,} (tol {tol}) not found"
                       + (" in structured fields" if need == "structured" and prose else "")
                       + f"; numbers seen: {seen[:20]} (undocumented value)", None)
    if kind in ("tool_called", "tool_not_called"):
        wanted = list(check["tools"])
        hits = [t for t in wanted if t in names]
        if kind == "tool_not_called":
            return _result(check, not hits, f"forbidden tools called: {hits}" if hits else "none of the forbidden tools called", "structured")
        ok = bool(hits) if check.get("mode", "any") == "any" else len(set(hits)) == len(set(wanted))
        return _result(check, ok, f"called {names}; wanted {check.get('mode', 'any')} of {wanted}", "structured")
    if kind == "reply_contains":
        values = check.get("any") or check.get("all") or []
        hits = [v for v in values if v.lower() in lower]
        ok = bool(hits) if "any" in check else len(hits) == len(values)
        return _result(check, ok, f"matched {hits} of {values}", "prose")
    if kind == "reply_not_contains":
        hits = [v for v in check["values"] if v.lower() in lower]
        return _result(check, not hits, f"reply contains {hits}" if hits else "no forbidden text", "prose")
    if kind == "concept_id":
        expected = str(int(check["expected"]))
        if expected in _structured_strings(turn, ("filters", "source_ref")):
            return _result(check, True, f"concept {expected} in dashboard filters/source", "structured")
        if re.search(rf"(?<!\d){expected}(?!\d)", reply):
            return _result(check, True, f"concept {expected} in reply text only", "prose")
        return _result(check, False, f"concept {expected} not found in filters or reply", None)
    if kind == "join_keys":
        keys = list(check["keys"])
        structured = _structured_strings(turn, ("source_ref",))
        missing, evidence = [], "structured"
        for key in keys:
            if key in structured:
                continue
            if re.search(rf"\b{re.escape(key)}\b", reply, re.I):
                evidence = "prose"
                continue
            missing.append(key)
        return _result(check, not missing, f"missing keys {missing}" if missing else f"all keys {keys} named",
                       None if missing else evidence)
    if kind == "workflow_ready":
        statuses = set(check.get("statuses", ["ready"]))
        min_rows = int(check.get("min_rows", 1))
        plans = [p for p in payload.get("workflow_plans") or [] if isinstance(p, dict)]
        if not plans:
            return _result(check, False, "no workflow plan returned", None)
        good = [p for p in plans if p.get("status") in statuses and int(p.get("rows") or 0) >= min_rows
                and not p.get("errors")]
        if good:
            plan = good[-1]
            return _result(check, True, f"plan {plan.get('id')} status {plan.get('status')} rows {plan.get('rows')}", "structured")
        detail = "; ".join(f"{p.get('status')} rows={p.get('rows')} errors={p.get('errors')}" for p in plans)
        return _result(check, False, f"no plan in {sorted(statuses)} with rows >= {min_rows}: {detail}", "structured")
    if kind == "same_session":
        if previous is None:
            return _result(check, False, "no previous turn", None)
        a, b = _payload(previous).get("session_id"), payload.get("session_id")
        return _result(check, bool(a) and a == b, f"previous {a} current {b}", "structured")
    if kind == "completion_reason":
        actual = payload.get("completion_reason") or ("approval_required" if turn.get("approval_required") else None)
        return _result(check, actual == check["expected"], f"completion_reason {actual}", "structured")
    if kind == "no_limit":
        hit = payload.get("limit_reached") or turn.get("runtime_limits")
        return _result(check, not hit, f"limit {payload.get('limit_reason') or turn.get('runtime_limits')}" if hit else "no limit", "structured")
    raise ValueError(f"Unknown check type {kind}")


def evaluate_task(task, turns, server_plans=None, allow_error=False):
    checks = []
    for index, (spec, turn) in enumerate(zip(task["turns"], turns)):
        previous = turns[index - 1] if index else None
        if not (allow_error or task.get("allow_error")):
            problem = turn.get("error") or (None if turn.get("result") is not None else
                                             "cancelled" if turn.get("cancelled") else "no result event")
            checks.append({"check": "stream_ok", "label": None, "severity": "hard", "turn": index,
                           "ok": not problem, "reason": problem or "result received", "evidence": "structured"})
        for check in spec.get("checks", []):
            checks.append({**evaluate_check(check, turn, previous), "turn": index})
    if len(turns) < len(task["turns"]):
        checks.append({"check": "turns_completed", "label": None, "severity": "hard", "turn": len(turns),
                       "ok": False, "reason": f"only {len(turns)} of {len(task['turns'])} turns ran", "evidence": None})
    launched = []
    for turn in turns:
        launched += [p for p in _payload(turn).get("workflow_plans") or []
                     if isinstance(p, dict) and p.get("status") in LAUNCHED_STATUSES]
    launched += [p for p in server_plans or [] if isinstance(p, dict) and p.get("status") in LAUNCHED_STATUSES]
    checks.append({"check": "no_workflow_launched", "label": None, "severity": "hard", "turn": None,
                   "ok": not launched, "evidence": "structured",
                   "reason": "no plan left the ready/blocked state" if not launched else
                   "LAUNCHED plans: " + ", ".join(f"{p.get('id')}={p.get('status')}" for p in launched)})
    passed = all(c["ok"] for c in checks if c["severity"] == "hard")
    return passed, checks


def turn_metrics(turns):
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage_seen = False
    out = {"wall_seconds": round(sum(t.get("wall_seconds", 0) for t in turns), 2), "model_steps": 0,
           "tool_calls": 0, "failed_tool_calls": 0, "errors": [], "limit_reached": False}
    for turn in turns:
        payload = _payload(turn)
        out["model_steps"] += turn.get("model_steps") or int(payload.get("turns") or 0)
        out["tool_calls"] += len(tool_names(turn))
        failed = [r for r in payload.get("tool_results") or [] if isinstance(r, dict) and r.get("status") == "failed"]
        out["failed_tool_calls"] += len(failed) or len(turn.get("tool_errors") or [])
        out["limit_reached"] |= bool(payload.get("limit_reached") or turn.get("runtime_limits"))
        if turn.get("error"):
            out["errors"].append(turn["error"])
        for key in usage:
            value = (payload.get("usage") or {}).get(key)
            if isinstance(value, (int, float)):
                usage[key] += int(value)
                usage_seen = True
    out["tokens"] = usage if usage_seen else None
    return out


def summarize_turn(turn):
    payload = _payload(turn)
    return {"message": turn.get("message"), "reply": reply_text(turn)[:4000],
            "session_id": payload.get("session_id"), "trace_id": payload.get("trace_id"),
            "run_id": turn.get("run_id"), "run_status": payload.get("run_status"),
            "provider": payload.get("provider"), "model": payload.get("model"),
            "tool_calls": tool_names(turn), "tool_results": payload.get("tool_results"),
            "tool_errors": turn.get("tool_errors"), "usage": payload.get("usage"),
            "limit_reached": payload.get("limit_reached"), "limit_reason": payload.get("limit_reason"),
            "completion_reason": payload.get("completion_reason"), "stop_reason": payload.get("stop_reason"),
            "actions": [{"title": a.get("title"), "rows": (a.get("dataset") or {}).get("rows"),
                         "filters": a.get("filters")} for a in payload.get("actions") or [] if isinstance(a, dict)],
            "workflow_plans": [{k: p.get(k) for k in ("id", "workflow", "status", "rows", "errors")}
                               for p in payload.get("workflow_plans") or [] if isinstance(p, dict)],
            "downloads": len(payload.get("downloads") or []),
            "error": turn.get("error"), "model_steps": turn.get("model_steps"),
            "stages": turn.get("stages"), "wall_seconds": turn.get("wall_seconds"),
            "malformed_lines": turn.get("malformed")}


# --------------------------------------------------------------------------- task file

def _substitute(value, variables):
    if isinstance(value, str):
        return re.sub(r"\{(\w+)\}", lambda m: str(variables.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [_substitute(v, variables) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v, variables) for k, v in value.items()}
    return value


def load_tasks(path, variables=None):
    data = json.loads(Path(path).read_text())
    variables = {**(data.get("vars") or {}), **(variables or {})}
    tasks = [_substitute(task, variables) for task in data.get("tasks", [])]
    return tasks


def validate_tasks(tasks):
    problems, seen = [], set()
    for task in tasks:
        tid = task.get("id")
        if not tid or not re.fullmatch(r"[a-z0-9_]+", str(tid)):
            problems.append(f"bad task id {tid!r}")
        if tid in seen:
            problems.append(f"duplicate task id {tid}")
        seen.add(tid)
        turns = task.get("turns") or []
        if not turns:
            problems.append(f"{tid}: no turns")
        for i, turn in enumerate(turns):
            message = turn.get("message")
            if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE:
                problems.append(f"{tid} turn {i}: message must be 1-{MAX_MESSAGE} characters")
            if re.search(r"\{\w+\}", message or ""):
                problems.append(f"{tid} turn {i}: unresolved variable in message")
            for check in turn.get("checks") or []:
                kind = check.get("type")
                if kind not in CHECK_TYPES:
                    problems.append(f"{tid} turn {i}: unknown check {kind}")
                    continue
                if check.get("severity", "hard") not in ("hard", "soft"):
                    problems.append(f"{tid}: bad severity")
                required = {"count": ["expected"], "tool_called": ["tools"], "tool_not_called": ["tools"],
                            "reply_not_contains": ["values"], "concept_id": ["expected"],
                            "join_keys": ["keys"], "completion_reason": ["expected"]}.get(kind, [])
                for field in required:
                    if field not in check:
                        problems.append(f"{tid} turn {i}: {kind} needs {field}")
                if kind == "reply_contains" and not (check.get("any") or check.get("all")):
                    problems.append(f"{tid} turn {i}: reply_contains needs any or all")
                if kind == "same_session" and i == 0:
                    problems.append(f"{tid}: same_session on first turn")
    return problems


# --------------------------------------------------------------------------- self-test

def _chunks(text, size):
    data = text.encode()
    return [data[i:i + size] for i in range(0, len(data), size)]


def self_test(tasks_path=DEFAULT_TASKS, fixtures_path=DEFAULT_FIXTURES, verbose=False):
    """Validate the task file and evaluator against canned streams. Returns a list of failures."""
    failures = []
    tasks = load_tasks(tasks_path)
    failures += [f"task file: {p}" for p in validate_tasks(tasks)]
    by_id = {t["id"]: t for t in tasks}
    fixtures = json.loads(Path(fixtures_path).read_text())
    passing_cover = set()
    for case in fixtures.get("cases", []):
        name = case.get("name", "?")
        task = by_id.get(case.get("task"))
        if task is None:
            failures.append(f"{name}: unknown task {case.get('task')}")
            continue
        turns = []
        for spec in case["turns"]:
            raw = spec.get("raw")
            if raw is None:
                raw = "".join(json.dumps(event) + "\n" for event in spec["events"])
            # Odd chunk sizes split JSON lines across reads, like a real socket.
            turn = collect_turn(parse_ndjson(_chunks(raw, int(spec.get("chunk", 7)))))
            if not turn["ended"] and not turn["error"]:
                turn["error"] = "Stream ended before the end event."
            turn["message"] = "(fixture)"
            turn["wall_seconds"] = 0.0
            turns.append(turn)
        passed, checks = evaluate_task(task, turns, case.get("server_plans"))
        failed = sorted({c["check"] for c in checks if not c["ok"] and c["severity"] == "hard"})
        if passed != case["expect_pass"]:
            failures.append(f"{name}: expected pass={case['expect_pass']} got {passed}; failed hard checks {failed}: "
                            + "; ".join(c["reason"] for c in checks if not c["ok"]))
        for expected in case.get("expect_failed", []):
            if expected not in failed:
                failures.append(f"{name}: expected hard check {expected} to fail; failed {failed}")
        for expected in case.get("expect_soft_failed", []):
            if not any(c["check"] == expected and not c["ok"] and c["severity"] == "soft" for c in checks):
                failures.append(f"{name}: expected soft check {expected} to warn")
        for expected in case.get("expect_evidence", []):
            if not any(c["check"] == expected["check"] and c["evidence"] == expected["evidence"] and c["ok"]
                       for c in checks):
                failures.append(f"{name}: expected {expected['check']} to pass with {expected['evidence']} evidence")
        if "expect_metrics" in case:
            metrics = turn_metrics(turns)
            for key, value in case["expect_metrics"].items():
                if metrics.get(key) != value:
                    failures.append(f"{name}: metric {key}={metrics.get(key)!r}, expected {value!r}")
        if case["expect_pass"]:
            passing_cover.add(task["id"])
        if verbose:
            print(f"  {'ok ' if passed == case['expect_pass'] else 'BAD'} {name}")
    for tid in by_id:
        if tid not in passing_cover:
            failures.append(f"task {tid} has no passing fixture; its checks are unverified")
    # The client must refuse approval and settings writes before any network I/O.
    for method, path in [("POST", "/api/agent/workflows/abc/approve"), ("PUT", "/api/config"),
                         ("POST", "/api/config/llm/test"), ("POST", "/api/agent/chat"),
                         ("GET", "/api/agent/workflows/x/approve?y=1")]:
        try:
            check_request_allowed(method, path)
            failures.append(f"guard allowed {method} {path}")
        except UnsafeRequest:
            pass
    for method, path in [("POST", "/api/agent/chat/stream"), ("GET", "/api/config"),
                         ("GET", "/api/agent/workflows?session_id=1"),
                         ("POST", "/api/agent/chat/runs/0b0f4c39-6c55-4f0e-9b9a-2f7f1d3f0a11/cancel")]:
        try:
            check_request_allowed(method, path)
        except UnsafeRequest:
            failures.append(f"guard refused {method} {path}")
    if prose_numbers("We found 1,000,000 rows, 90,085 people, 1.5 million events and 12k others.") \
            != {1000000, 90085, 1500000, 12000}:
        failures.append("prose number parsing")
    return failures


# --------------------------------------------------------------------------- live run

def _kv(values, sep):
    out = {}
    for value in values or []:
        if sep not in value:
            raise SystemExit(f"Expected KEY{sep}VALUE, got {value!r}")
        key, val = value.split(sep, 1)
        out[key.strip()] = val.strip()
    return out


def fetch_session_plans(client, session_ids):
    plans, errors = [], []
    for sid in sorted(s for s in session_ids if s):
        try:
            plans += client.get_json("/api/agent/workflows?" + urllib.parse.urlencode({"session_id": sid})).get("plans", [])
        except Exception as exc:
            errors.append(f"plan check for {sid}: {type(exc).__name__}: {exc}")
    return plans, errors


def run_task(client, task):
    turns, session_id = [], None
    for index, spec in enumerate(task["turns"]):
        turn = run_turn(client, spec["message"], session_id, new_session=index == 0)
        turns.append(turn)
        session_id = _payload(turn).get("session_id") or (turn.get("cancelled") or {}).get("session_id") or session_id
        if turn.get("error") and not _payload(turn):
            break
    plans, plan_errors = fetch_session_plans(client, {_payload(t).get("session_id") for t in turns})
    passed, checks = evaluate_task(task, turns, plans)
    if plan_errors:
        checks.append({"check": "server_plan_check", "label": None, "severity": "soft", "turn": None,
                       "ok": False, "reason": "; ".join(plan_errors), "evidence": None})
    return passed, checks, turns, plans


def print_summary(runs, out=sys.stdout):
    rows, by_task = [], {}
    for run in runs:
        by_task.setdefault(run["task"], []).append(run)
    header = f"{'task':32} {'pass':>7} {'wall s':>8} {'steps':>6} {'tools':>6} {'tokens':>8}  first failure"
    print(header, file=out)
    print("-" * len(header), file=out)
    summary = {}
    for tid, items in by_task.items():
        passes = sum(r["passed"] for r in items)
        walls = [r["metrics"]["wall_seconds"] for r in items]
        tokens = [r["metrics"]["tokens"]["total_tokens"] for r in items if r["metrics"].get("tokens")]
        first = next((c for r in items for c in r["checks"] if not c["ok"] and c["severity"] == "hard"), None)
        summary[tid] = {"runs": len(items), "passes": passes, "pass_rate": round(passes / len(items), 3),
                        "median_wall_seconds": statistics.median(walls),
                        "mean_model_steps": round(statistics.mean(r["metrics"]["model_steps"] for r in items), 2),
                        "mean_tool_calls": round(statistics.mean(r["metrics"]["tool_calls"] for r in items), 2),
                        "mean_total_tokens": round(statistics.mean(tokens)) if tokens else None}
        s = summary[tid]
        reason = f"{first['check']}: {first['reason']}"[:70] if first else ""
        print(f"{tid:32} {passes:>3}/{len(items):<3} {s['median_wall_seconds']:>8.1f} {s['mean_model_steps']:>6} "
              f"{s['mean_tool_calls']:>6} {str(s['mean_total_tokens'] or '-'):>8}  {reason}", file=out)
    total = sum(r["passed"] for r in runs)
    print(f"\nOverall: {total}/{len(runs)} runs passed", file=out)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", help="Running Studio app, e.g. http://127.0.0.1:8000")
    parser.add_argument("--tasks-file", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--tasks", help="Comma-separated task IDs or categories to run (default: all)")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per task, 1-20, for pass rates")
    parser.add_argument("--provider", help="Expected provider label (recorded; the app's configured provider runs)")
    parser.add_argument("--model", help="Expected model label (recorded; the app's configured model runs)")
    parser.add_argument("--require-config-match", action="store_true",
                        help="Abort if --provider/--model differ from GET /api/config")
    parser.add_argument("--var", action="append", help="Task template variable KEY=VALUE")
    parser.add_argument("--header", action="append", help="Extra HTTP header 'Name: value' (e.g. Workbench auth)")
    parser.add_argument("--cookie", action="append", help="Extra cookie NAME=VALUE")
    parser.add_argument("--output", type=Path, help="Results directory")
    parser.add_argument("--self-test", "--dry-run", dest="self_test", action="store_true",
                        help="Validate tasks and evaluator against canned streams; no network")
    args = parser.parse_args(argv)

    if args.self_test:
        failures = self_test(args.tasks_file, args.fixtures, verbose=True)
        for failure in failures:
            print("FAIL", failure)
        print(f"Self-test: {'PASS' if not failures else f'{len(failures)} failure(s)'}")
        return int(bool(failures))
    if not args.base_url:
        parser.error("--base-url is required unless --self-test is used")
    if not 1 <= args.repeat <= 20:
        parser.error("--repeat must be 1-20")

    tasks = load_tasks(args.tasks_file, _kv(args.var, "="))
    problems = validate_tasks(tasks)
    if problems:
        parser.error("task file invalid: " + "; ".join(problems))
    if args.tasks:
        wanted = {t.strip() for t in args.tasks.split(",") if t.strip()}
        tasks = [t for t in tasks if t["id"] in wanted or t.get("category") in wanted]
        unknown = wanted - {t["id"] for t in tasks} - {t.get("category") for t in tasks}
        if unknown:
            parser.error(f"unknown tasks/categories: {sorted(unknown)}")

    client = ApiClient(args.base_url, _kv(args.header, ":"), _kv(args.cookie, "="))
    try:
        config = client.get_json("/api/config")
    except Exception as exc:
        print(f"Could not read {args.base_url}/api/config: {exc}", file=sys.stderr)
        return 2
    llm = config.get("llm") or {}
    app_config = {"provider": llm.get("provider"), "model": llm.get("model"), "api_key_set": llm.get("api_key_set")}
    mismatch = [k for k in ("provider", "model") if getattr(args, k) and getattr(args, k) != app_config[k]]
    if mismatch:
        message = f"Requested {', '.join(f'{k}={getattr(args, k)}' for k in mismatch)} but the app runs " \
                  f"{app_config['provider']}/{app_config['model']}. The app's configuration is what is evaluated."
        if args.require_config_match:
            print(message, file=sys.stderr)
            return 2
        print("WARNING:", message, file=sys.stderr)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    output = (args.output or ROOT / ".eval-results" / f"agent-live-{stamp}").resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"harness_version": HARNESS_VERSION, "started": stamp, "base_url": args.base_url,
              "requested": {"provider": args.provider, "model": args.model}, "app_config": app_config,
              "config_mismatch": mismatch, "tasks_file": str(args.tasks_file), "repeat": args.repeat,
              "limits": ["Tool arguments and tool result bodies are not exposed by the stream; counts and concept IDs "
                         "are scored from structured dashboard/plan fields when present, otherwise from reply text "
                         "(see each check's evidence)."],
              "runs": []}
    results_path = output / "results.json"
    print(f"Evaluating {app_config['provider']}/{app_config['model']} at {args.base_url}: "
          f"{len(tasks)} task(s) x {args.repeat}", flush=True)
    try:
        for iteration in range(1, args.repeat + 1):
            for task in tasks:
                passed, checks, turns, plans = run_task(client, task)
                metrics = turn_metrics(turns)
                report["runs"].append({"task": task["id"], "category": task.get("category"), "iteration": iteration,
                                       "passed": passed, "checks": checks, "metrics": metrics,
                                       "turns": [summarize_turn(t) for t in turns],
                                       "server_plans": [{k: p.get(k) for k in ("id", "status", "rows")} for p in plans]})
                first = next((c for c in checks if not c["ok"] and c["severity"] == "hard"), None)
                print(f"[{iteration}] {task['id']}: {'PASS' if passed else 'FAIL'} "
                      f"({metrics['wall_seconds']}s, {metrics['tool_calls']} tools)"
                      + (f" - {first['check']}: {first['reason']}" if first else ""), flush=True)
                results_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    finally:
        if report["runs"]:
            print()
            report["summary"] = print_summary(report["runs"])
        results_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(f"Results: {results_path}")
    return int(not all(r["passed"] for r in report["runs"]))


if __name__ == "__main__":
    raise SystemExit(main())
