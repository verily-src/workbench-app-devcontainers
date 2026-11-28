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
        for path, starters in ((UI / "demo.yaml", 3), (UI / "examples" / "ehr-genomics-chips.yaml", 2)):
            with self.subTest(path=path.name):
                demo = settings.load_demo(path)
                self.assertGreaterEqual(len(demo["starters"]), starters)
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

    def test_the_ehr_genomics_chips_forecast_the_cohorts_own_members_in_one_step(self):
        demo = settings.load_demo(UI / "examples" / "ehr-genomics-chips.yaml")
        chips = {c["label"]: c for c in demo["next_steps"]}
        forecast = chips["Forecast kidney disease with Kumo"]
        self.assertIn("members of this cohort", forecast["prompt"])
        self.assertNotIn("outside", forecast["prompt"])
        genomes = chips["Add genomes to the forecast"]
        self.assertIn("forecast_forecast_with_genotypes", genomes["prompt"])
        self.assertIn("do not mention", genomes["prompt"])
        self.assertIn("call forecast_forecast_risk once", forecast["prompt"])
        self.assertIn('"value": [443597]', forecast["prompt"])
        # The data views come with the steps before them, by their dedicated tools, so the agent
        # writes no queries for them and the booth has no chip just for a view.
        # The records Kumo reads open the forecast step: a cohort need not lead to a forecast.
        starter = next(c for c in demo["starters"] if c["label"] == "Adults with type 2 diabetes")
        self.assertNotIn("forecast_", starter["prompt"])
        self.assertLess(forecast["prompt"].index("forecast_show_cohort_records"),
                        forecast["prompt"].index("forecast_forecast_risk"))
        self.assertIn("passing only", chips["Call variants with Parabricks"]["prompt"])
        self.assertIn("takes no inputs", chips["Call variants with Parabricks"]["prompt"])
        sarek = chips["Call variants with Parabricks"]["prompt"]
        self.assertLess(sarek.index("forecast_show_genomes"), sarek.index("registered sarek workflow"))
        self.assertFalse([c for c in demo["next_steps"] if c["label"].startswith("Show the")])

    def test_a_chip_source_is_loaded_and_sent_as_a_part_the_page_does_not_draw(self):
        demo = settings.load_demo(UI / "examples" / "ehr-genomics-chips.yaml")
        sourced = [c for c in demo["starters"] if c["source"]]
        self.assertEqual([c["label"] for c in sourced],
                         ["What is the Verily Pre platform?", "How does Verily Pre govern data?",
                          "Which NVIDIA tech is integrated in Verily Pre?"])
        for chip in sourced:
            self.assertIn("approved description", chip["source"])
            self.assertNotIn("Verily Pre is the governed", chip["prompt"])
        self.assertEqual(settings.load_demo(UI / "demo.yaml")["starters"][0]["source"], "")
        script = (UI / "static" / "app.js").read_text()
        self.assertIn('parts.push({ type: "text", text: source, synthetic: true })', script)
        self.assertIn('p.type === "text" && !p.synthetic', script)

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


import record_replay  # noqa: E402


def _session(prompt, answer, created=1000, sid="a"):
    """OpenCode's session/<id>/message for one step: the chip's message and an answer with a tool."""
    return [
        {"info": {"id": f"msg_{sid}1", "role": "user", "time": {"created": created}, "agent": "build"},
         "parts": [{"id": "prt_1", "type": "text", "text": prompt},
                   {"id": "prt_2", "type": "text", "text": "approved text", "synthetic": True}]},
        {"info": {"id": f"msg_{sid}2", "role": "assistant", "time": {"created": created + 1, "completed": created + 9},
                  "cost": 0.1, "tokens": {"input": 9}, "modelID": "m"},
         "parts": [{"id": "prt_3", "type": "step-start"},
                   {"id": "prt_4", "type": "tool", "tool": "forecast_show_genomes", "callID": "c1",
                    "state": {"status": "completed", "input": {"x": 1}, "output": '{"table": "| a |"}',
                              "title": "t", "metadata": {"big": "x" * 50}, "time": {"start": 1, "end": 2}}},
                   {"id": "prt_5", "type": "reasoning", "text": "thinking"},
                   {"id": "prt_6", "type": "text", "text": answer},
                   {"id": "prt_7", "type": "step-finish", "tokens": {}}]},
    ]


