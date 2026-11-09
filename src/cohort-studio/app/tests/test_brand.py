"""App color theme."""
import pytest
import config
from playwright.sync_api import expect

from tests.test_e2e import app_url  # noqa: F401


def test_removed_theme_settings_fall_back(tmp_path, monkeypatch, client):
    path = tmp_path / "studio_config.json"
    path.write_text('{"brand": "legacy", "chart_palette": "legacy"}')
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    result = client.get("/api/config").json()
    assert result["brand"] == "verily"
    assert result["chart_palette"] == "verily"
    assert client.put("/api/config", json={"brand": "legacy"}).status_code == 422
    assert client.put("/api/config", json={"chart_palette": "legacy"}).status_code == 422


@pytest.mark.e2e
def test_color_theme_recolors_the_whole_app(page, app_url):
    state = {"chart_palette": "verily"}

    def cfg(route):
        if route.request.method == "PUT":
            state.update(route.request.post_data_json)
        route.fulfill(status=200, content_type="application/json", json={
            "chart_palette": state["chart_palette"], "brand": "verily",
            "llm": {"provider": "anthropic", "providers": {}}, "jev": {}, "mcp": {"available": False, "path": "/mcp"},
            "mcp_connections": [], "features": {"ai": False, "lineage": False, "plink": False}})
    page.route("**/api/config", cfg)
    page.goto(app_url)
    page.get_by_role("toolbar", name="App tools").get_by_role("button", name="Settings").click()
    page.locator(".palette-swatch", has_text="indigo").click()
    page.get_by_role("button", name="Save color theme").click()
    expect(page.locator("html")).to_have_attribute("data-palette", "indigo")
    accent = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
    assert accent == "#4a3aa7"
    # The active nav tab uses it; Verily's own mark stays Verily green.
    page.get_by_role("toolbar", name="App tools").get_by_role("button", name="Settings").click()
    assert page.evaluate("getComputedStyle(document.querySelector('.corner-tool.active')).color") == "rgb(74, 58, 167)"
    assert page.evaluate("getComputedStyle(document.querySelector('.brandmark')).color") == "rgb(8, 122, 106)"
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-palette", "indigo")
