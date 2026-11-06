"""Brand theme: Verily or Verily × 23andMe; validated by pydantic, stored in config."""
import pytest
from playwright.sync_api import expect

import config
from tests.test_e2e import app_url  # noqa: F401


def test_brand_is_validated_and_stored(tmp_path, monkeypatch, client):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "studio_config.json")
    assert config.public_config()["brand"] == "verily"
    assert client.put("/api/config", json={"brand": "23andme"}).json()["brand"] == "23andme"
    assert config.public_config()["brand"] == "23andme"
    assert client.put("/api/config", json={"brand": "acme"}).status_code == 422
    assert client.put("/api/config", json={"chart_palette": "23andme"}).json()["chart_palette"] == "23andme"
    assert client.put("/api/config", json={"chart_palette": "neon"}).status_code == 422


@pytest.mark.e2e
def test_23andme_brand_recolors_app_and_cobrands_header(page, app_url):
    state = {"brand": "verily"}

    def cfg(route):
        if route.request.method == "PUT":
            state.update(route.request.post_data_json)
        body = {"chart_palette": "verily", "brand": state["brand"], "llm": {"provider": "anthropic", "providers": {}},
                "jev": {}, "mcp": {"available": False, "path": "/mcp"}, "mcp_connections": [],
                "features": {"ai": False, "lineage": False, "plink": False}}
        route.fulfill(status=200, content_type="application/json", json=body)
    page.route("**/api/config", cfg)
    page.goto(app_url)
    page.get_by_role("toolbar", name="App tools").get_by_role("button", name="Settings").click()
    page.get_by_role("radiogroup", name="Brand").get_by_role("radio", name="23andMe × Verily").click()
    expect(page.locator("html")).to_have_attribute("data-brand", "23andme")
    accent = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
    assert accent == "#d50f67"
    # The header names the partner; Verily's own mark keeps Verily green.
    logo = page.locator(".topbar .brand-partner img")
    expect(logo).to_have_attribute("alt", "23andMe")
    page.wait_for_function("() => { const i = document.querySelector('.topbar .brand-partner img'); return i && i.complete && i.naturalWidth > 0; }")
    expect(page.locator(".brand-partner-name")).to_have_count(0)   # the real logo, not the text fallback
    mark = page.evaluate("getComputedStyle(document.querySelector('.brandmark')).color")
    assert mark == "rgb(8, 122, 106)"
    # The chart palette list offers the 23andMe colours.
    expect(page.locator(".palette-swatch", has_text="23andme")).to_be_visible()
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-brand", "23andme")
