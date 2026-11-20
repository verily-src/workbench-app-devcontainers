"""An OpenAI-compatible model server on vLLM's port that answers from Vertex AI in the workspace's
own project: with Gemini, or with a model the workspace serves on a Vertex AI endpoint of its own.

OpenCode in the sandbox keeps the address and API it has with vLLM (README.md). This server adds
the app's Google credential, which never enters the sandbox, and sends each chat request on:

    GET  /health, /v1/models        answered here: the model is VERTEX_MODEL
    POST /v1/chat/completions       sent to Vertex AI, streamed or not, with the model replaced

With VERTEX_ENDPOINT_URL set (an endpoint's OpenAI base, `.../endpoints/<id>/invoke/v1`, which
`proxy.py find-endpoint` prints), requests go to that endpoint as they are, but for the model name:
it runs vLLM, and the cohort designer calls it here with its usual provider. Otherwise they go to
Gemini's OpenAI-compatible endpoint, and the designer runs on its own Gemini provider instead.

Gemini returns a thought signature with the first tool call of each step and refuses the next turn
if the call comes back without it. Clients written for vLLM drop it, so this server keeps each
signature by tool call id and puts it back; a call it never saw (one from before a restart) gets
Google's documented placeholder, which Vertex accepts.

Settings: VERTEX_MODEL (required), VERTEX_ENDPOINT_URL, VERTEX_LOCATION (default global),
GOOGLE_CLOUD_PROJECT (default the VM's project), VLLM_PORT, VLLM_BIND_ADDRESS, VLLM_CONTEXT_LENGTH
(reported in /v1/models). find-endpoint reads VERTEX_ENDPOINT and VERTEX_ENDPOINT_LOCATION.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

METADATA = "http://metadata.google.internal/computeMetadata/v1/"
# Google's value for a call whose signature is not known: Vertex skips the check for it.
PLACEHOLDER = "skip_thought_signature_validator"
KEPT = 20000
# How long a reply may take: the endpoint's own limit (deploy-endpoint.sh sets 1800 s).
TIMEOUT = 1800
# The label deploy-endpoint.sh puts on the endpoint, and VERTEX_ENDPOINT's default.
ENDPOINT_LABEL = "ara-model"
# The largest request body taken: requests can carry images.
MAX_BODY = 64 * 1024 * 1024


def metadata(path: str, timeout: float = 3) -> str:
    request = urllib.request.Request(METADATA + path, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode()


class Tokens:
    """The VM's access token from the metadata server, or gcloud's off a VM, renewed before expiry."""

    def __init__(self):
        self._lock = threading.Lock()
        self._token, self._expires = "", 0.0

    def get(self) -> str:
        with self._lock:
            if time.time() < self._expires - 120:
                return self._token
            try:
                held = json.loads(metadata("instance/service-accounts/default/token"))
                self._token, self._expires = held["access_token"], time.time() + held["expires_in"]
            except (OSError, ValueError, KeyError):
                self._token = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True, timeout=60).strip()
                self._expires = time.time() + 600
            return self._token


class Signatures:
    """Thought signatures by tool call id, the most recent KEPT of them."""

    def __init__(self):
        self._lock = threading.Lock()
        self._held: OrderedDict[str, str] = OrderedDict()

    def keep(self, call_id, signature) -> None:
        if not call_id or not signature:
            return
        with self._lock:
            self._held[call_id] = signature
            self._held.move_to_end(call_id)
            while len(self._held) > KEPT:
                self._held.popitem(last=False)

    def get(self, call_id):
        with self._lock:
            return self._held.get(call_id)


def signature_of(call: dict):
    return ((call.get("extra_content") or {}).get("google") or {}).get("thought_signature")


def with_signature(call: dict, signature: str) -> dict:
    extra = dict(call.get("extra_content") or {})
    extra["google"] = {**(extra.get("google") or {}), "thought_signature": signature}
    return {**call, "extra_content": extra}


def invalid(body) -> str:
    """Why a request body cannot be sent on, or "" when its shape is one this server can handle:
    an object, whose messages are objects and whose tool calls are objects."""
    if not isinstance(body, dict):
        return "the request body must be a JSON object"
    messages = body.get("messages")
    if messages is None:
        return ""
    if not isinstance(messages, list) or not all(isinstance(message, dict) for message in messages):
        return "messages must be a list of objects"
    for message in messages:
        calls = message.get("tool_calls")
        if calls is not None and (not isinstance(calls, list) or not all(isinstance(call, dict) for call in calls)):
            return "tool_calls must be a list of objects"
    return ""


def prepare(body: dict, model: str, signatures: Signatures) -> dict:
    """The request as Vertex takes it: its model name, and each step's signature back in place."""
    messages = []
    for message in body.get("messages") or []:
        calls = message.get("tool_calls") if message.get("role") == "assistant" else None
        if calls:
            calls = [call if signature_of(call) or not signatures.get(call.get("id"))
                     else with_signature(call, signatures.get(call.get("id"))) for call in calls]
            if not any(signature_of(call) for call in calls):
                calls[0] = with_signature(calls[0], PLACEHOLDER)
            message = {**message, "tool_calls": calls}
        messages.append(message)
    return {**body, "model": model if "/" in model else f"google/{model}", "messages": messages}


