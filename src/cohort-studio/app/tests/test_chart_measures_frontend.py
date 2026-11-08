"""Chart measures and Split by in the browser: Add chart row, Marks menu, drawn series."""
import pandas as pd
import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url  # noqa: F401

WAIT = ("el => { const i = window.__studioEcharts.getInstanceByDom(el); const o = i && i.getOption();"
        " return Boolean(o && o.series && o.series.length && (%s)); }")
LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"]


def _rows() -> pd.DataFrame:
    rows = []
    for i in range(60):
        rows.append({"sample_id": f"S{i:03d}", "tissue": ["liver", "lung", "heart"][i % 3],
                     "sex": "F" if i % 4 else "M", "rin_score": round(5 + (i * 37 % 50) / 10, 1),
                     "year": 2020 + i % 4, "site": f"site{i % 9}"})
    return pd.DataFrame(rows)


@pytest.fixture
def measured_page(page: Page, app_url, tmp_path):  # noqa: F811
    path = tmp_path / "labs.csv"
    _rows().to_csv(path, index=False)
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator('input[type="file"]').set_input_files(str(path))
    expect(page.locator(".hero .count", has_text="60")).to_be_visible(timeout=15000)
    return page


def _option(card):
    return card.locator(".chart-plot").evaluate(
        "el => { const o = window.__studioEcharts.getInstanceByDom(el).getOption();"
        " return { series: o.series.map(s => ({ name: s.name, type: s.type, data: s.data, stack: s.stack,"
        " color: s.itemStyle && s.itemStyle.color })), legend: (o.legend || []).length,"
        " x: o.xAxis[0].data, y: o.yAxis[0].data }; }")


def _open_marks(card):
    button = card.get_by_role("button", name="Marks")
    if button.get_attribute("aria-expanded") != "true":
        button.click()


def _add_chart(page, x, measure, of=None, split=None, kind="auto"):
    page.locator('select[name="x"]').select_option(x)
    page.locator('select[name="kind"]').select_option(kind)
    page.get_by_label("New chart measure", exact=True).select_option(label=measure)
    if of:
        page.get_by_label("New chart measure field").select_option(of)
    if split:
        page.get_by_label("New chart split by").select_option(split)
    page.locator('form[data-tutorial-target="add-chart"]').get_by_role("button", name="Add").click()


def test_mean_measure_from_add_chart_then_split_by_in_marks(measured_page):
    page = measured_page
    df = _rows()
    _add_chart(page, "tissue", "Mean", of="rin_score")
    card = page.locator(".chart-card", has_text="Mean rin_score by tissue")
    expect(card).to_be_visible()
    page.wait_for_function(
        WAIT % "o.series[0].name === 'Mean rin_score'",
        arg=card.locator(".chart-plot").element_handle())
    option = _option(card)
    assert len(option["series"]) == 1          # no muted "all" overlay for a mean
    means = df.groupby("tissue").rin_score.mean()
    drawn = dict(zip(option["y"], option["series"][0]["data"]))
    for tissue, value in means.items():
        assert abs(drawn[tissue] - value) < 1e-9

    queries = []
    page.on("request", lambda r: queries.append(r.post_data_json) if r.url.endswith("/query") else None)
    _open_marks(card)
    marks = card.locator(".marks-menu .popover-panel")
    marks.get_by_label("Split by").select_option("sex")
    page.wait_for_function(
        WAIT % "o.series.length === 2",
        arg=card.locator(".chart-plot").element_handle())
    assert queries and queries[-1]["charts"][-1]["series"] == "sex"
    option = _option(card)
    assert [s["name"] for s in option["series"]] == ["F", "M"]
    assert [s["color"] for s in option["series"]] == LIGHT[:2]
    assert option["legend"] == 1
    female = df[df.sex == "F"].groupby("tissue").rin_score.mean()
    cats = option["y"]
    for tissue, value in female.items():
        assert abs(option["series"][0]["data"][cats.index(tissue)] - value) < 1e-9

    _open_marks(card)
    marks = card.locator(".marks-menu .popover-panel")
    expect(marks.get_by_role("radio", name="Pie")).to_be_disabled()
    marks.get_by_role("radio", name="Line").click()
    page.wait_for_function(
        WAIT % "o.series[0].type === 'line'",
        arg=card.locator(".chart-plot").element_handle())
    option = _option(card)
    assert option["x"] == ["heart", "liver", "lung"]   # lines read in natural order


