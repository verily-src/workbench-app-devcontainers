"""The assistant's own UI (src/ai-research-assistant/assistant-ui): what its server lets the
page reach, its chips file, and how the app's compose file and front door put it at the root."""
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import yaml

APP = Path(__file__).resolve().parents[2] / "src" / "ai-research-assistant"
UI = APP / "assistant-ui"
sys.path.insert(0, str(UI))

import settings  # noqa: E402


class AllowedCallsTests(unittest.TestCase):
    def test_the_page_can_make_the_calls_it_uses(self):
        for method, path in (("GET", "session"), ("POST", "session"), ("GET", "mcp"), ("GET", "config"),
                             ("GET", "session/ses_1aB/message"), ("POST", "session/ses_1aB/prompt_async"),
                             ("POST", "session/ses_1aB/abort"), ("POST", "permission/per_9/reply"),
                             ("POST", "question/que_9/reply"), ("POST", "question/que_9/reject")):
            self.assertTrue(settings.allowed(method, path), f"{method} {path}")

    def test_the_rest_of_opencode_is_not_reachable(self):
        for method, path in (("GET", "pty"), ("POST", "pty"), ("POST", "session/ses_1/shell"),
                             ("POST", "session/ses_1/command"), ("GET", "file/content"), ("POST", "mcp"),
                             ("POST", "config"), ("GET", "event"), ("GET", "session/ses_1/../../pty"),
                             ("POST", "session/ses_1/prompt_async/extra"), ("GET", "")):
            self.assertFalse(settings.allowed(method, path), f"{method} {path}")

    def test_every_call_the_page_makes_is_allowed(self):
        # The page's calls are oc("<path>"...) in app.js; ids are joined in with +.
        script = (UI / "static" / "app.js").read_text()
        import re
        calls = re.findall(r'\boc\("([a-z_/]+)"(?: \+ [\w.]+ \+ "([a-z_/]+)")?(, )?', script)
        self.assertGreater(len(calls), 8)
        for head, tail, has_body in calls:
            path = head + ("x1" + tail if tail else "")
            self.assertTrue(settings.allowed("POST" if has_body else "GET", path), path)


