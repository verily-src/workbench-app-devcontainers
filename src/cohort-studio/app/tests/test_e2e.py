import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect
from tests.ui_helpers import menu

APP_DIR = Path(__file__).parent.parent
FIXTURE_CSV = Path(__file__).parent / "fixtures" / "samples.csv"
PHENO_CSV = Path(__file__).parent / "fixtures" / "phenotypes.csv"

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def app_url(tmp_path_factory):
    if not (APP_DIR / "static" / "index.html").exists():
        pytest.skip("frontend not built — run `npm run build` in web/ "
                    "and copy dist to app/static")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ)
    env["LINEAGE_DB"] = str(tmp_path_factory.mktemp("lineage") / "l.db")
    # Log to a file, not a pipe: nothing drains a pipe while tests run, and a
    # full pipe blocks the server on its next log write.
    log_path = tmp_path_factory.mktemp("uvicorn") / "server.log"
    log = open(log_path, "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
        cwd=APP_DIR, env=env,
        stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except Exception:
            if proc.poll() is not None:
                log.close()
                raise RuntimeError(log_path.read_text(errors="replace"))
            time.sleep(0.3)
    else:
        proc.kill()
        raise RuntimeError("uvicorn did not come up in 30s")
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
    log.close()


@pytest.fixture
def loaded_page(page: Page, app_url: str) -> Page:
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator('input[type="file"]').set_input_files(FIXTURE_CSV)
    expect(page.get_by_text(re.compile(r"of 100 rows"))).to_be_visible(
        timeout=15000)
    return page


def test_serves_empty_state(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("Cohort Studio")).to_be_visible(timeout=15000)
    expect(page.get_by_text("No data loaded")).to_be_visible()


def test_upload_opens_tab_with_charts_and_rows(loaded_page: Page):
    expect(loaded_page.locator(".tab.active", has_text="samples.csv")
           ).to_be_visible()
    expect(loaded_page.locator(".chart-card").first).to_be_visible()
    expect(loaded_page.locator(".chart-card", has_text="tissue")
           ).to_be_visible()
    expect(loaded_page.get_by_role("cell", name="GTEX-0000")).to_be_visible()


def test_sidebar_filter_updates_counts_and_chips(loaded_page: Page):
    group = loaded_page.locator(".filter-group", has_text="tissue")
    group.locator("summary").click()
    group.get_by_label("liver").check()
    expect(loaded_page.locator(".hero .count", has_text="25")
           ).to_be_visible(timeout=10000)
    chip = loaded_page.locator(".chip", has_text="tissue: liver")
    expect(chip).to_be_visible()
    chip.click()
    expect(loaded_page.locator(".hero .count", has_text="100")
           ).to_be_visible(timeout=10000)


def test_add_and_remove_chart(loaded_page: Page):
    loaded_page.locator('select[name="x"]').select_option("age")
    loaded_page.get_by_role("button", name="Add", exact=True).click()
    cards = loaded_page.locator(".chart-card", has_text="age")
    expect(cards.last).to_be_visible(timeout=10000)
    before = loaded_page.locator(".chart-card").count()
    cards.last.get_by_title("Remove chart").click()
    expect(loaded_page.locator(".chart-card")).to_have_count(before - 1)


def test_close_tab_returns_to_empty_state(loaded_page: Page):
    loaded_page.locator(".tab").get_by_role(
        "button", name="✕", exact=True).click()
    expect(loaded_page.get_by_text("No data loaded")).to_be_visible(
        timeout=10000)


def test_command_palette_navigates(loaded_page: Page):

    loaded_page.keyboard.press("Control+k")
    palette = loaded_page.locator(".palette")
    expect(palette).to_be_visible()
    palette.locator(".palette-input").fill("Lineage")
    loaded_page.keyboard.press("Enter")
    expect(palette).not_to_be_visible()
    expect(loaded_page.get_by_text("lineage events").first).to_be_visible(
        timeout=10000)


    loaded_page.get_by_title("Command palette").click()
    expect(loaded_page.locator(".palette")).to_be_visible()
    loaded_page.locator(".palette-input").fill("samples")
    expect(loaded_page.locator(".palette-item", has_text="samples.csv").first
           ).to_be_visible()


def test_settings_view_renders(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Settings", exact=True).click()
    expect(page.get_by_text("AI model").first).to_be_visible(timeout=10000)
    expect(page.get_by_text("MCP connections").first).to_be_visible()
    expect(page.get_by_text("Verily Workbench").first).to_be_visible()
    expect(page.get_by_text("bioRxiv preprints").first).to_be_visible()


def test_settings_provider_switch_shows_per_provider_key(
        page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Settings", exact=True).click()
    provider = page.locator(".settings-card select").first
    expect(provider).to_be_visible(timeout=10000)

    expect(page.get_by_text("Anthropic API key").first).to_be_visible()
    provider.select_option("openai")
    expect(page.get_by_text("OpenAI API key").first).to_be_visible()
    provider.select_option("gemini")
    expect(page.get_by_text("Gemini API key").first).to_be_visible()


def test_workflows_view_renders(page: Page, app_url: str):


    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".topnav-link", has_text="Workflows").click()
    expect(page.get_by_text("workflow job(s) running")).to_be_visible(
        timeout=10000)
    expect(page.get_by_role("button", name="Refresh")).to_be_visible()


def test_lineage_view_records_upload(loaded_page: Page):
    loaded_page.locator(".topnav-link", has_text="Lineage").click()
    expect(loaded_page.get_by_text("lineage events").first).to_be_visible(
        timeout=10000)
    expect(loaded_page.get_by_text("csv_uploaded").first).to_be_visible()


def test_chat_widget_opens_and_reports_unconfigured(loaded_page: Page):
    loaded_page.locator(".chat-launcher").click()
    expect(loaded_page.get_by_text("Data assistant")).to_be_visible(
        timeout=10000)
    box = loaded_page.locator(".chat-input input")
    box.fill("what is the mean rin score?")
    box.press("Enter")

    expect(loaded_page.locator(".chat-bubble",
           has_text="Something went wrong")).to_be_visible(timeout=15000)


def test_save_to_aurora_control_opens(loaded_page: Page):
    menu(loaded_page, "Export options").get_by_role("button", name="Save to Aurora").click()
    expect(loaded_page.locator(".save-aurora input")).to_be_visible(
        timeout=10000)

    expect(loaded_page.locator(".save-aurora select")).to_be_visible()
    # Closing the Export menu keeps the form: reopening shows what was typed.
    loaded_page.locator(".save-aurora input").fill("kept_table_name")
    loaded_page.keyboard.press("Escape")
    expect(loaded_page.locator(".save-aurora input")).to_be_hidden()
    menu(loaded_page, "Export options")
    expect(loaded_page.locator(".save-aurora input")).to_have_value("kept_table_name")



def test_settings_shows_palette_swatches(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.get_by_role("button", name="Settings", exact=True).click()
    expect(page.get_by_text("Chart palette").first).to_be_visible(timeout=10000)
    expect(page.locator(".palette-swatch")).to_have_count(5)


def test_save_cohort_and_compare(loaded_page: Page):

    group = loaded_page.locator(".filter-group", has_text="tissue")
    group.locator("summary").click()
    group.get_by_label("liver").check()
    expect(loaded_page.locator(".hero .count", has_text="25")).to_be_visible(
        timeout=10000)

    loaded_page.locator(".cohort-name").fill("livers")
    loaded_page.get_by_role("button", name="Save cohort").click()
    expect(loaded_page.locator(".cohort-chip", has_text="livers")
           ).to_be_visible()

    loaded_page.get_by_role("button", name="Compare groups").click()
    panel = loaded_page.locator(".compare-panel")
    expect(panel).to_be_visible()
    panel.get_by_role("button", name="Compare", exact=True).click()

    expect(panel.get_by_role("columnheader", name="p", exact=True)
           ).to_be_visible(timeout=10000)
    expect(panel.get_by_role("cell", name="rin_score")).to_be_visible()


def test_derive_column(loaded_page: Page):

    menu(loaded_page, "Add to this view").get_by_role("button", name="+ Calculated field").click()
    panel = loaded_page.locator(".derive-panel")
    expect(panel).to_be_visible()
    panel.get_by_placeholder("e.g. age_group").fill("age_group")
    panel.get_by_role("button", name="Add column").click()
    expect(panel.get_by_text(re.compile(r'Added "age_group"'))).to_be_visible(
        timeout=10000)

    expect(loaded_page.locator('select[name="x"] option',
                               has_text="age_group")).to_have_count(1)


def test_launch_workflow_panel_opens(loaded_page: Page):


    loaded_page.get_by_role("button", name="Run workflow ▸").click()
    panel = loaded_page.locator(".launch-panel")
    expect(panel).to_be_visible()
    expect(panel.get_by_text("Run workflow on cohort")).to_be_visible()
    expect(panel.get_by_role("button", name="Submit job")).to_be_visible()


def _mark(card, label):
    """Open the chart's Marks menu and pick a mark type."""
    card.get_by_role("button", name="Marks").click()
    card.get_by_role("radio", name=label, exact=True).click()


def test_change_chart_type(loaded_page: Page):
    card = loaded_page.locator(".chart-card", has_text="age").first
    _mark(card, "Bar")
    expect(card.locator(".chart-plot")).to_have_attribute("data-chart-style", "bar", timeout=10000)
    expect(card.get_by_role("button", name="Marks")).to_contain_text("Bar")
    expect(loaded_page.get_by_text(re.compile("Query failed"))).to_have_count(0)


def test_categorical_chart_has_no_numeric_type_option(loaded_page: Page):
    card = loaded_page.locator(".chart-card", has_text="tissue").first
    expect(card).to_be_visible()
    card.get_by_role("button", name="Marks").click()
    types = card.get_by_role("radiogroup", name="Mark type")
    enabled = [b.inner_text() for b in types.get_by_role("radio").all() if b.is_enabled()]
    assert enabled == ["Automatic", "Bar", "Column", "Line", "Area", "Pie", "Donut"]
    expect(types.get_by_role("radio", name="Circle")).to_have_attribute(
        "title", "Circle needs two numeric fields.")


def test_chart_styles_redraw_without_requery(loaded_page: Page):
    queries = []
    loaded_page.on("request", lambda r: "/query" in r.url and queries.append(r.url))
    card = loaded_page.locator(".chart-card", has_text="tissue").first
    plot = card.locator(".chart-plot")
    expect(plot).to_have_attribute("data-chart-style", "bar")
    for label, style in (("Column", "column"), ("Line", "line"), ("Area", "area"),
                         ("Pie", "pie"), ("Donut", "donut")):
        _mark(card, label)
        expect(plot).to_have_attribute("data-chart-style", style)
        expect(card.get_by_role("button", name="Marks")).to_contain_text(label)
    loaded_page.wait_for_timeout(500)
    assert queries == []  # a mark type on the same data only changes the drawing
    # Numeric columns draw line and area over histogram bins.
    age = loaded_page.locator(".chart-card", has_text="age").first
    _mark(age, "Area")
    expect(age.locator(".chart-plot")).to_have_attribute("data-chart-style", "area")
    # Clicking a pie slice still filters by that category.
    _mark(card, "Pie")
    box = plot.bounding_box()
    loaded_page.wait_for_timeout(1200)  # let the pie finish animating
    point = plot.evaluate("""(el) => {
        const chart = window.__studioEcharts.getInstanceByDom(el);
        const layout = chart.getModel().getSeriesByIndex(0).getData().getItemLayout(0);
        const angle = (layout.startAngle + layout.endAngle) / 2, r = (layout.r0 + layout.r) / 2 || layout.r / 2;
        return [layout.cx + r * Math.cos(angle), layout.cy + r * Math.sin(angle)];
    }""")
    loaded_page.mouse.click(box["x"] + point[0], box["y"] + point[1])
    expect(loaded_page.locator(".chips .chip").first).to_contain_text("tissue", timeout=10000)


def test_mark_color_size_and_labels(loaded_page: Page):
    card = loaded_page.locator(".chart-card", has_text="tissue").first
    _mark(card, "Column")
    card.get_by_role("button", name="Marks").click()
    card.get_by_role("button", name="Color #eb6834").click()
    card.get_by_role("radio", name="L", exact=True).click()
    card.get_by_label("Show values").check()
    series = card.locator(".chart-plot").evaluate("""(el) => {
        const s = window.__studioEcharts.getInstanceByDom(el).getOption().series;
        return s.map((x) => ({ name: x.name, color: x.itemStyle && x.itemStyle.color,
                               max: x.barMaxWidth, label: Boolean(x.label && x.label.show) }));
    }""")
    selected = [x for x in series if x["name"] != "all"][0]
    assert selected["color"] == "#eb6834" and selected["max"] == 34 and selected["label"] is True
    assert all(not x["label"] for x in series if x["name"] == "all")


def test_add_chart_with_line_style(loaded_page: Page):
    form = loaded_page.locator("form", has=loaded_page.get_by_text("Add chart"))
    form.locator('select[name="x"]').select_option("tissue")
    form.locator('select[name="kind"]').select_option("line")
    form.get_by_role("button", name="Add").click()
    card = loaded_page.locator(".chart-card").last
    expect(card.locator(".chart-plot")).to_have_attribute("data-chart-style", "line")
    expect(card.get_by_role("button", name="Marks")).to_contain_text("Line")


def test_join_two_tabs_into_new_dataset(loaded_page: Page):

    loaded_page.locator('input[type="file"]').set_input_files(PHENO_CSV)
    expect(loaded_page.locator(".tab", has_text="phenotypes.csv")
           ).to_be_visible(timeout=15000)
    loaded_page.locator(".tab-join").click()
    panel = loaded_page.locator(".join-panel")
    expect(panel).to_be_visible()
    panel.get_by_label("Left key step 1 condition 1").select_option("sample_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("sample_id")

    panel.get_by_role("button", name="Join into new tab").click()

    expect(loaded_page.locator(".tab.active", has_text="+")
           ).to_be_visible(timeout=15000)
    expect(loaded_page.get_by_role("columnheader", name="bmi")
           ).to_be_visible(timeout=10000)


def test_join_preview_shows_funnel_and_sample(loaded_page: Page):
    loaded_page.locator('input[type="file"]').set_input_files(PHENO_CSV)
    expect(loaded_page.locator(".tab", has_text="phenotypes.csv")
           ).to_be_visible(timeout=15000)
    loaded_page.locator(".tab-join").click()
    panel = loaded_page.locator(".join-panel")
    panel.get_by_label("Left key step 1 condition 1").select_option("sample_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("sample_id")
    panel.get_by_role("radio", name="No match").click()
    panel.get_by_role("button", name="Preview").click()
    funnel = panel.locator(".join-funnel")
    expect(funnel).to_contain_text("no match", timeout=10000)
    expect(panel.locator(".join-sample th").first).to_have_text("sample_id")


def test_join_table_combobox_and_inline_validation(loaded_page: Page):
    loaded_page.locator('input[type="file"]').set_input_files(PHENO_CSV)
    expect(loaded_page.locator(".tab", has_text="phenotypes.csv")
           ).to_be_visible(timeout=15000)
    loaded_page.locator(".tab-join").click()
    panel = loaded_page.locator(".join-panel")
    expect(panel.locator(".join-engine")).to_have_text("runs in memory",
                                                       timeout=10000)


    combo = panel.get_by_role("combobox", name="Table to join in step 1")
    combo.click()
    combo.fill("zzz")
    expect(panel.get_by_role("listbox")).to_contain_text("No matches")
    combo.press("Escape")
    expect(panel.get_by_role("listbox")).to_have_count(0)
    combo.fill("pheno")
    expect(panel.get_by_role("option", name=re.compile("phenotypes.csv"))
           ).to_be_visible()
    combo.press("Enter")
    expect(combo).to_have_value("phenotypes.csv")

    panel.get_by_label("Left key step 1 condition 1").select_option("sample_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("sample_id")

    cond = panel.locator(".join-cond").first
    cond.locator("select").nth(0).select_option("rin_score")
    cond.locator("select.join-op").select_option("<")
    expect(panel.locator(".join-check.join-error")).to_contain_text(
        "can't compare", timeout=10000)
    expect(panel.get_by_role("button", name="Join into new tab")).to_be_disabled()
    cond.locator("select.join-op").select_option("=")
    expect(panel.locator(".join-check.settings-hint")).to_contain_text(
        "compared as text", timeout=10000)
    expect(panel.get_by_role("button", name="Join into new tab")).to_be_enabled()


def test_export_pdf_downloads(loaded_page: Page):


    with loaded_page.expect_download(timeout=20000) as dl:
        menu(loaded_page, "Export options").get_by_role("button", name="Export PDF").click()
    download = dl.value
    assert download.suggested_filename.endswith(".pdf")
    path = download.path()
    assert path and path.stat().st_size > 1000


def test_saved_views_section_present(loaded_page: Page):


    expect(loaded_page.get_by_text("Saved views").first).to_be_visible()
    # Only an uploaded file is open, so nothing is saveable yet.
    expect(loaded_page.get_by_text(
        "Uploaded files can't be saved").first).to_be_visible()
    expect(loaded_page.get_by_text("No saved views.")).to_be_visible()
