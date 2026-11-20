"""The vertex-model feature: its server against a stand-in for Vertex AI, and the app's wiring."""
import http.client
import importlib.util
import json
import os
import subprocess
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
FEATURE = REPO / "features" / "src" / "vertex-model"
APP = REPO / "src" / "ai-research-assistant"

spec = importlib.util.spec_from_file_location("vertex_proxy", FEATURE / "proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)

CALL = {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}
SIGNED = {**CALL, "extra_content": {"google": {"thought_signature": "sig-1"}}}


class FixedToken:
    def get(self):
        return "token"


class Vertex(BaseHTTPRequestHandler):
    """Answers like Vertex AI: a signed tool call, a 400 for a call sent back unsigned, and a 403
    for the model named "refused"."""
    received = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Vertex.received.append((self.headers["Authorization"], body))
        if body["model"] == "google/refused":
            data = b'{"error": {"code": 403, "message": "Permission denied on resource project p."}}'
            self.send_response(403)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        for message in body["messages"]:
            calls = message.get("tool_calls") or []
            if calls and not proxy.signature_of(calls[0]):
                data = b'{"error": {"code": 400, "message": "Function call is missing a thought_signature"}}'
                self.send_response(400)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            first = {"choices": [{"index": 0, "delta": {"tool_calls": [
                {"index": 0, "extra_content": {"google": {"thought_signature": "sig-2"}}}]}}]}
            second = {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "id": "call_2", **{
                k: v for k, v in CALL.items() if k != "id"}}]}}]}
            for chunk in (first, second):
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return
        data = json.dumps({"choices": [{"index": 0, "message": {"role": "assistant", "tool_calls": [SIGNED]}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def started(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vertex = ThreadingHTTPServer(("127.0.0.1", 0), Vertex)
        upstream = started(cls.vertex) + "/v1/chat/completions"
        cls.server = proxy.serve("gemini-3.5-flash", upstream, "127.0.0.1", 0, 262144, tokens=FixedToken())
        cls.url = started(cls.server)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.vertex):
            server.shutdown()
            server.server_close()

    def setUp(self):
        Vertex.received.clear()

    def post(self, body):
        request = urllib.request.Request(self.url + "/v1/chat/completions", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode()

    def test_models_and_health_are_answered_here(self):
        with urllib.request.urlopen(self.url + "/v1/models") as response:
            served = json.loads(response.read())["data"][0]
        self.assertEqual((served["id"], served["max_model_len"]), ("gemini-3.5-flash", 262144))
        with urllib.request.urlopen(self.url + "/health") as response:
            self.assertEqual(response.status, 200)

    def test_a_request_goes_with_the_credential_and_vertexs_model_name(self):
        self.post({"model": "anything", "messages": [{"role": "user", "content": "hi"}]})
        authorization, body = Vertex.received[-1]
        self.assertEqual(authorization, "Bearer token")
        self.assertEqual(body["model"], "google/gemini-3.5-flash")

    def test_a_signature_the_client_dropped_is_put_back(self):
        self.post({"messages": [{"role": "user", "content": "weather?"}]})
        history = [{"role": "user", "content": "weather?"}, {"role": "assistant", "tool_calls": [CALL]},
                   {"role": "tool", "tool_call_id": "call_1", "content": "sunny"}]
        self.post({"messages": history})
        sent = Vertex.received[-1][1]["messages"][1]["tool_calls"][0]
        self.assertEqual(proxy.signature_of(sent), "sig-1")

    def test_a_streamed_signature_is_kept_though_it_comes_before_the_calls_id(self):
        reply = self.post({"stream": True, "messages": [{"role": "user", "content": "weather?"}]})
        self.assertIn("data: [DONE]", reply)
        self.assertEqual(self.server.RequestHandlerClass.signatures.get("call_2"), "sig-2")

    def test_a_call_never_seen_gets_the_placeholder_on_its_steps_first_call(self):
        unknown = [{**CALL, "id": "call_old"}, {**CALL, "id": "call_old_2"}]
        self.post({"messages": [{"role": "assistant", "tool_calls": unknown}]})
        sent = Vertex.received[-1][1]["messages"][0]["tool_calls"]
        self.assertEqual([proxy.signature_of(c) for c in sent], [proxy.PLACEHOLDER, None])

    def test_vertexs_refusal_reaches_the_client_as_it_is(self):
        upstream = f"http://127.0.0.1:{self.vertex.server_address[1]}/v1/chat/completions"
        server = proxy.serve("refused", upstream, "127.0.0.1", 0, 1, tokens=FixedToken())
        url = started(server)
        try:
            request = urllib.request.Request(url + "/v1/chat/completions", b'{"messages": []}',
                                             {"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
            self.assertEqual(caught.exception.code, 403)
            self.assertIn(b"Permission denied", caught.exception.read())
        finally:
            server.shutdown()
            server.server_close()

    def test_only_chat_completions_is_served(self):
        request = urllib.request.Request(self.url + "/v1/completions", b"{}", {"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(caught.exception.code, 404)

    def post_raw(self, data, length=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            connection.putrequest("POST", "/v1/chat/completions")
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(data) if length is None else length))
            connection.endheaders(data)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_a_body_that_is_not_an_object_or_has_odd_messages_is_a_400_in_openai_form(self):
        for body in (b"[1]", b"null", b'"text"', b'{"messages": 3}', b'{"messages": [1]}', b'{"messages": [null]}',
                     b'{"messages": [{"role": "assistant", "tool_calls": [1]}]}',
                     b'{"messages": [{"role": "assistant", "tool_calls": "x"}]}'):
            status, reply = self.post_raw(body)
            self.assertEqual((status, reply["error"]["type"]), (400, "invalid_request_error"), body)
            self.assertTrue(reply["error"]["message"], body)
        self.assertEqual(Vertex.received, [])

    def test_a_negative_or_non_numeric_content_length_is_a_400(self):
        for length in ("-1", "abc"):
            status, reply = self.post_raw(b"{}", length=length)
            self.assertEqual(status, 400, length)
            self.assertIn("Content-Length", reply["error"]["message"])

    def test_a_body_over_the_cap_is_a_413_without_being_read(self):
        with mock.patch.object(proxy, "MAX_BODY", 100):
            status, reply = self.post_raw(b'{"messages": []}', length=101)
            self.assertEqual(status, 413)
            self.assertIn("100 bytes", reply["error"]["message"])
            self.assertEqual(self.post_raw(b'{"messages": []}')[0], 200)

    def test_the_default_cap_leaves_room_for_images(self):
        self.assertGreaterEqual(proxy.MAX_BODY, 64 * 1024 * 1024)


class TokenTests(unittest.TestCase):
    def test_gcloud_is_asked_with_a_timeout_and_a_timeout_is_a_502_not_a_dropped_connection(self):
        timeout = subprocess.TimeoutExpired(["gcloud"], 60)
        with mock.patch.object(proxy, "metadata", side_effect=OSError("no metadata server")), \
                mock.patch.object(proxy.subprocess, "check_output", side_effect=timeout) as ask:
            server = proxy.serve("gemini-3.5-flash", "http://127.0.0.1:1/v1/chat/completions", "127.0.0.1", 0, 1)
            url = started(server)
            try:
                request = urllib.request.Request(url + "/v1/chat/completions", b"{}", {"Content-Type": "application/json"})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=10)
                self.assertEqual(caught.exception.code, 502)
                self.assertIn("no Google credential", caught.exception.read().decode())
            finally:
                server.shutdown()
                server.server_close()
        self.assertEqual(ask.call_args.kwargs["timeout"], 60)


class VLLM(BaseHTTPRequestHandler):
    """Answers like vLLM on the workspace's endpoint: what it got, streamed or not."""
    received = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        VLLM.received.append((self.path, self.headers["Authorization"], body))
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {"choices": [{"index": 0, "delta": {"reasoning": "hm", "tool_calls": [{"index": 0, **CALL}]}}]}
            self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\ndata: [DONE]\n\n")
            return
        data = json.dumps({"choices": [{"index": 0, "message": {"role": "assistant", "content": "ok",
                                                                "reasoning": "hm"}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class EndpointServerTests(unittest.TestCase):
    """VERTEX_ENDPOINT_URL: the workspace's own endpoint, which runs vLLM."""

    @classmethod
    def setUpClass(cls):
        cls.vllm = ThreadingHTTPServer(("127.0.0.1", 0), VLLM)
        cls.base = started(cls.vllm) + "/v1/projects/1/locations/r/endpoints/9/invoke/v1"
        cls.server = proxy.serve("nvidia/super", proxy.endpoint_chat_url(cls.base), "127.0.0.1", 0, 262144,
                                 tokens=FixedToken(), mode="endpoint")
        cls.url = started(cls.server)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.server, cls.vllm):
            server.shutdown()
            server.server_close()

    def setUp(self):
        VLLM.received.clear()

    def post(self, body):
        request = urllib.request.Request(self.url + "/v1/chat/completions", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.read().decode()

    def test_a_request_goes_as_it_is_but_for_the_served_name(self):
        history = [{"role": "user", "content": "weather?"}, {"role": "assistant", "tool_calls": [CALL]},
                   {"role": "tool", "tool_call_id": "call_1", "content": "sunny"}]
        body = {"model": "anything", "messages": history, "tools": [], "max_tokens": 9,
                "chat_template_kwargs": {"enable_thinking": True}, "thinking_token_budget": 16384}
        reply = json.loads(self.post(body))
        path, authorization, sent = VLLM.received[-1]
        self.assertEqual(path, "/v1/projects/1/locations/r/endpoints/9/invoke/v1/chat/completions")
        self.assertEqual(authorization, "Bearer token")
        self.assertEqual(sent, {**body, "model": "nvidia/super"}, "no Gemini signatures, nothing else changed")
        self.assertEqual(reply["choices"][0]["message"]["reasoning"], "hm")

    def test_a_streamed_reply_comes_back_as_it_is(self):
        reply = self.post({"stream": True, "messages": [{"role": "user", "content": "weather?"}]})
        self.assertIn('"reasoning": "hm"', reply)
        self.assertIn("data: [DONE]", reply)

    def test_models_names_the_endpoints_model(self):
        with urllib.request.urlopen(self.url + "/v1/models") as response:
            self.assertEqual(json.loads(response.read())["data"][0]["id"], "nvidia/super")


def endpoint(number, dns="9.r-1.prediction.vertexai.goog", deployed=True, created="2026-11-19T00:00:00Z"):
    return {"name": f"projects/1/locations/r/endpoints/{number}", "createTime": created,
            **({"dedicatedEndpointDns": dns} if dns else {}),
            **({"deployedModels": [{"id": "5", "model": f"projects/1/locations/r/models/{number}0"}]}
               if deployed else {})}


ARGS = ["nvidia/super", "--revision", "abc", "--served-model-name", "nvidia/super-served", "--max-model-len",
        "262144", "--reasoning-config", '{"reasoning_end_str": "x"}']


class FindEndpointTests(unittest.TestCase):
    def finder(self, listed, args=ARGS, fail_model=False):
        calls = []

        def get(url, tokens):
            calls.append(url)
            if "/models/" in url:
                if fail_model:
                    raise urllib.error.URLError("refused")
                return {"name": url, "containerSpec": {"command": ["vllm", "serve"], "args": args}}
            if "?filter=" in url:
                return {"endpoints": listed}
            return listed[0]
        return get, calls

    def test_auto_takes_the_newest_ready_endpoint_and_reads_what_its_model_serves(self):
        get, calls = self.finder([endpoint(7, created="2026-01-01T00:00:00Z"), endpoint(9),
                                  endpoint(8, deployed=False, created="2026-12-01T00:00:00Z")])
        found = proxy.find_endpoint("p", "r", "auto", FixedToken(), get=get)
        base = "https://9.r-1.prediction.vertexai.goog/v1/projects/1/locations/r/endpoints/9/invoke/v1"
        self.assertEqual(found, {"url": base, "model": "nvidia/super-served", "context": 262144,
                                 "endpoint": "projects/1/locations/r/endpoints/9"})
        self.assertEqual(calls, [
            "https://r-aiplatform.googleapis.com/v1/projects/p/locations/r/endpoints?filter=labels.ara-model%3A%2A",
            "https://r-aiplatform.googleapis.com/v1/projects/1/locations/r/models/90"])

    def test_the_served_name_falls_back_to_the_model_and_takes_either_flag_form(self):
        self.assertEqual(proxy.served({"containerSpec": {"args": ["nvidia/super", "--port", "8080"]}}),
                         ("nvidia/super", 0))
        self.assertEqual(proxy.served({"containerSpec": {"args": ["--model=gs://b/m", "--max-model-len=8192"]}}),
                         ("gs://b/m", 8192))
        self.assertEqual(proxy.served({}), (None, 0))

    def test_a_label_value_or_an_id_picks_the_endpoint(self):
        get, calls = self.finder([endpoint(9)])
        proxy.find_endpoint("p", "r", "super-vl", FixedToken(), get=get)
        self.assertTrue(calls[0].endswith("?filter=labels.ara-model%3Dsuper-vl"))
        get, calls = self.finder([endpoint(9)])
        proxy.find_endpoint("p", "r", "9", FixedToken(), get=get)
        self.assertTrue(calls[0].endswith("/endpoints/9"))

    def test_no_ready_endpoint_says_why(self):
        for listed, why in (([], "there is none"), ([endpoint(9, dns="")], "none is dedicated"),
                            ([endpoint(9, deployed=False)], "none is dedicated")):
            get, _ = self.finder(listed)
            with self.assertRaises(LookupError) as caught:
                proxy.find_endpoint("p", "r", "auto", FixedToken(), get=get)
            self.assertIn(why, str(caught.exception))

    def test_a_model_that_cannot_be_read_or_names_nothing_is_not_used(self):
        get, _ = self.finder([endpoint(9)], fail_model=True)
        with self.assertRaises(LookupError):
            proxy.find_endpoint("p", "r", "auto", FixedToken(), get=get)
        get, _ = self.finder([endpoint(9)], args=["--port", "8080"])
        with self.assertRaises(LookupError):
            proxy.find_endpoint("p", "r", "auto", FixedToken(), get=get)


class UpstreamTests(unittest.TestCase):
    def test_the_global_location_has_no_region_in_its_host(self):
        self.assertEqual(proxy.upstream_url("p", "global"),
                         "https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi/chat/completions")
        self.assertTrue(proxy.upstream_url("p", "us-central1").startswith("https://us-central1-aiplatform.googleapis.com/"))


class AppTests(unittest.TestCase):
    def test_the_app_serves_gemini_and_names_it_to_the_harness(self):
        env = yaml.safe_load((APP / "docker-compose.yaml").read_text())["services"]["app"]["environment"]
        self.assertEqual((env["VERTEX_MODEL"], env["VERTEX_LOCATION"]), ("gemini-3.5-flash", "global"))
        # The model start-services.sh chose (Vertex AI or vLLM), from the access state.
        self.assertEqual(env["AGENT_MODEL_COMMAND"], "/opt/ai-policy/access.py model-name --state /config/.ara/access.json")
        features = json.loads((APP / ".devcontainer.json").read_text())["features"]
        self.assertIn("./.devcontainer/features/vertex-model", features)

    def test_start_services_starts_vertex_in_place_of_vllm_when_access_py_chooses_it(self):
        start = (APP / "start-services.sh").read_text()
        self.assertIn('    vertex)\n', start)
        self.assertIn('      export VLLM_MODEL="${VERTEX_MODEL}"', start)
        self.assertIn("/opt/vertex-model/start-server.sh || {", start)
        self.assertIn('      export VERTEX_MODEL=""', start, "the vLLM path must not take the Vertex AI path later")
        self.assertIn("AGENT_MODEL_COMMAND,VERTEX_MODEL,VLLM_MODEL", start)
        self.assertIn('  designer_provider="gemini"\n', start, "the designer runs on its own Gemini provider")
        self.assertIn('COHORT_DESIGNER_PROVIDER="${designer_provider}"', start)

    def test_the_app_looks_for_the_workspaces_endpoint_ahead_of_gemini(self):
        env = yaml.safe_load((APP / "docker-compose.yaml").read_text())["services"]["app"]["environment"]
        self.assertEqual((env["VERTEX_ENDPOINT"], env["VERTEX_ENDPOINT_LOCATION"]), ("auto", "us-central1"))
        start = (APP / "start-services.sh").read_text()
        self.assertIn("python3 /opt/vertex-model/proxy.py find-endpoint", start)
        self.assertIn('--endpoint-model "${endpoint_model}"', start)
        case = start[start.index("    endpoint)\n"):start.index("    vertex)\n")]
        self.assertIn('export VLLM_MODEL="${endpoint_model}" VERTEX_MODEL="${endpoint_model}"', case)
        # sudo reads /etc/environment (compose's Gemini VERTEX_MODEL) over --preserve-env, so by env.
        self.assertIn('env VERTEX_MODEL="${endpoint_model}" VERTEX_ENDPOINT_URL="${VERTEX_ENDPOINT_URL}"', case)
        self.assertNotIn("--preserve-env=VERTEX_MODEL", case)
        self.assertNotIn("designer_provider=", case, "the designer keeps its usual provider on vLLM's port")
        self.assertTrue(os.access(FEATURE / "deploy-endpoint.sh", os.X_OK))


if __name__ == "__main__":
    unittest.main()