class ChipsFileTests(unittest.TestCase):
    def test_the_chips_files_load_with_starters_and_next_steps(self):
        for path in (UI / "demo.yaml", UI / "examples" / "ehr-genomics-chips.yaml"):
            with self.subTest(path=path.name):
                demo = settings.load_demo(path)
                self.assertGreaterEqual(len(demo["starters"]), 3)
                self.assertGreaterEqual(len(demo["next_steps"]), 3)
                for chip in demo["starters"] + demo["next_steps"]:
                    self.assertTrue(chip["label"] and chip["prompt"])
                    self.assertNotIn("\n", chip["prompt"])

    def test_the_default_chips_name_no_condition_gene_dataset_or_workflow(self):
        import re
        text = (UI / "demo.yaml").read_text().lower()
        for word in ("ckd", "kidney", "apol1", "pcsk9", "diabet", "ldl", "omop", "sarek", "parabricks", "genome"):
            self.assertNotIn(word, text, word)
        self.assertIsNone(re.search(r"wb-[a-z]+-[a-z]+-[0-9]{4}", text))

    def test_the_ehr_genomics_chips_ask_for_the_registered_workflow_and_drop_the_apol1_check(self):
        text = (UI / "examples" / "ehr-genomics-chips.yaml").read_text()
        self.assertIn("registered sarek workflow with Parabricks", text)
        self.assertNotIn("Who carries APOL1", text)
        self.assertIn("ASSISTANT_DEMO", text)

    def test_the_image_carries_the_examples(self):
        self.assertIn("COPY examples ./examples", (UI / "Dockerfile").read_text())

    def test_a_chip_without_a_prompt_is_refused(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as handle:
            handle.write("starters:\n  - label: No prompt\n")
            handle.flush()
            with self.assertRaisesRegex(ValueError, "label and a prompt"):
                settings.load_demo(handle.name)

    def test_the_text_box_can_be_turned_off_and_a_typo_is_refused(self):
        env = {"ASSISTANT_DEMO": str(UI / "demo.yaml")}
        self.assertEqual(settings.page_config(env)["input"], "free")
        self.assertEqual(settings.page_config({**env, "ASSISTANT_INPUT": "chips"})["input"], "chips")
        with self.assertRaisesRegex(ValueError, "ASSISTANT_INPUT"):
            settings.page_config({**env, "ASSISTANT_INPUT": "off"})


class AccessTests(unittest.TestCase):
    """The page for a person the app does not let in, and chips tied to features."""

    def page(self, state):
        env = {"ASSISTANT_DEMO": str(UI / "demo.yaml")}
        if state is None:
            return settings.page_config(env)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "access.json"
            if state != "missing":
                path.write_text(json.dumps(state))
            return settings.page_config({**env, "ASSISTANT_ACCESS": str(path)})

    def labels(self, config):
        return {c["label"] for c in config["starters"] + config["next_steps"]}

    def test_the_word_open_turns_the_gate_off_and_shows_every_chip(self):
        config = settings.page_config({"ASSISTANT_DEMO": str(UI / "demo.yaml"), "ASSISTANT_ACCESS": "open"})
        self.assertEqual(config["access"]["state"], "open")
        self.assertIn("Forecast with Kumo", self.labels(config))

    def test_an_unset_or_empty_access_state_keeps_the_gate_shut(self):
        for value in (None, ""):
            with self.subTest(value=value):
                self.assertEqual(self.page(None)["access"]["state"], "checking")
                self.assertEqual(settings.access_view(value)["state"], "checking")
        self.assertEqual(settings.access_view("open")["state"], "open")

    def test_the_app_sets_the_access_state_to_a_file_path_not_the_open_word(self):
        compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())["services"]["assistant-ui"]
        self.assertTrue(compose["environment"]["ASSISTANT_ACCESS"].startswith("/"))

    def test_each_state_has_its_page(self):
        for state, expected, text in (
                ("missing", "checking", "checking your access"),
                ({"status": "error", "tier": None, "message": "We couldn't verify your access. Retrying."}, "error", "Retrying"),
                ({"status": "error", "tier": None, "title": "Unavailable", "message": "Please try again later."},
                 "error", "try again later"),
                ({"status": "ok", "tier": None, "message": "The AI Research Assistant is in beta."}, "denied", "in beta"),
                ({"status": "ok", "tier": "beta", "features": {}, "model": {"backend": None, "message": "needs the GPU setup"}},
                 "no_model", "GPU setup")):
            with self.subTest(expected):
                access = self.page(state)["access"]
                self.assertEqual(access["state"], expected)
                self.assertIn(text, access["message"])
                self.assertTrue(access["title"])

    def test_an_error_state_may_name_its_page_title(self):
        self.assertEqual(self.page({"status": "error", "title": "Unavailable"})["access"]["title"], "Unavailable")
        self.assertEqual(self.page({"status": "error"})["access"]["title"], "Checking your access")

    def test_an_admitted_person_sees_only_the_chips_of_their_features(self):
        features = {"cohort_designer": True, "workflow_runs": True, "kumo_forecast": False, "vertex_model": False}
        config = self.page({"status": "ok", "tier": "beta", "features": features, "model": {"backend": "vllm"}})
        self.assertEqual(config["access"]["state"], "ok")
        self.assertNotIn("Forecast with Kumo", self.labels(config))
        self.assertIn("Design a cohort", self.labels(config))
        self.assertIn("What data is here?", self.labels(config), "a chip with no feature is always shown")

    def test_every_chip_feature_is_one_features_yaml_defines(self):
        features = yaml.safe_load((APP.parents[1] / "features" / "src" / "agent-sandbox" / "config" / "features.yaml")
                                  .read_text())["features"]
        demo = settings.load_demo(UI / "demo.yaml")
        for chip in demo["starters"] + demo["next_steps"]:
            if chip["feature"]:
                self.assertIn(chip["feature"], features, chip["label"])

    def test_the_page_has_the_gate_and_the_compose_file_mounts_the_state_read_only(self):
        html = (UI / "static" / "index.html").read_text()
        for id_ in ("gate", "gate-title", "gate-message", "layout"):
            self.assertIn(f'id="{id_}"', html)
        compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())["services"]
        ui = compose["assistant-ui"]
        self.assertIn("ara-access:/ara:ro", ui["volumes"])
        self.assertEqual(ui["environment"]["ASSISTANT_ACCESS"], "/ara/access.json")

    def test_the_assistant_stays_hidden_until_the_settings_let_the_person_in(self):
        # Otherwise a person who is not let in sees the assistant flash before the gate page.
        html = (UI / "static" / "index.html").read_text()
        for id_ in ("layout", "new-session", "conn-pill", "model-pill"):
            tag = re.search(rf'<[^>]*id="{id_}"[^>]*>', html).group(0)
            self.assertIn(" hidden", tag, id_)
        self.assertRegex(html, r'<section class="gate" id="gate" hidden>')
        js = (UI / "static" / "app.js").read_text()
        body = js[js.index("function start(config) {"):]
        shown = body.index('["layout", "new-session", "conn-pill", "model-pill"].forEach(function (id) { $(id).hidden = false; });')
        self.assertLess(body.index("gate(config); return;"), shown)
        # A failed settings load is shown on the gate page, the one thing visible.
        tail = js[js.rindex('fetch("api/config")'):]
        self.assertIn('$("gate").hidden = false;', tail)


