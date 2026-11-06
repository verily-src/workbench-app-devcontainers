import pytest
from playwright.sync_api import expect
from tests.test_e2e import app_url
from tests.test_table_info_progress_frontend import _mock_app

pytestmark = pytest.mark.e2e

COLUMNS = [{"name": "group", "dtype": "object", "filter_kind": "categorical", "values": ["A", "B"]}]


def _load(page, app_url, bodies):
    reply = _mock_app(page)
    page.route('**/api/data-jobs/open', lambda r: reply(r, {'job_id': 'j', 'kind': 'open', 'status': 'complete',
        'result': {'dataset_id': 'ds1', 'source': 'omop / cms.cost', 'rows': 8, 'columns': COLUMNS,
                   'query_scope': 'database'}}))

    def query(route):
        body = route.request.post_data_json
        bodies.append(body)
        charts = [{"kind": "bar", "x": "group", "data": [
            {"category": "A", "all": 5, "selected": 5}, {"category": "B", "all": 3, "selected": 3}]}
            for c in body["charts"] if c["kind"] in ("bar", "auto") or c.get("x") == "group"]
        reply(route, {'total': 8, 'filtered': 8, 'scope': 'database', 'sampled': False, 'entity': None,
                      'cache': None, 'charts': charts,
                      'rows': {'page': 0, 'page_size': 50, 'columns': ['group'], 'data': [['A']]}})
    page.route('**/api/datasets/ds1/query', query)
    page.goto(app_url)
    page.get_by_label('Source type', exact=True).select_option('aurora')
    page.get_by_label('Datasource', exact=True).select_option('aurora:omop')
    page.get_by_label('Schema', exact=True).select_option('cms')
    page.get_by_label('Table', exact=True).select_option('cms.cost')
    page.get_by_role('button', name='Load table', exact=True).click()
    expect(page.locator('.dataset-toolbar')).to_be_visible(timeout=10000)


def _fits(page):
    return page.evaluate("() => [document.documentElement.scrollWidth <= innerWidth + 1, "
                         "document.documentElement.scrollHeight <= innerHeight + 1]")


def test_default_comfortable_scale_fits_window_and_chart_clicks_hit(page, app_url):
    bodies = []
    _load(page, app_url, bodies)
    assert page.evaluate("document.documentElement.dataset.uiScale") == "comfortable"
    assert page.evaluate("getComputedStyle(document.getElementById('root')).zoom") in ("1.125", "1.12")
    assert _fits(page) == [True, True]
    canvas = page.locator('.chart-card canvas').first
    expect(canvas).to_be_visible(timeout=10000)
    page.wait_for_timeout(600)
    # Screen position of bar "B" = canvas rect + chart pixel scaled by the zoom.
    point = page.evaluate("""() => {
      const host = [...document.querySelectorAll('.chart-card [_echarts_instance_]')][0];
      const inst = window.__studioEcharts && window.__studioEcharts.getInstanceByDom(host);
      if (!inst) return null;
      const [px, py] = inst.convertToPixel({seriesIndex: 0}, [1.5, 'B'])   // middle of bar B (value 3);
      const rect = host.getBoundingClientRect();
      const scale = rect.width / host.offsetWidth;
      return [rect.left + px * scale, rect.top + py * scale];
    }""")
    assert point, "chart instance not reachable"
    before = len(bodies)
    page.mouse.click(point[0], point[1])
    page.wait_for_timeout(900)
    later = bodies[before:]
    assert later and any(f.get("column") == "group" and f.get("values") == ["B"]
                         for f in later[-1]["filters"]), [b["filters"] for b in later]


def test_large_scale_is_selectable_and_persists(page, app_url):
    bodies = []
    _load(page, app_url, bodies)
    # Settings needs the full config; let it reach the real test server.
    page.route('**/api/config', lambda r: r.continue_())
    page.get_by_role('button', name='Settings', exact=True).click()
    page.get_by_label('Display size').select_option('large')
    assert page.evaluate("document.documentElement.dataset.uiScale") == "large"
    page.reload()
    assert page.evaluate("document.documentElement.dataset.uiScale") == "large"
    assert _fits(page) == [True, True]
    page.screenshot(path='/private/tmp/cohort-ui-large.png')


def _inside(page, selector):
    return page.evaluate("""s => { const r = document.querySelector(s).getBoundingClientRect();
      return r.left >= -1 && r.top >= -1 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1; }""", selector)


def test_narrow_screens_are_not_zoomed_and_tutorial_fits(page, app_url):
    page.set_viewport_size({"width": 500, "height": 800})
    bodies = []
    _load(page, app_url, bodies)
    assert page.evaluate("getComputedStyle(document.getElementById('root')).zoom") == "1"
    assert _fits(page) == [True, True]
    page.get_by_role("button", name="Tutorial", exact=True).click()
    expect(page.locator(".tutorial-dialog")).to_be_visible()
    assert _inside(page, ".tutorial-dialog")


def test_large_scale_drawer_and_dialog_stay_on_screen(page, app_url):
    page.add_init_script("localStorage.setItem('cohort-studio-ui-scale', 'large')")
    page.set_viewport_size({"width": 1280, "height": 640})
    bodies = []
    _load(page, app_url, bodies)
    page.get_by_role("button", name="Dataset settings").click()
    expect(page.get_by_role("dialog", name="Dataset settings")).to_be_visible()
    assert _inside(page, ".dataset-settings-drawer")
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Add data source").click()
    expect(page.get_by_role("dialog")).to_be_visible()
    assert _inside(page, "[aria-labelledby='add-source-title']")