def prepare_for_endpoint(body: dict, model: str) -> dict:
    """The request as the workspace's endpoint takes it: vLLM's own form, with its served name."""
    return {**body, "model": model}


def keep_from_reply(reply: dict, signatures: Signatures) -> None:
    for choice in reply.get("choices") or []:
        for call in (choice.get("message") or {}).get("tool_calls") or []:
            signatures.keep(call.get("id"), signature_of(call))


class StreamWatcher:
    """Reads a streamed reply's lines and keeps the signatures its tool calls carry, which may come
    in another chunk than the call's id."""

    def __init__(self, signatures: Signatures):
        self.signatures = signatures
        self.calls: dict[tuple[int, int], dict] = {}

    def line(self, raw: bytes) -> None:
        text = raw.decode("utf-8", "replace").strip()
        if not text.startswith("data:") or text == "data: [DONE]":
            return
        try:
            chunk = json.loads(text[5:])
        except ValueError:
            return
        for choice in chunk.get("choices") or []:
            for call in (choice.get("delta") or {}).get("tool_calls") or []:
                seen = self.calls.setdefault((choice.get("index", 0), call.get("index", 0)), {})
                seen["id"] = call.get("id") or seen.get("id")
                seen["signature"] = signature_of(call) or seen.get("signature")
                self.signatures.keep(seen["id"], seen["signature"])


