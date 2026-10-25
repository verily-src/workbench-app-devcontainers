import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_provider_settings_save_before_test_without_echoing_key(
        page: Page, app_url: str):
    provider_ids = ("anthropic", "openai", "gemini", "openrouter", "bedrock",
                    "vertexai", "openweight")
    config = {
        "llm": {
            "provider": "anthropic", "model": "claude-opus-5",
            "api_key_set": False, "api_key_source": None,
            "providers": {name: {
                "model": "claude-opus-5" if name == "anthropic" else "",
                "api_key_set": False, "api_key_source": None,
                "auth_method": "api_key", "region": None,
                "configured": False,
            } for name in provider_ids},
        },
        "mcp": {"available": False, "path": "/mcp"},
        "mcp_connections": [], "chart_palette": "verily",
        "jev": {"model": "", "api_key_set": False,
                "api_key_source": None},
    }
    requests = []
    key = "test-only-provider-key-not-for-live-use"

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))

    def config_route(route):
        if route.request.method == "PUT":
            body = route.request.post_data_json
            requests.append(("save", body))
            config["llm"]["provider"] = body["provider"]
            config["llm"]["model"] = body["model"]
            state = config["llm"]["providers"][body["provider"]]
            state["model"] = body["model"]
            if body.get("api_key"):
                state["api_key_set"] = True
                state["api_key_source"] = "local_encrypted"
            config["llm"]["api_key_set"] = state["api_key_set"]
            config["llm"]["api_key_source"] = state["api_key_source"]
        fulfill(route, config)

    page.route("**/api/config", config_route)

    def test_route(route):
        requests.append(("test", None))
        fulfill(route, {"ok": True, "provider": "anthropic",
                        "model": "claude-sonnet-5", "display_name": "Claude"})

    page.route("**/api/config/llm/test", test_route)
    page.goto(app_url)
    page.locator(".topnav-link", has_text="Settings").click()

    ai_card = page.locator(".settings-card").first
    ai_card.locator('input[type="text"]').first.fill("claude-sonnet-5")
    ai_card.get_by_label("Anthropic API key").fill(key)
    ai_card.get_by_role("button", name="Test connection").click()

    expect(ai_card.get_by_role("status")).to_have_text(
        "Connected: Claude (claude-sonnet-5).", timeout=10000)
    assert [kind for kind, _ in requests] == ["save", "test"]
    assert requests[0][1]["api_key"] == key
    assert requests[0][1]["model"] == "claude-sonnet-5"
    assert key not in ai_card.inner_text()


def test_provider_save_failure_is_visible(page: Page, app_url: str):
    config = {
        "llm": {"provider": "anthropic", "model": "claude-opus-5",
                "api_key_set": False, "api_key_source": None,
                "providers": {name: {"model": "claude-opus-5",
                    "api_key_set": False, "api_key_source": None,
                    "auth_method": "api_key", "region": None}
                    for name in ("anthropic", "openai", "gemini", "openrouter",
                                 "bedrock", "vertexai", "openweight")}},
        "mcp": {"available": False, "path": "/mcp"},
        "mcp_connections": [], "chart_palette": "verily",
        "jev": {"model": "", "api_key_set": False, "api_key_source": None},
    }

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/config", lambda route: fulfill(
        route, {"detail": "secret-safe failure"}, 500)
        if route.request.method == "PUT" else fulfill(route, config))
    page.goto(app_url)
    page.locator(".topnav-link", has_text="Settings").click()
    ai_card = page.locator(".settings-card").first
    ai_card.get_by_role("button", name="Save", exact=True).click()
    expect(ai_card.get_by_role("status")).to_contain_text("Save failed:")


