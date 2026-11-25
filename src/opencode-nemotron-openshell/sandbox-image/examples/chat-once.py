#!/usr/bin/env python3
"""Smallest possible harness: one chat request to the local model.

The framework gives every harness two variables: OLLAMA_BASE_URL (Ollama's
OpenAI-compatible API, the only thing the sandbox policy lets a harness reach)
and AGENT_MODEL (the model tag). Arguments are the prompt.
"""
import json
import os
import sys
import urllib.request

prompt = " ".join(sys.argv[1:]) or "Reply with exactly one word: ready"
request = urllib.request.Request(
    os.environ["OLLAMA_BASE_URL"] + "/chat/completions",
    data=json.dumps({
        "model": os.environ["AGENT_MODEL"],
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=170) as response:
    choice = json.load(response)["choices"][0]
print("reply:", (choice["message"].get("content") or "").strip())
print("finish:", choice.get("finish_reason"))
