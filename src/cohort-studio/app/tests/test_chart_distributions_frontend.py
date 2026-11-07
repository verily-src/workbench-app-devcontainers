"""Box plots, reference lines and axis number formats in the browser."""
import numpy as np
from playwright.sync_api import expect

from tests.test_chart_measures_frontend import WAIT, _rows, measured_page  # noqa: F401
from tests.test_e2e import app_url  # noqa: F401

AXIS_LABELS = """(el, axis) => window.__studioEcharts.getInstanceByDom(el).getModel()
  .getComponent(axis, 0).axis.getViewLabels().map(l => l.formattedLabel)"""


def _add(page, x, kind, y=None):
    page.locator('select[name="x"]').select_option(x)
    page.locator('select[name="kind"]').select_option(kind)
    if y:
        page.locator('select[name="y"]').select_option(y)
    page.locator('form[data-tutorial-target="add-chart"]').get_by_role("button", name="Add").click()


def test_box_plot_grouped_by_category_with_units(measured_page):
    page = measured_page
    df = _rows()
    _add(page, "rin_score", "box", y="tissue")
    card = page.locator(".chart-card", has_text="rin_score by tissue")
    plot = card.locator(".chart-plot")
    page.wait_for_function(WAIT % "o.series[0].type === 'boxplot'", arg=plot.element_handle())
    option = plot.evaluate("el => { const o = window.__studioEcharts.getInstanceByDom(el).getOption();"
                           " return { cats: o.xAxis[0].data, data: o.series[0].data }; }")
    assert option["cats"] == ["heart", "liver", "lung"]
    for tissue, box in zip(option["cats"], option["data"]):
        values = df[df.tissue == tissue].rin_score.to_numpy()
        q1, med, q3 = np.quantile(values, [0.25, 0.5, 0.75])
        inside = values[(values >= q1 - 1.5 * (q3 - q1)) & (values <= q3 + 1.5 * (q3 - q1))]
        assert np.allclose(box, [inside.min(), q1, med, q3, inside.max()])

    card.get_by_role("button", name="Edit axes").click()
    form = card.get_by_role("form", name="Chart axes")
    form.get_by_label("Y axis decimals").select_option("1")
    form.get_by_label("Y axis units").fill("RIN")
    expect(form.get_by_text("Shows 1,234.6 RIN")).to_be_visible()
    queries = []
    page.on("request", lambda r: queries.append(r.url) if r.url.endswith("/query") else None)
    form.get_by_role("button", name="Apply").click()
    expect(form).to_have_count(0)
    page.wait_for_timeout(400)
    labels = plot.evaluate(AXIS_LABELS, "yAxis")
    assert labels and all(label.endswith(" RIN") and "." in label for label in labels)
    assert not queries                      # formats are display only


def test_histogram_threshold_line_follows_a_parameter(measured_page):
    page = measured_page
    _add(page, "rin_score", "histogram")
    card = page.locator(".chart-card", has_text="rin_score").last
    plot = card.locator(".chart-plot")
    page.wait_for_function(WAIT % "o.series[0].type === 'bar'", arg=plot.element_handle())
    page.get_by_label("New parameter name").fill("cutoff")
    page.get_by_role("button", name="Add parameter").click()
    page.get_by_label("Parameter cutoff", exact=True).fill("6.5")

    card.get_by_role("button", name="Edit axes").click()
    form = card.get_by_role("form", name="Chart axes")
    form.get_by_role("button", name="+ Reference line").click()
    ref = form.get_by_role("group", name="Reference 1")
    expect(ref.get_by_label("Reference axis")).to_have_value("x")
    ref.get_by_label("Reference value").fill("6")
    ref.get_by_label("Reference parameter").select_option("cutoff")
    ref.get_by_label("Reference label").fill("RIN 6.5")
    form.get_by_role("button", name="+ Reference line").click()
    band = form.get_by_role("group", name="Reference 2")
    band.get_by_label("Reference axis").select_option("y")
    band.get_by_label("Reference value").fill("1")
    band.get_by_label("Reference band end").fill("2")
    form.get_by_role("button", name="Apply").click()
    expect(form).to_have_count(0)
    page.wait_for_function(WAIT % "o.series[0].markArea && o.series[o.series.length - 1].markLine", arg=plot.element_handle())
    placed = plot.evaluate("""el => {
      const chart = window.__studioEcharts.getInstanceByDom(el);
      const o = chart.getOption();
      const bins = o.xAxis[0].data.length;
      const line = o.series[o.series.length - 1].markLine.data[0];
      const px = (i) => chart.convertToPixel({ xAxisIndex: 0 }, i);
      return { line, band: o.series[0].markArea.data[0], bins, at: chart.convertToPixel({ xAxisIndex: 1 }, line.xAxis), left: px(0), right: px(bins - 1) };
    }""")
    assert placed["line"]["name"] == "RIN 6.5"
    assert placed["band"][0]["yAxis"] == 1 and placed["band"][1]["yAxis"] == 2
    lo, hi = 5.0, 9.9                                    # rin_score range in the fixture
    width = (placed["right"] - placed["left"]) / (placed["bins"] - 1)
    expected = placed["left"] - width / 2 + (6.5 - lo) / ((hi - lo) / placed["bins"]) * width
    assert abs(placed["at"] - expected) < 0.5                # x references sit at exact values

    page.get_by_label("Parameter cutoff", exact=True).fill("8")
    page.wait_for_function("""el => {
      const o = window.__studioEcharts.getInstanceByDom(el).getOption();
      return o.series[o.series.length - 1].markLine.data[0].xAxis === %s; }""" % (
        8), arg=plot.element_handle())
    page.get_by_role("button", name="Remove parameter cutoff").click()
    card.get_by_role("button", name="Edit axes").click()
    form = card.get_by_role("form", name="Chart axes")
    expect(form.get_by_role("group", name="Reference 1").get_by_label("Reference value")).to_have_value("8")


