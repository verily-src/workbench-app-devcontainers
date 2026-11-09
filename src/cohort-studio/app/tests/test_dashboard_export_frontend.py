"""Dashboard PNG/PDF export, per-chart PNG and the viewer-mode share link."""
import base64
import re
import struct
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url, loaded_page  # noqa: F401
from tests.ui_helpers import menu

pytestmark = pytest.mark.e2e

OUT = Path("/private/tmp")

# Record canvas text and images so tests can read what the export drew.
RECORD = """
(() => {
  window.__texts = []; window.__images = [];
  const P = CanvasRenderingContext2D.prototype;
  const fill = P.fillText, draw = P.drawImage;
  P.fillText = function (text, ...rest) { window.__texts.push(String(text)); return fill.call(this, text, ...rest); };
  P.drawImage = function (img, ...rest) {
    if (img instanceof HTMLImageElement) window.__images.push(img.src.slice(0, 80));
    return draw.call(this, img, ...rest);
  };
})();
"""


def _png_size(data: bytes):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def _pixels(page: Page, data: bytes, accent: str):
    return page.evaluate("""async ([b64, accent]) => {
      const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
      const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
      const ctx = c.getContext('2d'); ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      const hex = [1, 3, 5].map(i => parseInt(accent.slice(i, i + 2), 16));
      const bg = [d[0], d[1], d[2]];
      let other = 0, hits = 0;
      for (let i = 0; i < d.length; i += 4) {
        if (Math.abs(d[i] - bg[0]) + Math.abs(d[i + 1] - bg[1]) + Math.abs(d[i + 2] - bg[2]) > 24) other++;
        if (Math.abs(d[i] - hex[0]) + Math.abs(d[i + 1] - hex[1]) + Math.abs(d[i + 2] - hex[2]) < 18) hits++;
      }
      return { corner: bg, other, accent: hits, total: d.length / 4 };
    }""", [base64.b64encode(data).decode(), accent])


def _pdf_images_per_page(pdf: bytes):
    contents = re.findall(rb"/Type\s*/Page\b(?:(?!endobj).)*?/Contents\s+(\d+)\s+0\s+R", pdf, re.S)
    out = []
    for number in contents:
        stream = re.search(rb"(?m)^" + number + rb"\s+0\s+obj\b(.*?)endobj", pdf, re.S)
        assert stream
        out.append(len(re.findall(rb"/I\d+\s+Do", stream.group(1))))
    return out


def _download(page: Page, click, name: str) -> bytes:
    with page.expect_download(timeout=30000) as download:
        click()
    path = OUT / name
    download.value.save_as(path)
    return path.read_bytes()


def _settled(page: Page):
    expect(page.locator(".chart-grid .chart-card canvas").first).to_be_visible(timeout=10000)
    page.wait_for_timeout(1200)


