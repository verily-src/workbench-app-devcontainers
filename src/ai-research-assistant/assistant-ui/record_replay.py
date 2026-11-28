#!/usr/bin/env python3
"""Record finished sessions as the page's backup replays (README.md, "Recorded runs").

Reads each session's messages from OpenCode, cuts them into steps (a person's message and the
assistant's answer up to the next one) and writes them as one JSON file the chips file names
under `replays:`. Run it in the UI container, where OPENCODE_URL reaches OpenCode:

    python3 record_replay.py --out /tmp/replays.json ses_A ses_B
    python3 record_replay.py --out /tmp/replays.json --merge /tmp/replays.json ses_C
    python3 record_replay.py --out /tmp/replays.json --chips examples/ehr-genomics-chips.yaml ses_A

With --chips, only steps whose prompt is one of that file's chips are kept.

A step is found again by its prompt, whitespace aside, so a chip replays the step whose prompt
is the chip's. Where two sessions (or the merged file and a session) have the same prompt, the
later one is kept. Only what the page draws is kept: roles, times, text and reasoning, and each
tool call's name, status, input, output, error and times. Synthetic parts (a chip's source)
are dropped.

Standard library only.
"""
import argparse
import json
import os
import sys
import urllib.request

VERSION = 1


def normalize(text):
    """A prompt as steps are matched on: whitespace runs as one space, no ends (the page does the same)."""
    return " ".join(str(text or "").split())


def _time(t):
    t = t or {}
    return {k: t[k] for k in ("created", "start", "end") if isinstance(t.get(k), (int, float))}


def trim_part(part):
    """The part as the page draws it, or None for a part it does not draw."""
    kind = part.get("type")
    if kind in ("text", "reasoning"):
        if part.get("synthetic") or not str(part.get("text") or "").strip():
            return None
        return {"id": part.get("id"), "type": kind, "text": part.get("text")}
    if kind == "tool":
        s = part.get("state") or {}
        state = {k: s[k] for k in ("status", "input", "output", "error") if k in s}
        if s.get("time"):
            state["time"] = _time(s["time"])
        return {"id": part.get("id"), "type": "tool", "tool": part.get("tool"), "callID": part.get("callID"),
                "state": state}
    return None


def trim_message(item):
    info = item.get("info") or {}
    out = {"id": info.get("id"), "role": info.get("role", "assistant"), "time": _time(info.get("time"))}
    if info.get("error"):
        out["error"] = info["error"]
    parts = [p for p in (trim_part(p) for p in item.get("parts") or []) if p]
    return {"info": out, "parts": parts}


def user_text(item):
    return "\n".join(p.get("text") or "" for p in item.get("parts") or []
                     if p.get("type") == "text" and not p.get("synthetic")).strip()


def steps_of(messages):
    """A session's messages (OpenCode's session/<id>/message) as steps: {prompt, messages}."""
    ordered = sorted(messages, key=lambda m: ((m.get("info") or {}).get("time") or {}).get("created") or 0)
    steps = []
    for item in ordered:
        role = (item.get("info") or {}).get("role")
        if role == "user":
            text = user_text(item)
            if text:
                steps.append({"prompt": normalize(text), "messages": [trim_message(item)]})
            continue
        if steps:
            steps[-1]["messages"].append(trim_message(item))
    return steps


def merge(*groups):
    """Steps of several sources, one per prompt: a later source's step replaces an earlier one's,
    in the earlier one's place."""
    kept = {}
    for steps in groups:
        for step in steps:
            kept[step["prompt"]] = step
    return {"version": VERSION, "steps": list(kept.values())}


def chip_prompts(path):
    """The prompts of a chips file's starters and next steps, as steps are matched."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import settings
    demo = settings.load_demo(path)
    return {normalize(c["prompt"]) for group in ("starters", "next_steps") for c in demo[group]}


def only_chips(steps, prompts):
    """The steps whose prompt is a chip's, so test prompts and older wordings are not kept."""
    return [s for s in steps if s["prompt"] in prompts]


def describe(step):
    tools = [p for m in step["messages"] for p in m["parts"] if p["type"] == "tool"]
    failed = sum(1 for p in tools if p["state"].get("status") == "error")
    times = [m["info"]["time"].get("created") for m in step["messages"] if m["info"]["time"].get("created")]
    seconds = (max(times) - min(times)) / 1000 if len(times) > 1 else 0
    return f"{len(tools)} tool calls, {failed} failed, ~{seconds:.0f} s: {step['prompt'][:70]}"


def fetch(base, sid):
    with urllib.request.urlopen(f"{base.rstrip('/')}/session/{sid}/message", timeout=60) as r:
        return json.load(r)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("sessions", nargs="+", help="OpenCode session ids, oldest first (a later one wins)")
    p.add_argument("--out", required=True, help="the JSON file to write")
    p.add_argument("--merge", help="a replays file whose steps are kept unless a session replaces them")
    p.add_argument("--chips", help="a chips file: keep only the steps whose prompt is one of its chips'")
    p.add_argument("--base", default=os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096"),
                   help="OpenCode's URL (default: OPENCODE_URL)")
    a = p.parse_args(argv)
    groups = []
    if a.merge and os.path.exists(a.merge):
        with open(a.merge) as f:
            groups.append(json.load(f).get("steps") or [])
    for sid in a.sessions:
        steps = steps_of(fetch(a.base, sid))
        print(f"{sid}: {len(steps)} steps", file=sys.stderr)
        for step in steps:
            print("  " + describe(step), file=sys.stderr)
        groups.append(steps)
    data = merge(*groups)
    if a.chips:
        data["steps"] = only_chips(data["steps"], chip_prompts(a.chips))
    with open(a.out, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    print(f"wrote {len(data['steps'])} steps to {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
