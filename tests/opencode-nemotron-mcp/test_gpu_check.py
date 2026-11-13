"""Keep the real-GPU diagnostic read-only even when a model misbehaves."""

import copy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("gpu_check", Path(__file__).resolve().parents[2] /
                                             "src/opencode-nemotron-mcp/gpu-check.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)
MODEL = "nemotron-3.5-lightning:30b"
CONTEXT = 65536


def response(name=CHECK.SAFE_TOOL, arguments="{}"):
    return {"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": "", "tool_calls": [{"id": "test-call", "type": "function",
        "function": {"name": name, "arguments": arguments}}],
    }}]}


class GPUCheckTests(unittest.TestCase):
    def test_full_inventory_roundtrip_and_residency(self):
        # All schemas must reach the model, even though only wb_status can execute.
        tools = [{"type": "function", "function": {"name": f"wb_tool_{i}"}} for i in range(108)]
        requests = []

        def api(path, payload=None):
            if path == "/api/ps":
                return {"models": [{"name": MODEL, "size": 100, "size_vram": 100, "context_length": CONTEXT}]}
            requests.append(copy.deepcopy(payload))
            if len(requests) == 1:
                return response()
            return {"choices": [{"finish_reason": "stop", "message": {"content": "Workspace is accessible."}}]}

        with patch.object(CHECK, "api", side_effect=api), patch.object(CHECK, "mcp", return_value={"content": [{"text": "workspace"}]}) as mcp:
            result = CHECK.trial(MODEL, tools, "Instructions", ["mcp-server"], CONTEXT)
        self.assertEqual(requests[0]["tools"], tools)
        self.assertEqual(requests[1]["messages"][-1]["role"], "tool")
        self.assertEqual(requests[1]["messages"][-1]["tool_call_id"], "test-call")
        self.assertEqual(result["context_length"], CONTEXT)
        mcp.assert_called_once_with(["mcp-server"], "tools/call", {"name": "wb_status", "arguments": {}})

    def test_unsafe_ambiguous_or_silent_calls_never_execute(self):
        silent = {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}
        duplicate = response()
        duplicate["choices"][0]["message"]["tool_calls"] *= 2
        truncated = response()
        truncated["choices"][0]["finish_reason"] = "length"
        for reply in (response("wb_workspace_delete"), response(arguments='{"workspaceId":"unknown"}'),
                      response(arguments="not json"), silent, duplicate, truncated):
            with self.subTest(reply=reply), patch.object(CHECK, "api", return_value=reply), patch.object(CHECK, "mcp") as mcp:
                with self.assertRaises((RuntimeError, ValueError)):
                    CHECK.trial(MODEL, [], "Instructions", ["mcp-server"], CONTEXT)
                mcp.assert_not_called()

    def test_residency_rejects_cpu_wrong_context_and_concurrency(self):
        valid = {"name": MODEL, "size": 100, "size_vram": 100, "context_length": CONTEXT}
        for models in ([], [valid, valid], [{**valid, "size_vram": 90}], [{**valid, "context_length": 4096}],
                       [{**valid, "name": "other-model"}]):
            with self.subTest(models=models), patch.object(CHECK, "api", return_value={"models": models}):
                with self.assertRaises(RuntimeError):
                    CHECK.residency(MODEL, CONTEXT)

    def test_empty_summary_is_a_failure(self):
        replies = [response(), {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}]
        with patch.object(CHECK, "api", side_effect=replies), patch.object(CHECK, "residency", return_value={}), patch.object(CHECK, "mcp", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "completed text summary"):
                CHECK.trial(MODEL, [], "Instructions", ["mcp-server"], CONTEXT)


if __name__ == "__main__":
    unittest.main()