def test_changed_measure_does_not_show_old_data_after_query_failure(measured_page):
    page = measured_page
    _add_chart(page, "tissue", "Mean", of="rin_score")
    card = page.locator(".chart-card", has_text="Mean rin_score by tissue")
    page.wait_for_function(WAIT % "o.series[0].name === 'Mean rin_score'",
                           arg=card.locator(".chart-plot").element_handle())
    page.route("**/api/datasets/*/query", lambda r: r.fulfill(status=500, json={"detail": "test failure"}))
    _open_marks(card)
    card.locator(".marks-menu .popover-panel").get_by_label("Split by").select_option("sex")
    expect(page.get_by_role("alert")).to_contain_text("test failure")
    page.wait_for_function("el => !(window.__studioEcharts.getInstanceByDom(el).getOption().series || []).length",
                           arg=card.locator(".chart-plot").element_handle())


def test_count_split_by_stacks_and_lines_sort_numeric_x(measured_page):
    page = measured_page
    df = _rows()
    _add_chart(page, "year", "Count rows", split="tissue", kind="column")
    card = page.locator(".chart-card", has_text="year, split by tissue")
    expect(card).to_be_visible()
    page.wait_for_function(
        WAIT % "o.series.length === 3",
        arg=card.locator(".chart-plot").element_handle())
    option = _option(card)
    assert option["x"] == ["2020", "2021", "2022", "2023"]
    counts = df.groupby(["year", "tissue"]).size()
    for s in option["series"]:
        assert s["type"] == "bar" and s["stack"] is None
        for year, value in zip(option["x"], s["data"]):
            assert value == counts.get((int(year), s["name"]), 0)
    _open_marks(card)
    card.locator(".marks-menu .popover-panel").get_by_label("Stack").check()
    page.wait_for_function(
        WAIT % "o.series[0].stack === 'total'",
        arg=card.locator(".chart-plot").element_handle())


def test_bad_add_chart_combination_explains(measured_page):
    page = measured_page
    _add_chart(page, "tissue", "Mean", of="rin_score", kind="pie")
    expect(page.get_by_role("alert")).to_contain_text("parts of a whole")


SLICE_POINT = """el => {
  const chart = window.__studioEcharts.getInstanceByDom(el);
  const data = chart.getModel().getSeriesByIndex(0).getData();
  const names = [...Array(data.count()).keys()].map(i => data.getName(i));
  const i = names.indexOf(%r);
  const l = data.getItemLayout(i);
  const a = (l.startAngle + l.endAngle) / 2, r = (l.r0 + l.r) / 2 || l.r * 0.6;
  const scale = el.getBoundingClientRect().width / el.clientWidth;
  return { names, x: (l.cx + r * Math.cos(a)) * scale, y: (l.cy + r * Math.sin(a)) * scale };
}"""


def test_folded_pie_slice_never_filters(measured_page):
    page = measured_page
    _add_chart(page, "site", "Sum", of="rin_score", kind="pie")
    card = page.locator(".chart-card", has_text="Sum of rin_score by site")
    expect(card).to_be_visible()
    plot = card.locator(".chart-plot")
    page.wait_for_function(WAIT % "o.series[0].type === 'pie'", arg=plot.element_handle())
    plot.scroll_into_view_if_needed()
    box = plot.bounding_box()
    point = plot.evaluate(SLICE_POINT % "Other")
    assert point["names"][-1] == "Other" and len(point["names"]) == 6
    page.mouse.click(box["x"] + point["x"], box["y"] + point["y"])
    page.wait_for_timeout(400)
    expect(page.locator(".chip", has_text="site:")).to_have_count(0)
    point = plot.evaluate(SLICE_POINT % point["names"][0])
    page.mouse.click(box["x"] + point["x"], box["y"] + point["y"])
    expect(page.locator(".chip", has_text=f"site: {point['names'][0]}")).to_be_visible()