class EventStreamTests(unittest.TestCase):
    def test_each_event_is_its_data_and_comments_are_dropped(self):
        lines = ["data: {\"type\":\"a\"}", "", ": ping", "", "event: x", "data: {\"type\":", "data: \"b\"}", ""]
        self.assertEqual(list(settings.sse_events(lines)), ['{"type":"a"}', '{"type":\n"b"}'])


class WiringTests(unittest.TestCase):
    def setUp(self):
        self.compose = yaml.safe_load((APP / "docker-compose.yaml").read_text())
        self.caddyfile = (APP / "caddy" / "Caddyfile").read_text()

    def test_the_front_door_serves_the_assistant_and_keeps_code_server(self):
        web = self.compose["services"]["opencode-web"]
        self.assertNotIn("command", web, "Caddy reads /etc/caddy/Caddyfile, the assistant's door")
        self.assertNotIn("opencode-web-events", self.compose["services"])
        ui = self.compose["services"]["assistant-ui"]
        self.assertEqual(ui["network_mode"], "service:app")
        self.assertEqual(ui["environment"]["HOST"], "127.0.0.1", "Caddy is the only way in")
        self.assertIn(f"reverse_proxy 127.0.0.1:{ui['environment']['PORT']}", self.caddyfile)
        self.assertIn("handle_path /ide/*", self.caddyfile)
        self.assertIn("reverse_proxy 127.0.0.1:8443", self.caddyfile)
        self.assertIn(":8080 {", self.caddyfile)

    def test_the_ui_reaches_opencode_where_the_broker_forwards_it(self):
        ui = self.compose["services"]["assistant-ui"]
        self.assertEqual(ui["environment"]["OPENCODE_URL"], "http://sandbox-broker:4096")
        harness = yaml.safe_load((APP.parents[1] / "features" / "src" / "opencode-harness" / "harnesses" / "opencode.yaml").read_text())
        self.assertEqual(harness["serve"]["port"], 4096)

    def test_the_image_holds_every_file_the_server_reads(self):
        dockerfile = (UI / "Dockerfile").read_text()
        for name in ("server.py", "settings.py", "demo.yaml", "static"):
            self.assertIn(name, dockerfile)

    def test_the_page_uses_relative_paths_only(self):
        # Workbench serves the app under a proxy path; a leading slash leaves it.
        page = (UI / "static" / "index.html").read_text()
        script = (UI / "static" / "app.js").read_text()
        self.assertNotRegex(page, r'(href|src)="/')
        self.assertNotRegex(script, r'fetch\("/|new URL\("/')


if __name__ == "__main__":
    unittest.main()


try:
    from fastapi.testclient import TestClient
except ImportError:  # CI installs only pyyaml.
    TestClient = None


@unittest.skipIf(TestClient is None, "needs fastapi and httpx")
class AccessGateTests(unittest.TestCase):
    """The server refuses OpenCode to a person the access state does not let in, not only the page."""

    def client(self, state):
        import os
        import server
        folder = tempfile.mkdtemp()
        path = Path(folder) / "access.json"
        path.write_text(json.dumps(state))
        old = os.environ.get("ASSISTANT_ACCESS")
        os.environ["ASSISTANT_ACCESS"] = str(path)
        self.addCleanup(lambda: os.environ.pop("ASSISTANT_ACCESS") if old is None
                        else os.environ.__setitem__("ASSISTANT_ACCESS", old))
        return TestClient(server.app)

    def test_a_denied_person_gets_no_opencode(self):
        denied = {"status": "ok", "tier": None, "message": "not in a group"}
        with self.client(denied) as client:
            self.assertEqual(client.get("/oc/session").status_code, 403)
            with self.assertRaises(Exception):
                with client.websocket_connect("/events") as ws:
                    ws.receive_text()

    def test_an_error_state_gets_no_opencode(self):
        with self.client({"status": "error", "tier": None}) as client:
            self.assertEqual(client.post("/oc/session", json={}).status_code, 403)

    def test_an_admitted_person_reaches_opencode(self):
        admitted = {"status": "ok", "tier": "beta", "features": {}, "model": {"backend": "vllm"}}
        with self.client(admitted) as client:
            # Nothing listens on OPENCODE_URL here: past the gate, the proxy answers 503.
            self.assertEqual(client.get("/oc/session").status_code, 503)

