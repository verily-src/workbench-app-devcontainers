#!/usr/bin/env python3
"""The event bridge behind the app's front door (caddy/Caddyfile; the app's README, "Web UI").

The OpenCode web UI follows its server through a server-sent event stream, which Workbench's
proxy delivers only once it ends, so the page never updates. Websockets the proxy does carry.
This process, on the app's loopback, does two things for the front door:

- Pages (requests that accept text/html) are fetched from the server and returned with one
  script tag in their head, event-shim.js, which answers the UI's fetch of the event stream
  from a websocket to /__event-ws instead.
- /__event-ws?stream=<path>: the bridge opens that stream on the server and relays its bytes
  as binary websocket messages until either side closes. Only the event stream paths are
  accepted. The path is in the URL so that the websocket carries nothing from the browser:
  Workbench's proxy has lost a first message while setting up its own tunnel, which left the
  page without events.

Configuration: UPSTREAM (host:port of the server behind the broker's forward), LISTEN (port).
"""

import asyncio
import http.client
import logging
import os
import re
import sys
from urllib.parse import parse_qs, urlsplit
from concurrent.futures import ThreadPoolExecutor

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

UPSTREAM = os.environ.get("UPSTREAM", "sandbox-broker:4096")
LISTEN = int(os.environ.get("LISTEN", "9001"))
HERE = os.path.dirname(os.path.abspath(__file__))
EVENT_PATH = re.compile(r"^/(global/)?event(\?[^\s]*)?$")
SHIM_PATH = "/__event-shim.js"
WS_PATH = "/__event-ws"
SHIM_TAG = b'<script src="/__event-shim.js"></script>'
STARTING = (b"OpenCode is starting. The sandbox and its web UI come up with the app; if this stays, "
            b"open /ide/ and run: agent-sandbox web\n")
# Hop-by-hop and length headers are the bridge's own; the body may have changed.
DROPPED_HEADERS = {"content-length", "transfer-encoding", "connection", "content-encoding", "keep-alive"}

log = logging.getLogger("event-bridge")

with open(os.path.join(HERE, "event-shim.js"), "rb") as handle:
    SHIM = handle.read()


def upstream_request(path, headers):
    """Opens one request on the server; returns (connection, response). Blocking."""
    host, _, port = UPSTREAM.partition(":")
    connection = http.client.HTTPConnection(host, int(port or 80), timeout=30)
    connection.request("GET", path, headers={"Host": UPSTREAM, **headers})
    return connection, connection.getresponse()


def plain(status, reason, body, content_type="text/plain; charset=utf-8"):
    return Response(status, reason, Headers([("Content-Type", content_type),
                                             ("Cache-Control", "no-cache"),
                                             ("Content-Length", str(len(body)))]), body)


async def process_request(connection, request):
    """Plain HTTP through the bridge: the shim, and pages with the shim in their head."""
    path = request.path
    if path.split("?", 1)[0] == WS_PATH:
        return None  # the websocket handshake proceeds
    if path.split("?", 1)[0] == SHIM_PATH:
        return plain(200, "OK", SHIM, "text/javascript; charset=utf-8")
    accept = request.headers.get("Accept", "text/html")
    try:
        upstream, response = await asyncio.to_thread(upstream_request, path, {"Accept": accept})
        body = await asyncio.to_thread(response.read)
        upstream.close()
    except OSError as error:
        log.warning("page %s: server unreachable: %s", path, error)
        return plain(503, "Service Unavailable", STARTING)
    content_type = response.getheader("Content-Type", "")
    if response.status == 200 and content_type.startswith("text/html") and b"<head>" in body:
        body = body.replace(b"<head>", b"<head>" + SHIM_TAG, 1)
    headers = Headers([(k, v) for k, v in response.getheaders() if k.lower() not in DROPPED_HEADERS])
    headers["Content-Length"] = str(len(body))
    return Response(response.status, response.reason, headers, body)


def stream_path(request_path):
    """The event stream path named by the websocket's URL (?stream=...), or None."""
    streams = parse_qs(urlsplit(request_path).query).get("stream", [])
    if len(streams) == 1 and EVENT_PATH.match(streams[0]):
        return streams[0]
    return None


async def bridge(websocket):
    """One websocket: the event stream named in its URL, relayed as bytes."""
    path = stream_path(websocket.request.path)
    if path is None:
        log.warning("websocket %s: not an event stream", websocket.request.path)
        await websocket.close(1008, "not an event stream")
        return
    try:
        upstream, response = await asyncio.to_thread(
            upstream_request, path, {"Accept": "text/event-stream", "Cache-Control": "no-cache"})
    except OSError as error:
        log.warning("stream %s: server unreachable: %s", path, error)
        await websocket.close(1011, "server unavailable")
        return
    if response.status != 200:
        upstream.close()
        await websocket.close(1011, f"server answered {response.status}")
        return
    log.info("stream %s opened for %s", path, websocket.remote_address)
    try:
        while True:
            chunk = await asyncio.to_thread(response.read1, 65536)
            if not chunk:
                break
            await websocket.send(chunk)
    except ConnectionClosed:
        pass
    except OSError as error:
        log.warning("stream %s: %s", path, error)
    finally:
        upstream.close()
        log.info("stream %s closed", path)
    await websocket.close()


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stdout)
    # Each open stream parks one thread in a blocking read; the default pool is small.
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=128))
    async with serve(bridge, "127.0.0.1", LISTEN, process_request=process_request,
                     ping_interval=20, ping_timeout=20, max_size=None, compression=None):
        log.info("event bridge on 127.0.0.1:%d for %s", LISTEN, UPSTREAM)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