def test_line_histogram_references_align_and_band_parameters_survive_edits(measured_page):
    page = measured_page
    _add(page, "rin_score", "line")
    card = page.locator(".chart-card", has_text="rin_score").last
    plot = card.locator(".chart-plot")
    page.wait_for_function(WAIT % "o.series[0].type === 'line'", arg=plot.element_handle())
    page.get_by_label("New parameter name").fill("upper")
    page.get_by_role("button", name="Add parameter").click()
    page.get_by_label("Parameter upper", exact=True).fill("8")
    card.get_by_role("button", name="Edit axes").click()
    form = card.get_by_role("form", name="Chart axes")
    form.get_by_role("button", name="+ Reference line").click()
    ref = form.get_by_role("group", name="Reference 1")
    ref.get_by_label("Reference value").fill("6")
    ref.get_by_label("Reference band parameter").select_option("upper")
    form.get_by_role("button", name="Apply").click()
    page.wait_for_function(WAIT % "o.series[o.series.length - 1].markArea", arg=plot.element_handle())
    card.get_by_role("button", name="Edit axes").click()           # reopen and apply unchanged
    card.get_by_role("form", name="Chart axes").get_by_role("button", name="Apply").click()
    page.wait_for_timeout(300)
    out = plot.evaluate("""el => {
      const chart = window.__studioEcharts.getInstanceByDom(el);
      const o = chart.getOption();
      const lo = 5.0, width = (9.9 - 5.0) / o.xAxis[0].data.length;
      return { band: o.series[o.series.length - 1].markArea.data[0].map(p => p.xAxis),
               center: chart.convertToPixel({ xAxisIndex: 1 }, lo + width / 2), first: chart.convertToPixel({ xAxisIndex: 0 }, 0),
               lastCenter: chart.convertToPixel({ xAxisIndex: 1 }, 9.9 - width / 2),
               last: chart.convertToPixel({ xAxisIndex: 0 }, o.xAxis[0].data.length - 1) };
    }""")
    assert out["band"] == [6, 8]                                 # to_param kept through the editor
    assert abs(out["center"] - out["first"]) < 0.5 and abs(out["lastCenter"] - out["last"]) < 0.5


def test_box_tooltip_escapes_group_names(page, app_url, tmp_path):  # noqa: F811
    path = tmp_path / "html.csv"
    path.write_text("grp,v\n" + "".join(f"<img src=x onerror=window.__xss=1>,{i * 1.1:.1f}\nplain,{i * 1.3:.1f}\n" for i in range(15)))
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator('input[type="file"]').set_input_files(str(path))
    expect(page.locator(".hero .count", has_text="30")).to_be_visible(timeout=15000)
    _add(page, "v", "box", y="grp")
    card = page.locator(".chart-card", has_text="v by grp")
    plot = card.locator(".chart-plot")
    page.wait_for_function(WAIT % "o.series[0].type === 'boxplot'", arg=plot.element_handle())
    html = plot.evaluate("""el => {
      const chart = window.__studioEcharts.getInstanceByDom(el);
      const cats = chart.getOption().xAxis[0].data;
      const i = cats.findIndex(c => c.startsWith('<img'));
      return chart.getOption().tooltip[0].formatter({ dataIndex: i });
    }""")
    assert "&lt;img" in html and "<img" not in html
    assert not page.evaluate("window.__xss")