class MarkdownSanitizerTests(unittest.TestCase):
    """Model and tool text is untrusted: the page keeps an allow list and the CSP backs it up."""

    def setUp(self):
        self.script = (UI / "static" / "app.js").read_text()
        self.page = (UI / "static" / "index.html").read_text()

    def list_in_script(self, name):
        match = re.search(r"var " + name + r" = \[(.*?)\];", self.script, re.S)
        self.assertIsNotNone(match, name)
        return re.findall(r'"([^"]+)"', match.group(1))

    def test_the_sanitizer_uses_allow_lists_for_tags_and_attributes(self):
        call = re.search(r"DOMPurify\.sanitize\(html, \{(.*?)\}\)", self.script, re.S).group(1)
        self.assertIn("ALLOWED_TAGS: MARKDOWN_TAGS", call)
        self.assertIn("ALLOWED_ATTR: MARKDOWN_ATTRS", call)
        self.assertIn("ALLOW_DATA_ATTR: false", call)
        self.assertNotIn("FORBID_TAGS", call)
        tags = set(self.list_in_script("MARKDOWN_TAGS"))
        attrs = set(self.list_in_script("MARKDOWN_ATTRS"))
        self.assertTrue({"p", "a", "pre", "code", "table", "li"} <= tags)
        for tag in ("img", "video", "audio", "source", "svg", "image", "picture", "iframe",
                    "object", "embed", "form", "input", "style", "script", "link", "meta", "math"):
            self.assertNotIn(tag, tags)
        for attr in ("style", "src", "srcset", "poster", "background", "action", "formaction", "xlink:href"):
            self.assertNotIn(attr, attrs)

    def test_every_html_string_the_page_assigns_is_sanitized_or_constant(self):
        for line in self.script.splitlines():
            if re.search(r"innerHTML|insertAdjacentHTML|outerHTML|document\.write", line):
                self.assertRegex(line, r'DOMPurify\.sanitize\(|innerHTML = ""', line)

    def test_the_page_has_no_inline_script_or_style(self):
        # The CSP allows scripts and styles from the page's own origin only.
        self.assertNotRegex(self.page, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(self.page, r"<style\b")
        self.assertNotRegex(self.page, r'\sstyle="')
        self.assertNotRegex(self.page, r'\son[a-z]+="')


@unittest.skipIf(TestClient is None, "needs fastapi and httpx")
class SecurityHeaderTests(unittest.TestCase):
    def test_the_page_and_static_files_carry_the_policy(self):
        import server
        with TestClient(server.app) as client:
            for path in ("/", "/static/app.js", "/static/style.css", "/healthz", "/nothing"):
                headers = client.get(path).headers
                policy = headers["content-security-policy"]
                self.assertIn("default-src 'self'", policy, path)
                self.assertIn("media-src 'none'", policy, path)
                script_src = re.search(r"script-src ([^;]*)", policy).group(1)
                self.assertNotIn("unsafe-inline", script_src, path)
                self.assertNotIn("unsafe-inline", policy, path)
                self.assertNotIn("frame-ancestors", policy, path)
                self.assertEqual(headers["x-content-type-options"], "nosniff", path)
                self.assertEqual(headers["referrer-policy"], "no-referrer", path)
                self.assertNotIn("x-frame-options", headers, path)

    def test_opencode_answers_keep_only_json_or_event_stream_types(self):
        import asyncio
        import httpx
        import server
        self.enterContext(mock.patch.dict(os.environ, {"ASSISTANT_ACCESS": "open"}))

        def upstream(kind):
            def handler(request):
                return httpx.Response(200, content=b"<script>1</script>", headers={"content-type": kind})
            return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://up")

        with TestClient(server.app) as client:
            for kind, kept in (("text/html; charset=utf-8", "application/json"),
                               ("application/json", "application/json"),
                               ("text/event-stream", "text/event-stream")):
                server.app.state.client = upstream(kind)
                response = client.get("/oc/session")
                self.assertEqual(response.headers["content-type"].split(";")[0], kept, kind)
                self.assertIn("content-security-policy", response.headers)


@unittest.skipIf(TestClient is None, "needs fastapi and httpx")
class RequestGuardTests(unittest.TestCase):
    """What /oc and /events refuse from another site, and what is not passed on to OpenCode."""

    def setUp(self):
        import httpx
        import server
        self.server = server
        self.enterContext(mock.patch.dict(os.environ, {"ASSISTANT_ACCESS": "open"}))
        self.seen = []

        def handler(request):
            self.seen.append(request)
            return httpx.Response(200, json={"ok": True})
        self.client = self.enterContext(TestClient(server.app))
        server.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://up")

    def post(self, path, content=None, **headers):
        return self.client.post(path, content=content, headers=headers)

    def test_a_post_with_a_body_must_be_json(self):
        for kind in ("text/plain", "application/x-www-form-urlencoded", "text/plain;charset=UTF-8"):
            self.assertEqual(self.post("/oc/session", '{"title":"x"}', **{"Content-Type": kind}).status_code, 415, kind)
        self.assertEqual(self.seen, [])
        self.assertEqual(self.post("/oc/session", '{"title":"x"}').status_code, 415, "no content type")

    def test_a_json_post_reaches_opencode_as_json(self):
        for kind in ("application/json", "application/json; charset=utf-8", "Application/JSON"):
            response = self.post("/oc/session", '{"title":"x"}', **{"Content-Type": kind})
            self.assertEqual(response.status_code, 200, kind)
        self.assertEqual(len(self.seen), 3)
        self.assertEqual(self.seen[0].headers["content-type"], "application/json")
        self.assertEqual(self.seen[0].content, b'{"title":"x"}')

    def test_a_post_without_a_body_is_allowed(self):
        self.assertEqual(self.client.post("/oc/session/ses_1/abort").status_code, 200)

    def test_every_post_in_the_page_has_a_body_and_the_json_header(self):
        script = (UI / "static" / "app.js").read_text()
        self.assertIn('method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)', script)

    def test_a_cross_site_request_is_refused_on_oc_and_the_websocket(self):
        cross = {"Sec-Fetch-Site": "cross-site"}
        self.assertEqual(self.client.get("/oc/session", headers=cross).status_code, 403)
        self.assertEqual(self.post("/oc/session", "{}", **{"Content-Type": "application/json", **cross}).status_code, 403)
        self.assertEqual(self.seen, [])
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/events", headers=cross) as ws:
                ws.receive_text()

    def test_same_origin_same_site_none_and_no_header_are_allowed(self):
        for value in ("same-origin", "same-site", "none", None):
            headers = {} if value is None else {"Sec-Fetch-Site": value}
            self.assertEqual(self.client.get("/oc/session", headers=headers).status_code, 200, value)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_the_websocket_accepts_a_same_origin_handshake(self):
        import httpx

        def handler(request):
            return httpx.Response(200, content=b'data: {"type":"x"}\n\n', headers={"content-type": "text/event-stream"})
        self.server.app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://up")
        with self.client.websocket_connect("/events", headers={"Sec-Fetch-Site": "same-origin"}) as ws:
            self.assertEqual(ws.receive_text(), '{"type":"x"}')

    def test_no_query_string_is_passed_on(self):
        script = (UI / "static" / "app.js").read_text()
        self.assertNotRegex(script, r'\boc\("[^"]*\?')
        self.client.get("/oc/session?directory=/etc&x=1")
        self.assertEqual(self.seen[0].url.query, b"")

    def test_a_permission_reply_is_once_or_reject_only(self):
        json_type = {"Content-Type": "application/json"}
        for body in ('{"reply":"once"}', '{"reply":"reject"}'):
            self.assertEqual(self.post("/oc/permission/per_1/reply", body, **json_type).status_code, 200, body)
        for body in ('{"reply":"always"}', '{}', '[]', 'not json', '{"reply":["once"]}'):
            self.assertEqual(self.post("/oc/permission/per_1/reply", body, **json_type).status_code, 400, body)
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(self.post("/oc/question/que_1/reply", '{"answers":[["a"]]}', **json_type).status_code, 200)

    def test_the_page_sends_only_replies_the_server_passes(self):
        script = (UI / "static" / "app.js").read_text()
        sent = set(re.findall(r'reply\("(\w+)"\)', script))
        self.assertEqual(sent, {"once", "reject"})
        self.assertEqual(set(settings.PERMISSION_REPLIES), sent)

    def test_a_cookie_from_opencode_is_not_replayed(self):
        import httpx
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={}, headers={"set-cookie": "sid=abc; Path=/"} if len(calls) == 1 else {})
        client = self.server.new_client()
        client._transport = httpx.MockTransport(handler)
        import asyncio

        async def run():
            await client.get("http://127.0.0.1:4096/session")
            await client.get("http://127.0.0.1:4096/session")
            await client.aclose()
        asyncio.run(run())
        self.assertEqual(len(calls), 2)
        self.assertNotIn("cookie", calls[1].headers)
