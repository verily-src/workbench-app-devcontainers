// Loaded by the OpenCode web UI's page, before its own code (the event bridge puts this
// script tag in the page's head). The UI follows the server through a server-sent event
// stream (GET /global/event, or /event), which Workbench's proxy does not pass through
// until it ends; websockets it does carry. So a fetch of the event stream is answered
// from a websocket to the event bridge (/__event-ws?stream=<path>), which reads the stream
// from the server and relays its bytes. The path travels in the URL: the websocket carries
// nothing from the browser, so nothing can be lost on the way (Workbench's proxy has dropped
// a first message during its own tunnel set-up). Anything else goes to the real fetch.
//
// When the websocket ends, for any reason, the fetch's stream ends with an error, never
// cleanly: the UI's event client resubscribes after an error (3 s, then backing off) and
// treats a clean end as final, which left the page deaf until reloaded.
(function () {
  if (!window.WebSocket || !window.ReadableStream) return;
  var realFetch = window.fetch;
  var isEventPath = function (pathname) {
    return /\/(global\/)?event$/.test(pathname);
  };
  window.fetch = function (input, init) {
    var args = arguments;
    var request = typeof Request !== "undefined" && input instanceof Request ? input : null;
    var url;
    try {
      url = new URL(request ? request.url : String(input), location.href);
    } catch (e) {
      return realFetch.apply(this, args);
    }
    var method = ((init && init.method) || (request && request.method) || "GET").toUpperCase();
    if (method !== "GET" || url.origin !== location.origin || !isEventPath(url.pathname)) {
      return realFetch.apply(this, args);
    }
    var signal = (init && init.signal) || (request && request.signal) || null;
    if (signal && signal.aborted) {
      return Promise.reject(new DOMException("The event stream fetch was aborted", "AbortError"));
    }
    var wsUrl = new URL("/__event-ws", location.href);
    wsUrl.protocol = location.protocol === "https:" ? "wss:" : "ws:";
    wsUrl.searchParams.set("stream", url.pathname + url.search);
    return new Promise(function (resolve, reject) {
      var ws = new WebSocket(wsUrl.href);
      ws.binaryType = "arraybuffer";
      var opened = false;
      var controller = null;
      var finish = function (fn) {
        try {
          fn();
        } catch (e) {
          // the stream is already closed or errored
        }
      };
      var fail = function (reason) {
        if (!opened) {
          reject(new TypeError("event stream websocket " + reason));
          return;
        }
        finish(function () {
          controller.error(new TypeError("event stream websocket " + reason));
        });
      };
      var body = new ReadableStream({
        start: function (c) {
          controller = c;
        },
        cancel: function () {
          ws.close();
        },
      });
      ws.onopen = function () {
        opened = true;
        resolve(
          new Response(body, {
            status: 200,
            headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
          })
        );
      };
      ws.onmessage = function (event) {
        var chunk =
          typeof event.data === "string" ? new TextEncoder().encode(event.data) : new Uint8Array(event.data);
        finish(function () {
          controller.enqueue(chunk);
        });
      };
      ws.onerror = function () {
        fail("failed");
      };
      ws.onclose = function (event) {
        fail("closed (" + event.code + ")");
      };
      if (signal) {
        signal.addEventListener("abort", function () {
          ws.close();
        });
      }
    });
  };
})();
