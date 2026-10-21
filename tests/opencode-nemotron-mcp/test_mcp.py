"""Check the actual shared MCP binary with a fake Workbench CLI, no credentials."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.environ.get("WB_MCP_TEST_BINARY"), "Set WB_MCP_TEST_BINARY to a built shared server")
class MCPTransportTests(unittest.TestCase):
    def test_stdio_handshake_tools_and_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            wb = Path(temp) / "wb"
            wb.write_text('#!/bin/sh\necho \'{"status":"test-workspace"}\'\n')
            wb.chmod(0o755)
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "opencode-smoke-test", "version": "1"},
                }},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "wb_status", "arguments": {},
                }},
            ]
            result = subprocess.run(
                [os.environ["WB_MCP_TEST_BINARY"]],
                env={**os.environ, "PATH": temp + os.pathsep + os.environ["PATH"]},
                input="".join(json.dumps(request) + "\n" for request in requests),
                text=True, capture_output=True, timeout=15, check=True,
            )
            responses = [json.loads(line) for line in result.stdout.splitlines()]
            # Notifications must not produce a response or contaminate the JSON stream.
            self.assertEqual([reply["id"] for reply in responses], [1, 2, 3])
            for reply in responses:
                self.assertEqual(reply["jsonrpc"], "2.0")
                self.assertNotIn("error", reply)
            self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "wb-mcp-server")
            tools = {tool["name"] for tool in responses[1]["result"]["tools"]}
            self.assertIn("workspace_list_resources", tools)
            self.assertIn("wb_status", tools)
            call = responses[2]["result"]
            self.assertFalse(call.get("isError"))
            self.assertEqual(json.loads(call["content"][0]["text"]), {"status": "test-workspace"})


if __name__ == "__main__":
    unittest.main()
