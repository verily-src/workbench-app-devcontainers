from playwright.sync_api import expect
from tests.test_e2e import app_url


def test_agent_integrations_show_setup_status_and_open_settings(page, app_url):
    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/config", lambda route: fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}},
        "mcp": {"available": True, "path": "/mcp"},
        "mcp_connections": [{"name": "pubmed", "label": "PubMed", "url": "https://example.org/mcp",
                             "enabled": True, "token_set": True, "note": ""}],
    }))
    page.route("**/api/datasources", lambda route: fulfill(route, {"ready": True, "sources": []}))
    page.route("**/api/workflows**", lambda route: fulfill(route, {"available": False, "jobs": []}))
    page.route("**/api/views/all", lambda route: fulfill(route, {"views": [], "unavailable": []}))
    page.route("**/api/agent/workflows", lambda route: fulfill(route, {"plans": []}))
    page.route("**/api/agent/chat/sessions", lambda route: fulfill(route, {"sessions": []}))
    page.route("**/api/agent/chat/history?*", lambda route: fulfill(route, {
        "session_id": None, "messages": [{"role": "assistant", "content": "Found [Example study](https://pubmed.ncbi.nlm.nih.gov/123/). <script>alert(1)</script> [unsafe](javascript:alert)"}], "has_more": False, "next_before_message_id": None,
    }))
    page.goto(app_url)
    page.locator(".topnav-link", has_text="Agent").click()
    citation = page.get_by_role("link", name="Example study")
    expect(citation).to_have_attribute("href", "https://pubmed.ncbi.nlm.nih.gov/123/")
    expect(citation).to_have_attribute("rel", "noopener noreferrer")
    expect(page.get_by_role("link", name="unsafe")).to_have_count(0)
    expect(page.locator(".studio-agent-bubble script")).to_have_count(0)
    panel = page.locator(".agent-integrations")
    panel.locator("summary").click()
    expect(panel.get_by_text("PubMed", exact=True)).to_be_visible()
    expect(panel.get_by_text("Built in · optional NCBI key", exact=True)).to_be_visible()
    expect(panel.get_by_text("Built in · date-window search", exact=True)).to_be_visible()
    expect(panel.get_by_text("bioRxiv", exact=True)).to_be_visible()
    expect(panel.get_by_text("arXiv", exact=True)).to_be_visible()
    expect(panel.get_by_text("Not configured", exact=True)).to_have_count(1)
    panel.get_by_role("button", name="Manage integrations").click()
    expect(page.locator(".topnav-link.active", has_text="Settings")).to_be_visible()
