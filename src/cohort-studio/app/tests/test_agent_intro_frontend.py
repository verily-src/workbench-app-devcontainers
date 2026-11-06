import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_agent_empty_state_explains_capabilities_and_fills_examples(page, app_url):
    page.goto(app_url)
    page.locator('.topnav').get_by_text('Agent', exact=True).click()
    intro = page.get_by_role('region', name='What the agent can do')
    expect(intro).to_be_visible(timeout=10000)
    for text in ("OMOP cohorts", "Joins", "Dashboards", "Workflows", "Literature",
                 "nothing runs or changes without your approval"):
        expect(intro).to_contain_text(text)
    expect(page.get_by_text('Earlier workflow plans')).to_have_count(0)
    example = "How many women born 1930–1950 have an observation period?"
    intro.get_by_role('button', name=example).click()
    expect(page.get_by_placeholder('What would you like to analyze?')).to_have_value(example)
    page.screenshot(path='/private/tmp/cohort-agent-intro.png')


def test_settings_offers_agent_memory_setup(page, app_url):
    page.route("**/api/admin/agent-store", lambda r: r.fulfill(json={
        "resource_id": None, "from_environment": False, "ready": False, "aurora": ["omop-data-source"]}))
    page.goto(app_url)
    page.get_by_role('button', name='Settings', exact=True).click()
    card = page.get_by_label('Agent memory', exact=True)
    expect(card).to_contain_text("Not set up", timeout=10000)
    expect(card.get_by_label('Agent memory datasource')).to_have_value('omop-data-source')
    expect(card.get_by_role('button', name='Set up agent memory')).to_be_enabled()