def test_provider_test_failure_redacts_key(page: Page, app_url: str):
    provider_ids = ("anthropic", "openai", "gemini", "openrouter", "bedrock",
                    "vertexai", "openweight")
    config = {
        "llm": {"provider": "anthropic", "model": "claude-opus-5",
                "api_key_set": False, "api_key_source": None,
                "providers": {name: {"model": "claude-opus-5",
                    "api_key_set": False, "api_key_source": None,
                    "auth_method": "api_key", "region": None}
                    for name in provider_ids}},
        "mcp": {"available": False, "path": "/mcp"},
        "mcp_connections": [], "chart_palette": "verily",
        "jev": {"model": "", "api_key_set": False, "api_key_source": None},
    }
    key = "test-only-provider-key-not-for-live-use"

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))

    def config_route(route):
        if route.request.method == "PUT":
            config["llm"]["api_key_set"] = True
            config["llm"]["api_key_source"] = "local_encrypted"
            config["llm"]["providers"]["anthropic"]["api_key_set"] = True
            config["llm"]["providers"]["anthropic"]["api_key_source"] = "local_encrypted"
        fulfill(route, config)

    page.route("**/api/config", config_route)
    page.route("**/api/config/llm/test", lambda route: fulfill(
        route, {"detail": f"Unauthorized; key was {key}"}, 502))
    page.goto(app_url)
    page.locator(".topnav-link", has_text="Settings").click()
    ai_card = page.locator(".settings-card").first
    ai_card.get_by_label("Anthropic API key").fill(key)
    ai_card.get_by_role("button", name="Test connection").click()
    status = ai_card.get_by_role("status")
    expect(status).to_contain_text("Connection test failed:", timeout=10000)
    expect(status).to_contain_text("[redacted]")
    assert key not in ai_card.inner_text()


def test_jev_token_is_masked_saved_and_removed_without_connection_claim(
        page: Page, app_url: str):
    provider_ids = ("anthropic", "openai", "gemini", "openrouter", "bedrock",
                    "vertexai", "openweight")
    config = {
        "llm": {
            "provider": "anthropic", "model": "claude-opus-5",
            "api_key_set": False, "api_key_source": None,
            "providers": {name: {
                "model": "claude-opus-5" if name == "anthropic" else "",
                "api_key_set": False, "api_key_source": None,
                "auth_method": "api_key", "region": None,
                "configured": False,
            } for name in provider_ids},
        },
        "mcp": {"available": False, "path": "/mcp"},
        "mcp_connections": [], "chart_palette": "verily",
        "jev": {"model": "", "api_key_set": False,
                "api_key_source": None},
    }
    writes = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))

    def config_route(route):
        if route.request.method == "PUT":
            body = route.request.post_data_json
            writes.append(body)
            if "jev_model" in body:
                config["jev"]["model"] = body["jev_model"]
            if "jev_api_key" in body:
                if body["jev_api_key"]:
                    config["jev"].update(api_key_set=True,
                                         api_key_source="local_encrypted")
                else:
                    config["jev"].update(api_key_set=False, api_key_source=None)
        fulfill(route, config)

    page.route("**/api/config", config_route)
    page.goto(app_url)
    page.locator(".topnav-link", has_text="Settings").click()
    token_field = page.get_by_label("TypeSafe API token")
    card = page.locator(".settings-card").filter(has=token_field)
    token = "test-only-jevs-token-not-for-live-use"
    token_field.fill(token)
    card.get_by_label("Jev model").fill("ranker-v1")
    card.get_by_role("button", name="Save Jev settings").click()

    expect(card.get_by_role("status")).to_have_text(
        "Settings saved. Connection not tested.")
    assert writes[-1] == {"jev_model": "ranker-v1", "jev_api_key": token}
    assert token not in card.inner_text()
    assert token_field.input_value() == ""
    assert token not in page.evaluate("Object.values(localStorage).join(' ')")

    expect(token_field).to_have_attribute("placeholder", "Enter a new token to replace")
    card.get_by_role("button", name="Remove saved token").click()
    expect(card.get_by_role("status")).to_have_text("Saved token removed.")
    assert writes[-1] == {"jev_api_key": ""}
