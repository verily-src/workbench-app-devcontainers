"""Expose client disconnects to dashboard query handlers.

Starlette's BaseHTTPMiddleware (used by the app's http middlewares) hides
`http.disconnect` from `Request.is_disconnected()`. This pure ASGI layer,
installed outermost, reads the request body itself, replays it to the app,
and watches the real connection; the endpoint reads
`request.state.disconnected` (an asyncio.Event).
"""
import asyncio
import re

_WATCHED = re.compile(r"/api/datasets/[^/]+/query")
MAX_BODY = 1024 * 1024


class DisconnectWatch:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope.get("method") != "POST"
                or not _WATCHED.fullmatch(scope.get("path", ""))):
            await self.app(scope, receive, send)
            return
        body, more = b"", True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > MAX_BODY:
                break                       # let the app reject it normally
        disconnected = asyncio.Event()
        scope.setdefault("state", {})["disconnected"] = disconnected
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": more}
            if more:
                return await receive()
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def watch():
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    disconnected.set()
                    return

        watcher = asyncio.create_task(watch()) if not more else None
        try:
            await self.app(scope, replay, send)
        finally:
            if watcher:
                watcher.cancel()