def test_dashboard_png_pdf_and_chart_png(loaded_page: Page):
    page = loaded_page
    page.add_init_script(RECORD)
    page.evaluate(RECORD)
    group = page.locator(".filter-group", has_text="tissue")
    group.locator("summary").click()
    group.get_by_label("liver").check()
    expect(page.locator(".hero .count", has_text="25")).to_be_visible(timeout=10000)
    page.get_by_label("Charts per row").select_option("2")
    _settled(page)
    cards = page.locator(".chart-grid .chart-card").count()
    assert cards >= 2
    grid_w, grid_h = page.evaluate("[document.querySelector('.chart-grid').offsetWidth,"
                                   " document.querySelector('.chart-grid').offsetHeight]")

    menu(page, "Export options")
    data = _download(page, lambda: page.get_by_role("button", name="Dashboard PNG").click(),
                     "cohort-dashboard.png")
    width, height = _png_size(data)
    assert width == 2 * max(grid_w + 48, 640)
    assert height > 2 * grid_h + 200
    pixels = _pixels(page, data, "#087a6a")
    assert pixels["corner"] == [250, 250, 250]
    assert pixels["other"] > pixels["total"] * 0.08
    assert pixels["accent"] > 500
    texts = page.evaluate("window.__texts")
    assert "Filters: tissue: liver" in texts
    assert "25 of 100 rows · in memory" in texts
    assert "samples.csv" in texts and texts.count("samples.csv") == 1
    assert any(t.startswith("Generated ") for t in texts)
    assert "Cohort Browser" in texts
    titles = page.locator(".chart-grid .chart-card .head .title").all_inner_texts()
    assert all(any(t.startswith(title.strip()[:20]) for t in texts) for title in titles)

    menu(page, "Export options")
    pdf = _download(page, lambda: page.get_by_role("button", name="Dashboard PDF").click(),
                    "cohort-dashboard.pdf")
    assert pdf.startswith(b"%PDF-")
    first = _pdf_images_per_page(pdf)
    assert first and set(first) == {1}
    assert f"(1 / {len(first)})".encode() in pdf

    # One chart per row with more charts runs over several landscape pages, one slice image each.
    page.get_by_label("Charts per row").select_option("1")
    for column in ("age", "rin_score"):
        page.locator('select[name="x"]').select_option(column)
        page.locator('[data-tutorial-target="add-chart"]').get_by_role("button", name="Add", exact=True).click()
    expect(page.locator(".chart-grid .chart-card")).to_have_count(cards + 2, timeout=10000)
    _settled(page)
    menu(page, "Export options")
    pdf = _download(page, lambda: page.get_by_role("button", name="Dashboard PDF").click(),
                    "cohort-dashboard-pages.pdf")
    pages = _pdf_images_per_page(pdf)
    assert len(pages) > len(first) and set(pages) == {1}
    assert f"(1 / {len(pages)})".encode() in pdf
    assert b"/MediaBox [0 0 841.89 595.28]" in pdf or b"/MediaBox [0 0 792. 612.]" in pdf

    card = page.locator(".chart-grid .chart-card").first
    card_w = page.evaluate("document.querySelector('.chart-grid .chart-card').offsetWidth")
    card.get_by_role("button", name="Chart actions").click()
    data = _download(page, lambda: card.get_by_role("button", name="Download PNG").click(), "cohort-chart.png")
    width, _ = _png_size(data)
    assert width == 2 * max(card_w + 48, 640)
    assert _pixels(page, data, "#087a6a")["accent"] > 200
    assert "Filters: tissue: liver" in page.evaluate("window.__texts")


def test_dark_theme_export(loaded_page: Page):
    page = loaded_page
    page.evaluate(RECORD)
    page.evaluate("document.documentElement.setAttribute('data-theme', 'dark')")
    _settled(page)
    menu(page, "Export options")
    data = _download(page, lambda: page.get_by_role("button", name="Dashboard PNG").click(),
                     "cohort-dashboard-dark.png")
    pixels = _pixels(page, data, "#087a6a")
    assert pixels["corner"] == [23, 27, 32]
    assert pixels["other"] > pixels["total"] * 0.1
    assert "Filters: none (full cohort)" in page.evaluate("window.__texts")


NAME = "Liver report"
COLUMNS = [{"name": "group", "dtype": "object", "filter_kind": "categorical", "values": ["A", "B"]}]


