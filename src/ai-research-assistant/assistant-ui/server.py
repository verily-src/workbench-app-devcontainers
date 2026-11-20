#!/usr/bin/env python3
"""The NVIDIA AI Research Assistant's web UI: one page over an OpenCode server (README.md).

This process serves the page and stands between it and OpenCode:

- /            the page and its files (static/).
- /api/config  the chips and the page's settings (demo.yaml and the environment).
- /oc/<path>   OpenCode's HTTP API, only the calls the page makes (ALLOWED below).
- /events      a websocket that relays OpenCode's event stream, one event per message.
               Workbench's proxy delivers a server-sent event stream only once it ends, and it
               does carry websockets. The browser sends nothing on it: the proxy has lost a
               first message while setting up its own tunnel.

Configuration: OPENCODE_URL (the OpenCode server), ASSISTANT_DEMO (the chips file),
ASSISTANT_INPUT ("free", or "chips" to hide the text box), ASSISTANT_TITLE, ASSISTANT_ACCESS (the
access state: /oc and /events answer only while it lets the person in; the word "open" turns the
gate off, for local development), PORT.
"""
import asyncio
import http.cookiejar
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from settings import HERE, access_view, allowed, page_config, sse_events, body_refusal

OPENCODE_URL = os.environ.get("OPENCODE_URL", "http://127.0.0.1:4096").rstrip("/")

log = logging.getLogger("assistant-ui")
LET_IN = ("ok", "open")


def let_in():
    """Whether the access state lets the person use the assistant: the page hides it otherwise,
    and these routes refuse it, read again on every call."""
    return access_view(os.environ.get("ASSISTANT_ACCESS"))["state"] in LET_IN


def cross_site(headers):
    """Whether the browser says the request was made by a page on another site. The browser sets
    Sec-Fetch-Site itself and a page cannot change it, and it does not depend on the Host header,
    which Caddy and Workbench's proxy may rewrite, so Origin cannot be compared with Host here.
    A client that sends no such header (curl, an older browser) is not refused."""
    return headers.get("sec-fetch-site", "").lower() == "cross-site"

# Nothing the page shows may make the browser load from another origin, whatever the markdown
# sanitizer lets through. The page has no inline script or style (styles are set through the
# CSSOM), so script-src and style-src need no 'unsafe-inline'. frame-ancestors is left unset:
# Workbench may show the page in a frame.
CSP = ("default-src 'self'; img-src 'self' data:; media-src 'none'; object-src 'none'; "
       "frame-src 'none'; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response


def new_client():
    """The one client for OpenCode. It keeps no cookies: a jar would replay a cookie OpenCode set
    for one person on the requests of everyone else who uses the page."""
    jar = http.cookiejar.CookieJar(policy=http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
    return httpx.AsyncClient(base_url=OPENCODE_URL, timeout=httpx.Timeout(60, read=None), cookies=jar)


@asynccontextmanager
async def lifespan(app):
    page_config()  # A bad chips file stops the start, not the first page load.
    app.state.client = new_client()
    yield
    await app.state.client.aclose()


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


app.add_middleware(SecurityHeaders)


@app.get("/")
async def index():
    return FileResponse(HERE / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/api/config")
async def config():
    return page_config()


@app.api_route("/oc/{path:path}", methods=["GET", "POST"])
async def opencode(path: str, request: Request):
    if cross_site(request.headers):
        return JSONResponse({"error": "Requests from another site are refused."}, status_code=403)
    if not let_in():
        return JSONResponse({"error": "The assistant is not available to you."}, status_code=403)
    if not allowed(request.method, path):
        return JSONResponse({"error": f"{request.method} /{path} is not offered"}, status_code=404)
    body = await request.body()
    if body and request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        # Another site can send text/plain without a preflight; only the page sends JSON.
        return JSONResponse({"error": "The body must be application/json."}, status_code=415)
    refusal = body_refusal(request.method, path, body)
    if refusal:
        return JSONResponse({"error": refusal}, status_code=400)
    headers = {"Content-Type": "application/json"} if body else {}
    try:
        # The page sends no query string on these calls, so none is passed on.
        upstream = await app.state.client.request(
            request.method, "/" + path, content=body, headers=headers, timeout=60)
    except httpx.HTTPError as error:
        return JSONResponse({"error": f"The assistant is not reachable yet ({type(error).__name__})."},
                            status_code=503)
    # Only JSON and the event stream are passed on as the upstream types them; with nosniff,
    # any other type cannot make the browser treat the answer as a page on this origin.
    kind = upstream.headers.get("content-type", "application/json")
    if kind.split(";")[0].strip().lower() not in ("application/json", "text/event-stream"):
        kind = "application/json"
    # no-store: neither the browser nor Workbench's proxy may answer a later read from a copy.
    return Response(upstream.content, status_code=upstream.status_code,
                    media_type=kind,
                    headers={"Cache-Control": "no-store"})


@app.websocket("/events")
async def events(ws: WebSocket):
    if cross_site(ws.headers) or not let_in():
        await ws.close(code=1008)
        return
    await ws.accept()

    async def relay():
        async with app.state.client.stream("GET", "/event") as upstream:
            upstream.raise_for_status()
            pending = []
            async for line in upstream.aiter_lines():
                pending.append(line)
                if not line:
                    for event in sse_events(pending):
                        await ws.send_text(event)
                    pending = []

    async def until_closed():
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass

    tasks = [asyncio.create_task(relay()), asyncio.create_task(until_closed())]
    done, rest = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in rest:
        task.cancel()
    for task in done:
        if task.exception() and not isinstance(task.exception(), WebSocketDisconnect):
            log.warning("event stream ended: %r", task.exception())
    # The page reconnects and reads the session again; a close code says this end was not clean.
    try:
        await ws.close(code=1011)
    except RuntimeError:
        pass


app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "9002")))
