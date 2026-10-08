"""End-to-end: uvicorn serving the compiled React frontend, driven by
Playwright. Uses CSV upload, so no workspace/Aurora is needed."""

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
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(port)],
        cwd=APP_DIR, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError(proc.stdout.read().decode(errors="replace"))
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
    loaded_page.locator(".tab .quiet").click()
    expect(loaded_page.get_by_text("No data loaded")).to_be_visible(
        timeout=10000)


def test_settings_view_renders(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".topnav-link", has_text="Settings").click()
    expect(page.get_by_text("AI model").first).to_be_visible(timeout=10000)
    expect(page.get_by_text("MCP connections").first).to_be_visible()
    expect(page.get_by_text("Verily Workbench").first).to_be_visible()
    expect(page.get_by_text("bioRxiv preprints").first).to_be_visible()


def test_settings_provider_switch_shows_per_provider_key(
        page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".topnav-link", has_text="Settings").click()
    provider = page.locator(".settings-card select").first
    expect(provider).to_be_visible(timeout=10000)
    # Default provider is Anthropic; its key field label is shown.
    expect(page.get_by_text("Anthropic API key").first).to_be_visible()
    provider.select_option("openai")
    expect(page.get_by_text("OpenAI API key").first).to_be_visible()
    provider.select_option("gemini")
    expect(page.get_by_text("Gemini API key").first).to_be_visible()


def test_workflows_view_renders(page: Page, app_url: str):
    # The view mounts and shows the running-count hero plus a Refresh
    # button, whether or not a workspace (and `wb workflow`) is reachable.
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
    # no API key in the test server -> graceful error bubble
    expect(loaded_page.locator(".chat-bubble",
           has_text="Something went wrong")).to_be_visible(timeout=15000)


def test_save_to_aurora_control_opens(loaded_page: Page):
    loaded_page.get_by_role("button", name="Save to Aurora").click()
    expect(loaded_page.locator(".save-aurora input")).to_be_visible(
        timeout=10000)
    # no Aurora resource in the test workspace -> placeholder option shown
    expect(loaded_page.locator(".save-aurora select")).to_be_visible()



def test_settings_shows_palette_swatches(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".topnav-link", has_text="Settings").click()
    expect(page.get_by_text("Chart palette").first).to_be_visible(timeout=10000)
    expect(page.locator(".palette-swatch")).to_have_count(5)


def test_save_cohort_and_compare(loaded_page: Page):
    # Filter to liver, save it as a cohort, then compare current-vs-rest.
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
    # Ranked result table renders with a p-value column and a rin_score row.
    expect(panel.get_by_role("columnheader", name="p", exact=True)
           ).to_be_visible(timeout=10000)
    expect(panel.get_by_role("cell", name="rin_score")).to_be_visible()


def test_derive_column(loaded_page: Page):
    # Bin the numeric 'age' column into groups and confirm it's added.
    loaded_page.get_by_role("button", name="+ Derived column").click()
    panel = loaded_page.locator(".derive-panel")
    expect(panel).to_be_visible()
    panel.get_by_placeholder("e.g. age_group").fill("age_group")
    panel.get_by_role("button", name="Add column").click()
    expect(panel.get_by_text(re.compile(r'Added "age_group"'))).to_be_visible(
        timeout=10000)
    # the new column is now offered when adding a chart
    expect(loaded_page.locator('select[name="x"] option',
                               has_text="age_group")).to_have_count(1)


def test_change_chart_type(loaded_page: Page):
    # age is numeric → starts as a histogram; switch it to a bar in place
    # and confirm the query round-trip does not error.
    card = loaded_page.locator(".chart-card", has_text="age").first
    card.locator(".chart-kind").select_option("bar")
    expect(card.locator(".chart-kind")).to_have_value("bar", timeout=10000)
    expect(loaded_page.get_by_text(re.compile("Query failed"))
           ).to_have_count(0)


def test_categorical_chart_has_no_numeric_type_option(loaded_page: Page):
    # tissue is categorical: only "bar" is valid, so the type selector is
    # hidden entirely (a histogram would be a numeric-only cast).
    card = loaded_page.locator(".chart-card", has_text="tissue").first
    expect(card).to_be_visible()
    expect(card.locator(".chart-kind")).to_have_count(0)


def test_join_two_tabs_into_new_dataset(loaded_page: Page):
    # Load a second table that shares sample_id, then join the two.
    loaded_page.locator('input[type="file"]').set_input_files(PHENO_CSV)
    expect(loaded_page.locator(".tab", has_text="phenotypes.csv")
           ).to_be_visible(timeout=15000)
    loaded_page.locator(".tab-join").click()
    panel = loaded_page.locator(".join-panel")
    expect(panel).to_be_visible()
    # Keys default to the shared sample_id column; just run the join.
    panel.get_by_role("button", name=re.compile("Join")).click()
    # Merged tab carries both source names and the joined columns (bmi).
    expect(loaded_page.locator(".tab.active", has_text="+")
           ).to_be_visible(timeout=15000)
    expect(loaded_page.get_by_role("columnheader", name="bmi")
           ).to_be_visible(timeout=10000)


def test_export_pdf_downloads(loaded_page: Page):
    # Export PDF is fully client-side (charts live in the browser); assert
    # a real .pdf download is produced with non-empty bytes.
    with loaded_page.expect_download(timeout=20000) as dl:
        loaded_page.get_by_role("button", name="Export PDF").click()
    download = dl.value
    assert download.suggested_filename.endswith(".pdf")
    path = download.path()
    assert path and path.stat().st_size > 1000


def test_saved_views_section_present(loaded_page: Page):
    # Section renders; with no Aurora/S3 resource in the test workspace it
    # shows the "no store" message.
    expect(loaded_page.get_by_text("Saved views").first).to_be_visible()
    expect(loaded_page.get_by_text(
        "No Aurora or S3 resource").first).to_be_visible()
