import pytest
from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_tab_title_and_favicon(page, app_url):
    page.goto(app_url)
    assert page.title() == "Cohort Browser"
    icons = page.locator("link[rel='icon']").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert icons == ["/favicon.svg", "/favicon.png"]
    for href, kind in (("/favicon.svg", "image/svg"), ("/favicon.png", "image/png")):
        response = page.request.get(app_url + href)
        assert response.status == 200 and response.headers["content-type"].startswith(kind), href