class Handler(BaseHTTPRequestHandler):
    server_version = "vertex-model"
    # Set by serve().
    model = ""
    context = 0
    upstream = ""
    # "gemini" (Gemini's OpenAI-compatible endpoint) or "endpoint" (the workspace's own endpoint).
    mode = "gemini"
    tokens: Tokens
    signatures: Signatures

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), fmt % args))

    def answer(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            return self.answer(200, {"status": "ok"})
        if self.path.rstrip("/") in ("/v1/models", "/models"):
            return self.answer(200, {"object": "list", "data": [
                {"id": self.model, "object": "model", "owned_by": "vertex-ai", "max_model_len": self.context}]})
        self.answer(404, {"error": {"message": f"no {self.path} here"}})

    def do_POST(self):
        if self.path.rstrip("/") not in ("/v1/chat/completions", "/chat/completions"):
            return self.answer(404, {"error": {"message": f"only chat completions are served, not {self.path}"}})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            # The body is not read, so the connection cannot be reused.
            self.close_connection = True
            if length < 0:
                return self.answer(400, {"error": {"message": "Content-Length must be a non-negative number",
                                                   "type": "invalid_request_error"}})
            return self.answer(413, {"error": {"message": f"the request is over {MAX_BODY} bytes",
                                               "type": "invalid_request_error"}})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.answer(400, {"error": {"message": "the request is not JSON"}})
        problem = invalid(body)
        if problem:
            return self.answer(400, {"error": {"message": problem, "type": "invalid_request_error"}})
        try:
            token = self.tokens.get()
        except (OSError, subprocess.SubprocessError) as err:
            return self.answer(502, {"error": {"message": f"no Google credential for Vertex AI: {err}"}})
        gemini = self.mode == "gemini"
        sent = prepare(body, self.model, self.signatures) if gemini else prepare_for_endpoint(body, self.model)
        request = urllib.request.Request(
            self.upstream, json.dumps(sent).encode(),
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=TIMEOUT)
        except urllib.error.HTTPError as err:
            data = err.read()
            self.send_response(err.code)
            self.send_header("Content-Type", err.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        except OSError as err:
            return self.answer(502, {"error": {"message": f"Vertex AI did not answer: {err}"}})
        with response:
            if not body.get("stream"):
                data = response.read()
                try:
                    if gemini:
                        keep_from_reply(json.loads(data), self.signatures)
                except ValueError:
                    pass
                self.send_response(response.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            # Streamed: each line goes on as it comes; the connection closes at the end.
            self.send_response(response.status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            watcher = StreamWatcher(self.signatures) if gemini else None
            for raw in response:
                if watcher:
                    watcher.line(raw)
                self.wfile.write(raw)
                self.wfile.flush()


def upstream_url(project: str, location: str) -> str:
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    return f"https://{host}/v1/projects/{project}/locations/{location}/endpoints/openapi/chat/completions"


def endpoint_chat_url(base: str) -> str:
    return base.rstrip("/") + "/chat/completions"


def api_get(url: str, tokens, timeout: float = 30):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {tokens.get()}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def endpoint_base(endpoint: dict) -> str:
    """An endpoint's OpenAI base URL, on its dedicated DNS name: `<name>` is
    projects/<number>/locations/<location>/endpoints/<id>, as Vertex AI returns it."""
    return f"https://{endpoint['dedicatedEndpointDns']}/v1/{endpoint['name']}/invoke/v1"


def flag(args: list, name: str):
    """A command-line flag's value from a container's args, as `--name value` or `--name=value`."""
    for i, arg in enumerate(args):
        if arg == name and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(name + "="):
            return arg[len(name) + 1:]
    return None


def served(model: dict) -> tuple:
    """(served model name, context) of a vLLM model uploaded to Vertex AI, from its container's
    args: `vllm serve <model> ... [--served-model-name n] [--max-model-len n]`. The endpoint's invoke
    route forwards only POST, so vLLM's GET /v1/models can't be asked."""
    args = (model.get("containerSpec") or {}).get("args") or []
    positional = args[0] if args and not args[0].startswith("-") else None
    name = flag(args, "--served-model-name") or flag(args, "--model") or positional
    try:
        context = int(flag(args, "--max-model-len") or 0)
    except ValueError:
        context = 0
    return name, context


def find_endpoint(project: str, location: str, selector: str, tokens, get=api_get):
    """The workspace's endpoint and what it serves: {"url", "model", "context", "endpoint"}, or
    raises LookupError saying why there is none. selector is "auto" (the newest dedicated endpoint
    labelled ara-model, with a model deployed), "<label value>" (the same, for that value), or an
    endpoint's numeric ID."""
    host = f"https://{location}-aiplatform.googleapis.com/v1"
    api = f"{host}/projects/{project}/locations/{location}/endpoints"
    if selector.isdigit():
        found = [get(f"{api}/{selector}", tokens)]
    else:
        value = "" if selector == "auto" else selector
        query = f"labels.{ENDPOINT_LABEL}={value}" if value else f"labels.{ENDPOINT_LABEL}:*"
        found = get(f"{api}?{urllib.parse.urlencode({'filter': query})}", tokens).get("endpoints") or []
    ready = [e for e in found if e.get("dedicatedEndpointDns") and e.get("deployedModels")]
    if not ready:
        why = "none is dedicated with a model deployed" if found else "there is none"
        raise LookupError(f"no Vertex AI endpoint for the assistant in {project}/{location} "
                          f"(VERTEX_ENDPOINT={selector}): {why}")
    endpoint = max(ready, key=lambda e: e.get("createTime", ""))
    deployed = endpoint["deployedModels"][0].get("model", "")
    try:
        name, context = served(get(f"{host}/{deployed}", tokens))
    except (OSError, ValueError) as err:
        raise LookupError(f"could not read the model {deployed} on {endpoint['name']}: {err}") from err
    if not name:
        raise LookupError(f"the model {deployed} on {endpoint['name']} names no served model in its args")
    return {"url": endpoint_base(endpoint), "model": name, "context": context, "endpoint": endpoint["name"]}


def serve(model: str, upstream: str, bind: str, port: int, context: int, tokens=None,
          mode: str = "gemini") -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {
        "model": model, "context": context, "upstream": upstream, "mode": mode,
        "tokens": tokens or Tokens(), "signatures": Signatures()})
    server = ThreadingHTTPServer((bind, port), handler)
    server.daemon_threads = True
    return server


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or metadata("project/project-id")
    if argv[:1] == ["find-endpoint"]:
        # For start-services.sh: one line of JSON, or the reason there is none and exit 1.
        selector = os.environ.get("VERTEX_ENDPOINT", "auto").strip() or "auto"
        location = os.environ.get("VERTEX_ENDPOINT_LOCATION", "us-central1").strip() or "us-central1"
        try:
            print(json.dumps(find_endpoint(project, location, selector, Tokens())))
        except (LookupError, OSError, ValueError, subprocess.SubprocessError) as err:
            sys.exit(f"find-endpoint: {err}")
        return
    model = os.environ.get("VERTEX_MODEL", "").strip()
    if not model:
        sys.exit("VERTEX_MODEL names the model to serve (start-services.sh sets it)")
    endpoint = os.environ.get("VERTEX_ENDPOINT_URL", "").strip()
    location = os.environ.get("VERTEX_LOCATION", "global")
    port = int(os.environ.get("VLLM_PORT", "8000"))
    bind = os.environ.get("VLLM_BIND_ADDRESS", "127.0.0.1")
    context = int(os.environ.get("VLLM_CONTEXT_LENGTH", "262144"))
    if endpoint:
        server = serve(model, endpoint_chat_url(endpoint), bind, port, context, mode="endpoint")
        where = endpoint
    else:
        server = serve(model, upstream_url(project, location), bind, port, context)
        where = f"Gemini, {project}, {location}"
    print(f"Serving {model} from Vertex AI ({where}) on {bind}:{port}", file=sys.stderr, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
