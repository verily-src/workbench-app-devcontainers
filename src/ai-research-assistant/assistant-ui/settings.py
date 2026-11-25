"""What the assistant UI's server decides without a web framework (server.py): which OpenCode
calls the page may make, the chips file, the page's settings, and the event stream's framing.
Only the standard library and PyYAML, so the tests run without the server's packages."""
import json
import os
import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DEMO_FILE = Path(os.environ.get("ASSISTANT_DEMO", HERE / "demo.yaml"))
INPUT_MODES = ("free", "chips")
OPEN = "open"  # ASSISTANT_ACCESS=open turns the access gate off; the app sets a file path.

# The OpenCode calls the page makes. The server offers far more (shells, files, config
# changes); none of it is reachable through here.
_ID = r"[A-Za-z0-9_]+"
ALLOWED = [(method, re.compile(pattern)) for method, pattern in (
    ("GET", r"global/health"),
    ("GET", r"config"),
    ("GET", r"mcp"),
    ("GET", r"session"),
    ("POST", r"session"),
    ("GET", r"session/status"),
    ("GET", rf"session/{_ID}"),
    ("GET", rf"session/{_ID}/message"),
    ("POST", rf"session/{_ID}/prompt_async"),
    ("POST", rf"session/{_ID}/abort"),
    ("GET", r"permission"),
    ("POST", rf"permission/{_ID}/reply"),
    ("GET", r"question"),
    ("POST", rf"question/{_ID}/reply"),
    ("POST", rf"question/{_ID}/reject"),
)]


def allowed(method, path):
    """Whether the page may make this OpenCode call."""
    return any(method == m and p.fullmatch(path) for m, p in ALLOWED)


# The replies the page sends to an approval request: allow this call once, or refuse it.
# OpenCode also accepts "always", which stops asking for that tool; the page never sends it.
PERMISSION_REPLIES = ("once", "reject")
_PERMISSION_REPLY = re.compile(rf"permission/{_ID}/reply")


def body_refusal(method, path, body):
    """Why an allowed call's body is refused, or None. Only the permission reply is checked."""
    if method == "POST" and _PERMISSION_REPLY.fullmatch(path):
        try:
            reply = json.loads(body).get("reply")
        except (ValueError, AttributeError):
            reply = None
        if reply not in PERMISSION_REPLIES:
            return f"The reply must be one of {', '.join(PERMISSION_REPLIES)}."
    return None


def load_demo(path=None):
    """The chips file, checked: a list of starters and of next steps, each a label and a prompt.
    A chip's optional source is sent with its prompt as context the agent reads and the page does
    not show (an approved text for the agent to answer from)."""
    path = Path(path or DEMO_FILE)
    data = yaml.safe_load(path.read_text()) or {}
    demo = {}
    for group in ("starters", "next_steps"):
        chips = data.get(group) or []
        for chip in chips:
            if not isinstance(chip, dict) or not chip.get("label") or not chip.get("prompt"):
                raise ValueError(f"{path}: every chip in {group} needs a label and a prompt")
        demo[group] = [{"label": str(c["label"]), "prompt": str(c["prompt"]).strip(),
                        "hint": str(c.get("hint", "")), "feature": str(c.get("feature", "")),
                        "source": str(c.get("source", "")).strip()} for c in chips]
    demo["about"] = [str(line) for line in data.get("about") or []]
    return demo


def access_view(path):
    """Whether the page lets the person in, from the access state the app writes (the ai-policy
    feature's access.py): {"state", "title", "message", "features"}. state is open (path is the
    word "open", for local development), ok, checking, error, denied or no_model; features is
    None when open. An unset or empty path is checking: the gate is turned off only by name."""
    if path == OPEN:
        return {"state": "open", "title": "", "message": "", "features": None}
    try:
        if not path:
            raise ValueError("no access state configured")
        state = json.loads(Path(path).read_text())
        if not isinstance(state, dict):
            raise ValueError("not a mapping")
    except (OSError, ValueError):
        return {"state": "checking", "title": "Checking your access",
                "message": "The app is checking your access to the Research Assistant.", "features": {}}
    features = {k: v is True for k, v in (state.get("features") or {}).items()}
    if state.get("status") != "ok":
        return {"state": "error", "title": str(state.get("title") or "Checking your access"),
                "message": str(state.get("message") or "We couldn't verify your access. Retrying."), "features": {}}
    if not state.get("tier"):
        return {"state": "denied", "title": "Thanks for Your Interest in the Research Assistant",
                "message": str(state.get("message") or ""), "features": {}}
    model = state.get("model")
    if isinstance(model, dict) and not model.get("backend"):
        return {"state": "no_model", "title": "The Research Assistant is unavailable",
                "message": str(model.get("message") or ""), "features": features}
    return {"state": "ok", "title": "", "message": "", "features": features}


def page_config(env=None):
    """What /api/config answers. Chips that name a feature (feature: in the chips file) appear
    only when the access state has that feature on."""
    env = os.environ if env is None else env
    mode = env.get("ASSISTANT_INPUT", "free")
    if mode not in INPUT_MODES:
        raise ValueError(f"ASSISTANT_INPUT is {mode!r}; expected one of {INPUT_MODES}")
    demo = load_demo(env.get("ASSISTANT_DEMO"))
    access = access_view(env.get("ASSISTANT_ACCESS"))
    on = access.pop("features")
    if on is not None:
        for group in ("starters", "next_steps"):
            demo[group] = [c for c in demo[group] if not c["feature"] or on.get(c["feature"])]
    return {"title": env.get("ASSISTANT_TITLE", "Research Assistant"),
            "input": mode, "access": access, **demo}


def sse_events(lines):
    """The data of each server-sent event in an iterable of lines, as text."""
    data = []
    for line in lines:
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            yield "\n".join(data)
            data = []