class RecordedRunTests(unittest.TestCase):
    def test_a_session_becomes_steps_with_only_what_the_page_draws(self):
        steps = record_replay.steps_of(_session("Show  the\n genomes ", "Here they are."))
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step["prompt"], "Show the genomes")
        user, answer = step["messages"]
        self.assertEqual([p["text"] for p in user["parts"]], ["Show  the\n genomes "])  # no synthetic source
        self.assertEqual([p["type"] for p in answer["parts"]], ["tool", "reasoning", "text"])
        tool = answer["parts"][0]
        self.assertEqual(set(tool["state"]), {"status", "input", "output", "time"})
        self.assertEqual(set(answer["info"]), {"id", "role", "time"})

    def test_steps_split_at_each_message_of_the_person(self):
        two = _session("First", "one") + _session("Second", "two", created=2000, sid="b")
        self.assertEqual([s["prompt"] for s in record_replay.steps_of(two[::-1])], ["First", "Second"])

    def test_a_later_recording_of_the_same_prompt_wins_in_its_place(self):
        old = record_replay.steps_of(_session("A", "old") + _session("B", "b", 2000, "b"))
        new = record_replay.steps_of(_session("A", "new", 3000, "c"))
        merged = record_replay.merge(old, new)
        self.assertEqual([s["prompt"] for s in merged["steps"]], ["A", "B"])
        self.assertEqual(merged["steps"][0]["messages"][1]["parts"][-1]["text"], "new")

    def test_the_recorder_writes_a_file_the_server_loads(self):
        folder = Path(tempfile.mkdtemp())
        with mock.patch.object(record_replay, "fetch", lambda base, sid: _session("Go " + sid, "ok")):
            record_replay.main(["--out", str(folder / "r.json"), "s1", "s2"])
            record_replay.main(["--out", str(folder / "r.json"), "--merge", str(folder / "r.json"), "s1"])
        data = settings.load_replays(folder / "r.json")
        self.assertEqual([s["prompt"] for s in data["steps"]], ["Go s1", "Go s2"])

    def test_the_page_matches_prompts_as_the_recorder_does(self):
        script = (UI / "static" / "app.js").read_text()
        self.assertIn('replace(/\\s+/g, " ").trim()', script)
        self.assertIn("steps.get(normalize(text))", script)

    def test_the_image_carries_the_recorder(self):
        self.assertIn("record_replay.py", (UI / "Dockerfile").read_text())


class ReplaySettingsTests(unittest.TestCase):
    def chips(self, folder, extra=""):
        path = Path(folder) / "chips.yaml"
        path.write_text("starters:\n  - label: A\n    prompt: Go\n" + extra)
        return path

    def test_the_replays_file_is_found_beside_the_chips_file_and_not_sent_as_a_path(self):
        folder = tempfile.mkdtemp()
        (Path(folder) / "r.json").write_text(json.dumps({"steps": []}))
        path = self.chips(folder, "replays: r.json\n")
        self.assertEqual(settings.replay_file(settings.load_demo(path)), Path(folder).resolve() / "r.json")
        config = settings.page_config({"ASSISTANT_DEMO": str(path), "ASSISTANT_ACCESS": "open"})
        self.assertIs(config["replays"], True)

    def test_no_replays_or_a_missing_file_offers_none(self):
        folder = tempfile.mkdtemp()
        for extra in ("", "replays: missing.json\n"):
            path = self.chips(folder, extra)
            self.assertIsNone(settings.replay_file(settings.load_demo(path)))
            self.assertIs(settings.page_config({"ASSISTANT_DEMO": str(path), "ASSISTANT_ACCESS": "open"})["replays"], False)

    def test_a_malformed_replays_file_is_refused(self):
        folder = Path(tempfile.mkdtemp())
        for bad in ({"steps": [{"prompt": 1, "messages": []}]}, [], {"steps": "x"}):
            (folder / "r.json").write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                settings.load_replays(folder / "r.json")

    def test_the_page_offers_the_switch_and_the_recorded_run_pill(self):
        page = (UI / "static" / "index.html").read_text()
        for node in ('id="replay-box"', 'id="replay-switch"', 'id="replay-pill"'):
            self.assertIn(node, page)
        self.assertIn('fetch("api/replay"', (UI / "static" / "app.js").read_text())


