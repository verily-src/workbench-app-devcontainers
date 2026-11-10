"""The front door: Workbench's proxy reaches the first published port, which Caddy owns."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[2] / "src" / "ai-research-assistant"
FEATURES = Path(__file__).resolve().parents[2] / "features" / "src"


class FrontDoorTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())
        self.caddyfile = (APP / "caddy" / "Caddyfile").read_text()

    def test_caddy_owns_the_first_published_port_of_the_app(self):
        first = str(self.compose["services"]["app"]["ports"][0])
        self.assertEqual(first, "8080:8080")
        self.assertIn(":8080 {", self.caddyfile)
        web = self.compose["services"]["opencode-web"]
        self.assertEqual(web["network_mode"], "service:app")
        self.assertIn("./caddy:/etc/caddy:ro", web["volumes"])
        # code-server's own port is reached only through Caddy.
        self.assertFalse([p for p in self.compose["services"]["app"]["ports"] if "8443" in str(p)])

    def test_port_guard_guards_the_published_port(self):
        guard = self.compose["services"]["port-guard"]["environment"]["GUARDED_PORT"]
        self.assertEqual(str(guard), "8080")

    def test_caddy_proxies_to_the_harness_web_port_on_the_broker(self):
        harness = json.loads(subprocess.run(
            [sys.executable, str(FEATURES / "agent-sandbox" / "harness.py"), str(FEATURES / "opencode-harness" / "harnesses" / "opencode.yaml")],
            capture_output=True, text=True, check=True).stdout)
        port = harness["serve"]["port"]
        self.assertIn(f"reverse_proxy sandbox-broker:{port}", self.caddyfile)
        self.assertIn("reverse_proxy 127.0.0.1:8443", self.caddyfile)
        self.assertIn("handle_path /ide/*", self.caddyfile)
        # The server listens on the sandbox's loopback, on that port.
        self.assertEqual(harness["serve"]["command"][-4:], ["--hostname", "127.0.0.1", "--port", str(port)])

    def test_broker_allows_the_web_command(self):
        allow = re.search(r"^\s*(run\|[^)]*)\)", (FEATURES / "agent-sandbox" / "broker" / "command.sh").read_text(), re.M).group(1)
        self.assertIn("web", allow.split("|"))

    def test_opening_the_app_lands_on_a_new_session_in_the_harness_working_directory(self):
        """OpenCode's project page for `workdir`, base64url-encoded, instead of its project picker."""
        import base64
        workdir = yaml.safe_load((FEATURES / "opencode-harness" / "harnesses" / "opencode.yaml").read_text())["workdir"]
        route = base64.urlsafe_b64encode(workdir.encode()).decode().rstrip("=")
        self.assertRegex(self.caddyfile, r"@home \{\s*path /\s*header Accept \*text/html\*\s*\}")
        self.assertIn(f"redir @home /{route} 302", self.caddyfile)
        self.assertNotRegex(self.caddyfile, r"^\s*redir .*301", "a 301 outlives an upgrade that changes the route")

    def test_the_event_bridge_runs_beside_caddy_and_gets_the_pages_and_the_websocket(self):
        """The web UI's event stream goes over a websocket (Workbench's proxy does not stream)."""
        bridge = self.compose["services"]["opencode-web-events"]
        self.assertEqual(bridge["network_mode"], "service:app")
        self.assertEqual(bridge["build"]["dockerfile"], "event-bridge/Dockerfile")
        self.assertEqual(bridge["environment"]["UPSTREAM"], "sandbox-broker:4096")
        self.assertIn("reverse_proxy /__event-ws 127.0.0.1:9001", self.caddyfile)
        self.assertIn("reverse_proxy /__event-shim.js 127.0.0.1:9001", self.caddyfile)
        self.assertIn("reverse_proxy @page 127.0.0.1:9001", self.caddyfile)
        self.assertIn("@page header Accept *text/html*", self.caddyfile)
        shim = (APP / "event-bridge" / "event-shim.js").read_text()
        self.assertIn('"/__event-ws"', shim)
        bridge_py = (APP / "event-bridge" / "bridge.py").read_text()
        self.assertIn('WS_PATH = "/__event-ws"', bridge_py)
        self.assertIn('SHIM_PATH = "/__event-shim.js"', bridge_py)

    def test_the_websocket_names_its_stream_in_the_url_and_never_ends_cleanly(self):
        """Workbench's proxy has lost a websocket's first message, and the UI's event client
        resubscribes only after an error: the path goes in the URL, and every end is an error."""
        shim = (APP / "event-bridge" / "event-shim.js").read_text()
        self.assertIn('wsUrl.searchParams.set("stream", url.pathname + url.search)', shim)
        self.assertNotIn("ws.send(", shim)
        self.assertNotIn("controller.close()", shim)
        self.assertIn("controller.error(", shim)
        self.assertNotIn("realFetch.apply(window, args)", shim, "no silent fallback to a stream the proxy will not deliver")
        bridge_py = (APP / "event-bridge" / "bridge.py").read_text()
        self.assertIn("def stream_path(request_path):", bridge_py)
        self.assertNotIn("websocket.recv()", bridge_py)
        # The path parser, without the websockets dependency.
        source = bridge_py[bridge_py.index("def stream_path"):]
        source = source[:source.index("\n\n\nasync def bridge")]
        namespace = {"parse_qs": __import__("urllib.parse").parse.parse_qs, "urlsplit": __import__("urllib.parse").parse.urlsplit,
                     "EVENT_PATH": re.compile(r"^/(global/)?event(\?[^\s]*)?$")}
        exec(source, namespace)
        stream_path = namespace["stream_path"]
        self.assertEqual(stream_path("/__event-ws?stream=/global/event"), "/global/event")
        self.assertEqual(stream_path("/__event-ws?stream=%2Fevent%3Fdirectory%3D%2Fsandbox"), "/event?directory=/sandbox")
        for bad in ("/__event-ws", "/__event-ws?stream=/session", "/__event-ws?stream=/global/event&stream=/event",
                    "/__event-ws?stream=http://x/global/event"):
            self.assertIsNone(stream_path(bad), bad)


if __name__ == "__main__":
    unittest.main()