def test_viewer_mode_exports_and_copies_revision_link(page: Page, app_url: str):
    state = {"version": 2, "active": 0, "datasets": [{
        "source": {"kind": "aurora", "resource_id": "db-main", "table": "person"},
        "title": "Report", "filters": [], "cohorts": [], "parameters": [],
        "charts": [{"kind": "bar", "x": "group"}]}]}
    rev = {"name": NAME, "revision": 3, "published_at": "2026-11-03T10:00:00+00:00",
           "published_by": "analyst@example.org", "note": None}

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda r: fulfill(r, {
        "ready": True, "catalogs_pending": False,
        "sources": [{"kind": "aurora", "id": "db-main", "label": "Clinical database"}]}))
    page.route("**/api/workflows**", lambda r: fulfill(r, {"available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda r: fulfill(r, {"views": [], "unavailable": [], "pending": []}))
    page.route("**/api/views/revision**", lambda r: fulfill(r, {**state, "published": rev}))
    page.route("**/api/data-jobs/open", lambda r: fulfill(r, {
        "job_id": "open", "status": "complete", "result": {
            "dataset_id": "report-ds", "source": "person", "rows": 8, "columns": COLUMNS,
            "source_ref": r.request.post_data_json["source_ref"], "query_scope": "database"}}))
    page.route("**/api/datasets/report-ds/query", lambda r: fulfill(r, {
        "total": 8, "filtered": 8, "scope": "database", "sampled": False, "entity": None, "cache": None,
        "charts": [{"kind": "bar", "x": "group", "sampled": True, "data": [
            {"category": "A", "all": 5, "selected": 5}, {"category": "B", "all": 3, "selected": 3}]}],
        "rows": {"page": 0, "page_size": 50, "columns": ["group"], "data": [["A"]]}}))
    page.add_init_script(RECORD)
    page.add_init_script("""Object.defineProperty(navigator, "clipboard", { configurable: true,
      value: { writeText: async (text) => { window.__copied = text; } } })""")
    page.goto(f"{app_url}/#view=aurora:db-main:Liver%20report&published")
    expect(page.get_by_role("status", name="Published view")).to_contain_text("rev 3", timeout=15000)
    _settled(page)

    menu(page, "Export options")
    page.get_by_role("button", name="Copy link · rev 3").click()
    assert page.evaluate("window.__copied").endswith("#view=aurora:db-main:Liver%20report&rev=3")
    expect(page.get_by_text("Link copied. It opens published rev 3")).to_be_visible()
    page.screenshot(path=str(OUT / "viewer-export-menu.png"))
    data = _download(page, lambda: page.get_by_role("button", name="Dashboard PNG").click(), "viewer-dashboard.png")
    assert _png_size(data)[0] >= 1280
    texts = page.evaluate("window.__texts")
    assert "person · published rev 3" in texts
    assert "8 rows · full database" in texts
    assert "Note: Charts marked Sampled use sampled data." in texts and "Sampled" in texts

    card = page.locator(".chart-grid .chart-card").first
    card.get_by_role("button", name="Chart actions").click()
    data = _download(page, lambda: card.get_by_role("button", name="Download PNG").click(), "viewer-chart.png")
    assert _pixels(page, data, "#087a6a")["accent"] > 200

    # After a failed query the charts are stale, so image exports wait for a good result.
    page.unroute("**/api/datasets/report-ds/query")
    page.route("**/api/datasets/report-ds/query", lambda r: r.fulfill(status=500, json={"detail": "boom"}))
    page.get_by_role("button", name="Refresh data").click()
    expect(page.locator(".query-error")).to_contain_text("Showing the last successful result", timeout=10000)
    menu(page, "Export options")
    expect(page.get_by_role("button", name="Dashboard PNG")).to_be_disabled()
    expect(page.get_by_role("button", name="Dashboard PDF")).to_be_disabled()
    card.get_by_role("button", name="Chart actions").click()
    expect(card.get_by_role("button", name="Download PNG")).to_be_disabled()


def test_very_long_dashboard_png_stays_within_canvas_limits(loaded_page: Page):
    page = loaded_page
    page.get_by_label("Charts per row").select_option("1")
    page.add_style_tag(content=".chart-grid .chart-plot { height: 6000px !important; }")
    _settled(page)
    grid_w, grid_h = page.evaluate("[document.querySelector('.chart-grid').offsetWidth,"
                                   " document.querySelector('.chart-grid').offsetHeight]")
    assert grid_h > 16000
    menu(page, "Export options")
    data = _download(page, lambda: page.get_by_role("button", name="Dashboard PNG").click(),
                     "cohort-dashboard-long.png")
    width, height = _png_size(data)
    assert height <= 32000 and width * height <= 250e6
    assert width < 2 * (grid_w + 48)
    # The last chart is drawn, not cut off or blank.
    tail = page.evaluate("""async (b64) => {
      const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
      const c = document.createElement('canvas'); c.width = img.width; c.height = 400;
      const ctx = c.getContext('2d'); ctx.drawImage(img, 0, img.height - 1200, img.width, 400, 0, 0, img.width, 400);
      const d = ctx.getImageData(0, 0, c.width, 400).data; let n = 0;
      for (let i = 0; i < d.length; i += 4) if (d[i] < 200) n++;
      return n; }""", base64.b64encode(data).decode())
    assert tail > 100