@unittest.skipIf(TestClient is None, "needs fastapi and httpx")
class ReplayRouteTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        (self.folder / "r.json").write_text(json.dumps({"version": 1, "steps": [{"prompt": "Go", "messages": []}]}))
        (self.folder / "chips.yaml").write_text("starters:\n  - label: A\n    prompt: Go\nreplays: r.json\n")

    def get(self, chips, access="open", **headers):
        import server
        with mock.patch.dict(os.environ, {"ASSISTANT_DEMO": str(chips), "ASSISTANT_ACCESS": access}):
            with TestClient(server.app) as client:
                return client.get("/api/replay", headers=headers)

    def test_the_recorded_runs_are_served_when_the_chips_file_names_them(self):
        r = self.get(self.folder / "chips.yaml")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["steps"][0]["prompt"], "Go")

    def test_none_configured_is_not_found(self):
        (self.folder / "plain.yaml").write_text("starters:\n  - label: A\n    prompt: Go\n")
        self.assertEqual(self.get(self.folder / "plain.yaml").status_code, 404)

    def test_the_gate_and_cross_site_rule_apply(self):
        self.assertEqual(self.get(self.folder / "chips.yaml", access="").status_code, 403)
        self.assertEqual(self.get(self.folder / "chips.yaml", **{"Sec-Fetch-Site": "cross-site"}).status_code, 403)


class RecorderChipFilterTests(unittest.TestCase):
    def test_only_steps_whose_prompt_is_a_chips_are_kept(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("record_replay", UI / "record_replay.py")
        rec = importlib.util.module_from_spec(spec); spec.loader.exec_module(rec)
        prompts = rec.chip_prompts(UI / "examples" / "ehr-genomics-chips.yaml")
        chip = next(p for p in prompts if "call forecast_forecast_risk once" in p)
        steps = [{"prompt": chip, "messages": []}, {"prompt": "Call cohort_get_status once.", "messages": []}]
        self.assertEqual([s["prompt"] for s in rec.only_chips(steps, prompts)], [chip])


class DecisionCardTests(unittest.TestCase):
    def test_a_record_of_answered_choices_shows_no_choices_card(self):
        # After the person answers, the designer's next idle reply carries "choices" that only
        # record the answers; the card would have nothing to send.
        script = (UI / "static" / "app.js").read_text()
        self.assertIn("out.choices.text && parseChoices(out.choices.text).length", script)


class IntroAndRecordingTimeTests(unittest.TestCase):
    def test_the_ehr_genomics_chips_open_with_the_health_context(self):
        demo = settings.load_demo(UI / "examples" / "ehr-genomics-chips.yaml")
        self.assertEqual(demo["intro_title"], "Why kidney disease, and why now")
        text = " ".join(demo["intro"])
        for fact in ("About 40 million Americans have diabetes", "about 1 in 7 American adults", "9 in 10", "CDC"):
            self.assertIn(fact, text)
        for absent in ("All of Us", "NIH"):
            self.assertNotIn(absent, text)
        self.assertEqual(settings.load_demo(UI / "demo.yaml")["intro"], [])
        script = (UI / "static" / "app.js").read_text()
        self.assertIn('intro.append(el("p", note ? "intro-note" : null', script, "intro lines are drawn as text")

    def test_recorded_steps_carry_their_time_and_session_and_the_page_shows_it(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("record_replay", UI / "record_replay.py")
        rec = importlib.util.module_from_spec(spec); spec.loader.exec_module(rec)
        steps = rec.steps_of([{"info": {"id": "m1", "role": "user", "time": {"created": 1764289098000}},
                               "parts": [{"type": "text", "text": "Go"}]}], "ses_A")
        self.assertEqual((steps[0]["recorded_at"], steps[0]["session"]), (1764289098000, "ses_A"))
        self.assertIsInstance(rec.merge(steps)["recorded"], int)
        script = (UI / "static" / "app.js").read_text()
        self.assertIn('"Recorded run" + (step.recorded_at ? " · " + when(step.recorded_at) : "")', script)
        self.assertIn('id="replay-info"', (UI / "static" / "index.html").read_text())
