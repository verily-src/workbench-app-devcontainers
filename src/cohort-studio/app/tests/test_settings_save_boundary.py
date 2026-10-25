import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import expect

APP_DIR = Path(__file__).parent.parent


@pytest.fixture
def settings_app(tmp_path):
    env = dict(os.environ)
    for key in ("STUDIO_LLM_SECRET_ID", "STUDIO_LLM_KMS_KEY_ID", "ANTHROPIC_API_KEY",
                "OPENAI_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                "TYPESAFE_API_KEY"):
        env.pop(key, None)
    env.update(STUDIO_CONFIG=str(tmp_path / "config.json"),
               STUDIO_LOCAL_SECRET_DIR=str(tmp_path / "keys"),
               LINEAGE_DB=str(tmp_path / "lineage.sqlite"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
                            cwd=APP_DIR, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(url + "/api/health", timeout=1)
                break
            except OSError:
                if proc.poll() is not None:
                    pytest.fail("Isolated settings app exited before startup")
                time.sleep(0.2)
        else:
            pytest.fail("Isolated settings app did not start")
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def test_settings_saves_against_real_api_with_default_mcp_read_fields(page, settings_app):
    url = settings_app
    original = page.request.get(url + "/api/config").json()
    assert len(original["mcp_connections"]) >= 3
    assert all("token_set" in c for c in original["mcp_connections"])
    page.goto(url)
    page.locator(".topnav-link", has_text="Settings").click()
    provider = page.locator(".settings-card").first
    provider.get_by_label("Anthropic API key").fill("local-browser-regression-secret")
    with page.expect_response(lambda r: r.url.endswith("/api/config") and r.request.method == "PUT") as response:
        provider.get_by_role("button", name="Save", exact=True).click()
    assert response.value.status == 200, response.value.text()
    body = response.value.request.post_data_json
    assert set(body) == {"provider", "model", "api_key"}
    expect(provider.get_by_role("status")).to_have_text("Provider settings saved securely.")
    expect(provider.get_by_label("Anthropic API key")).to_have_value("")
    saved = page.request.get(url + "/api/config").json()
    assert saved["llm"]["api_key_set"] is True
    assert saved["mcp_connections"] == original["mcp_connections"]
    assert "local-browser-regression-secret" not in json.dumps(saved)

    palette = page.locator(".settings-card").filter(has=page.get_by_role("button", name="amber", exact=True))
    palette.get_by_role("button", name="amber", exact=True).click()
    palette.get_by_role("button", name="Save", exact=True).click()
    expect(palette.get_by_role("status")).to_have_text("Palette saved.")
    mcp = page.locator(".settings-card").filter(has=page.get_by_role("button", name="Add connection", exact=True))
    with page.expect_response(lambda r: r.url.endswith("/api/config") and r.request.method == "PUT") as response:
        mcp.get_by_role("button", name="Save", exact=True).click()
    assert response.value.status == 200, response.value.text()
    body = response.value.request.post_data_json
    assert set(body) == {"mcp_connections"}
    assert all("token_set" not in c for c in body["mcp_connections"])
    after = page.request.get(url + "/api/config").json()
    assert after["chart_palette"] == "amber"
    assert after["llm"]["api_key_set"] is True
