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
