import re
import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url, loaded_page

pytestmark = pytest.mark.e2e


def set_explore_view(page: Page, mode: str):
    page.get_by_role("button", name="OMOP" if mode == "omop" else "Tables",
                     exact=True).click()


def expect_explore_view(page: Page, mode: str):
    expect(page.get_by_role("button", name="OMOP" if mode == "omop" else "Tables",
                            exact=True)).to_have_attribute("aria-pressed", "true")


def test_entity_count_and_column_settings(loaded_page: Page):
    loaded_page.set_viewport_size({"width": 2048, "height": 1100})
    entity = loaded_page.locator(".entity-select select")
    select_box = entity.bounding_box()
    export_box = loaded_page.get_by_role("button", name="Export TSV", exact=True).bounding_box()
    assert select_box and export_box
    assert abs(select_box["y"] + select_box["height"] / 2 - export_box["y"] - export_box["height"] / 2) < 2
    entity.select_option("sample_id")
    expect(loaded_page.locator(".hero .count")).to_have_text("100", timeout=10000)
    expect(loaded_page.locator(".hero .detail")).to_contain_text(
        "unique sample_id", timeout=10000)

    loaded_page.get_by_role("button", name="Column settings").click()
    row = loaded_page.locator(".column-setting-row").filter(has_text="tissue")
    row.locator("label", has_text="Label").locator("input").fill("Tissue")
    row.locator("label", has_text="Filter").locator("select").select_option("none")
    loaded_page.get_by_role("button", name="Save column settings").click()

    expect(loaded_page.get_by_role("columnheader", name="Tissue")).to_be_visible(
        timeout=10000)
    expect(loaded_page.locator(".filter-group", has_text="Tissue")).to_have_count(0)


def test_database_scope_compare_derive_cache_and_chat_guard(page: Page, app_url: str):
    query_refreshes = []
    refresh_complete = False
    hold_refresh = False
    pending_refresh = []
    saved_view = {}
    columns = [
        {"name": "person_id", "dtype": "int64", "filter_kind": "none"},
        {"name": "age", "dtype": "float64", "logical_type": "number",
         "filter_kind": "range", "min": 20, "max": 80},
    ]
    source_ref = {"kind": "aurora", "resource_id": "fixture",
                  "table": "person", "schema": "public"}

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "fixture", "label": "Fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "person", "detail": "2 rows"},
    ]))
    page.route("**/api/datasets/open", lambda route: fulfill(route, {
        "dataset_id": "database-person", "source": "fixture / person",
        "rows": 2, "columns": columns, "source_ref": source_ref,
        "query_scope": "database",
    }))

    def query(route):
        nonlocal refresh_complete
        body = route.request.post_data_json
        refresh = body.get("refresh", False)
        query_refreshes.append(refresh)
        if refresh:
            refresh_complete = True
        entity = body.get("entity_column")
        response = {
            "total": 100001, "filtered": 100001, "scope": "database", "sampled": False,
            "entity": ({"column": entity, "total": 2, "filtered": 2}
                       if entity else None),
            "cache": {"hit": bool(refresh_complete and not refresh),
                      "as_of": ("2026-10-21T12:02:00Z" if refresh_complete
                                else "2026-10-21T12:00:00Z"),
                      "ttl_seconds": 30},
            "charts": [], "rows": {"page": 0, "page_size": 50,
                                    "columns": [c["name"] for c in columns],
                                    "data": [[1, 50], [2, 60]]},
        }
        if refresh:
            response["columns"] = columns
        if refresh and hold_refresh:
            pending_refresh.append((route, response))
        else:
            fulfill(route, response)

    page.route("**/api/datasets/database-person/query", query)
    page.route("**/api/datasets/database-person/compare", lambda route: fulfill(route, {
        "a_n": 2, "b_n": 1, "n_overlap": 0, "results": [],
    }))

    derived_source = {"kind": "derived", "base": source_ref,
                      "spec": {"op": "bin", "name": "age_group", "column": "age",
                               "breaks": [0, 18, 65, 120]}}

    def derive(route):
        nonlocal columns
        columns = [*columns, {"name": "age_group", "dtype": "object",
                             "filter_kind": "categorical", "values": ["adult"]}]
        fulfill(route, {"name": "age_group", "rows": 2, "columns": columns,
                        "source_ref": derived_source, "query_scope": "database"})

    page.route("**/api/datasets/database-person/derive", derive)

    def views(route):
        if route.request.method == "POST":
            saved_view.update(route.request.post_data_json)
            fulfill(route, {"name": saved_view["name"]})
        else:
            fulfill(route, [])

    page.route("**/api/views**", views)
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".sidebar select").nth(0).select_option("aurora:fixture")
    page.get_by_label("Table", exact=True).select_option("person")
    page.get_by_role("button", name="Load table").click()

    expect(page.locator(".hero .detail")).to_contain_text(
        "counts cover the full database", timeout=10000)
    expect(page.locator(".large-data-warning")).to_contain_text(
        "large queries may take longer")
    expect(page.locator(".query-cache-row")).to_contain_text("Fetched result")
    expect(page.get_by_role("button", name="Compare groups")).to_be_enabled()
    expect(page.get_by_role("button", name=re.compile("Calculated field"))).to_be_enabled()
    expect(page.get_by_text(re.compile("Chat uses loaded rows"))
           ).to_be_visible()
    expect(page.locator(".chat-launcher")).to_have_count(0)

    page.get_by_role("button", name="Compare groups").click()
    page.locator(".compare-panel").get_by_role("button", name="Compare").click()
    expect(page.locator(".compare-panel")).to_contain_text("A: 2 rows · B: 1 rows",
                                                            timeout=10000)
    page.locator(".compare-panel").get_by_role("button", name="✕").click()

    page.get_by_role("button", name=re.compile("Calculated field")).click()
    page.get_by_label("New column name").fill("age_group")
    page.locator(".derive-panel").get_by_role("button", name="Add column").click()
    expect(page.locator(".derive-panel")).to_contain_text('Added "age_group".',
                                                           timeout=10000)
    expect(page.locator(".hero .detail")).to_contain_text("counts cover the full database")
    page.locator(".view-save input").fill("derived-view")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Saved 1 tab(s).", exact=False)).to_be_visible(timeout=10000)
    assert saved_view["datasets"][0]["source"]["kind"] == "derived"
    assert saved_view["datasets"][0]["source"]["spec"]["name"] == "age_group"

    page.locator(".entity-select select").select_option("person_id")
    expect(page.locator(".hero .detail")).to_contain_text(
        "unique person_id", timeout=10000)

    page.get_by_role("button", name="Refresh data").click()
    expect(page.locator(".query-cache-row")).to_contain_text(
        "Fetched result", timeout=10000)
    expect(page.locator(".query-cache-row")).to_contain_text("2026-10-21 12:02 UTC")
    page.locator(".entity-select select").select_option("")
    expect(page.locator(".query-cache-row")).to_contain_text(
        "Cached result", timeout=10000)
    assert query_refreshes.count(True) == 2
    hold_refresh = True
    page.get_by_role("button", name="Refresh data").click()
    expect(page.get_by_role("button", name="Refreshing…")).to_be_disabled()
    page.locator(".entity-select select").select_option("person_id")
    expect(page.get_by_role("button", name="Refresh data")).to_be_enabled()
    for route, response in pending_refresh:
        fulfill(route, response)
    expect(page.get_by_role("button", name="Refresh data")).to_be_enabled()


def test_omop_mode_is_per_aurora_source_and_survives_open_result(
        page: Page, app_url: str, tmp_path):
    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    sources = [
        {"kind": "aurora", "id": "aurora-a", "label": "Aurora A"},
        {"kind": "aurora", "id": "aurora-b", "label": "Aurora B"},
        {"kind": "aurora", "id": "no-cdm", "label": "No CDM"},
    ]
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "person", "detail": "2 rows"},
    ]))
    page.route("**/api/omop/aurora-a?*", lambda route: fulfill(route, {
        "cdm": True, "cdm_schema": "cdm", "vocab_schema": "vocab",
        "tables": [{"name": "person", "schema": "cdm", "domain": "person",
                    "rows": 2, "approx": False}],
    }))
    page.route("**/api/omop/aurora-b?*", lambda route: fulfill(route, {
        "cdm": True, "cdm_schema": "cdm", "vocab_schema": "vocab",
        "tables": [{"name": "person", "schema": "cdm", "domain": "person",
                    "rows": 2, "approx": False}],
    }))
    page.route("**/api/omop/no-cdm?*", lambda route: fulfill(route, {
        "cdm": False, "vocab_schema": None, "tables": [],
    }))

    def concepts(route):
        label = "Condition A" if "/aurora-a/concepts?" in route.request.url else "Condition B"
        concept_id = 101 if label.endswith("A") else 202
        fulfill(route, {"concepts": [{"concept_id": concept_id,
            "concept_name": label, "vocabulary_id": "SNOMED",
            "domain_id": "Condition", "persons": 1}]})

    page.route("**/api/omop/*/concepts?*", concepts)
    page.route("**/api/omop/*/cohort/count", lambda route: fulfill(route, {
        "persons": 1, "total_persons": 2, "attrition": [],
    }))
    page.route("**/api/omop/*/cohort/summary", lambda route: fulfill(route, {
        "scope": "database", "persons": 1, "total_persons": 2,
        "attrition": [{"label": "All persons", "persons": 2}],
        "charts": {
            "gender": [{"category": "Female", "concept_id": 8532, "persons": 1}],
            "age_at_index": [{"category": "18–29", "lo": 18, "hi": 29, "persons": 1}],
            "domains": [],
        },
    }))
    page.route("**/api/omop/*/domain/open", lambda route: fulfill(route, {
        "dataset_id": "opened-clinical", "source": "Clinical table",
        "rows": 1, "columns": [{"name": "person_id", "dtype": "int64",
                                    "filter_kind": "none"}],
        "query_scope": "database",
    }))
    page.route("**/api/datasets/open", lambda route: fulfill(route, {
        "dataset_id": "opened-person", "source": "Aurora A / person",
        "rows": 1, "columns": [{"name": "person_id", "dtype": "int64",
                                    "filter_kind": "none"}],
        "query_scope": "database",
    }))
    page.route("**/api/datasets/upload", lambda route: fulfill(route, {
        "dataset_id": "uploaded-dataset", "source": "uploaded.csv",
        "rows": 1, "columns": [{"name": "person_id", "dtype": "int64",
                                    "filter_kind": "none"}],
        "query_scope": "loaded",
    }))
    page.route("**/api/datasets/opened-*/query", lambda route: fulfill(route, {
        "total": 1, "filtered": 1, "scope": "database", "sampled": False,
        "cache": {"hit": False, "as_of": "2026-10-21T12:00:00Z",
                  "ttl_seconds": 30},
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                 "columns": ["person_id"], "data": [[1]]},
    }))
    page.route("**/api/datasets/uploaded-dataset/query", lambda route: fulfill(route, {
        "total": 1, "filtered": 1, "scope": "loaded", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                  "columns": ["person_id"], "data": [[1]]},
    }))

    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    source_select = page.locator(".sidebar select").nth(0)
    source_select.select_option("aurora:aurora-a")
    expect_explore_view(page, "tables")
    set_explore_view(page, "omop")
    editor = page.locator(".omop-builder:visible > div:not([hidden])")
    summary = editor.get_by_label("OMOP cohort summary")
    expect(summary).to_contain_text("1 of 2 persons", timeout=10000)
    expect(summary.locator(".chart-card .title", has_text="Gender")).to_be_visible()
    expect(summary.locator(".chart-card .title", has_text="Age at index")).to_be_visible()
    expect(editor.get_by_role("button", name="Open cohort")).to_be_enabled()
    grid_box = editor.locator(".omop-grid").bounding_box()
    summary_box = summary.bounding_box()
    assert grid_box and summary_box and summary_box["y"] >= grid_box["y"] + grid_box["height"]
    summary.get_by_role("button", name="Table", exact=True).click()
    expect(summary.get_by_role("table", name="Gender", exact=True)).to_be_visible()
    expect(summary.get_by_role("table", name="Gender", exact=True)).to_contain_text("Female")
    summary.get_by_role("button", name="Charts", exact=True).click()
    plot = summary.locator(".chart-card canvas").first.bounding_box()
    assert plot and plot["width"] > 100 and plot["height"] > 100
    expect(page.get_by_role("heading", name="Filters")).to_have_count(0)
    for width in (1280, 900):
        page.set_viewport_size({"width": width, "height": 1200})
        chart_box = summary.locator(".chart-card").first.bounding_box()
        assert chart_box and chart_box["x"] >= 0
        assert chart_box["x"] + chart_box["width"] <= width
    page.set_viewport_size({"width": 1280, "height": 1200})
    columns = editor.locator(".omop-grid > div")
    left_box, right_box = columns.nth(0).bounding_box(), columns.nth(1).bounding_box()
    assert left_box and right_box and right_box["x"] > left_box["x"]
    page.set_viewport_size({"width": 900, "height": 1200})
    left_box, right_box = columns.nth(0).bounding_box(), columns.nth(1).bounding_box()
    assert left_box and right_box and right_box["y"] > left_box["y"]
    editor.get_by_label("Concept name, ID or code").fill("Aurora A")
    editor.get_by_role("button", name="Search concepts").click()
    result_a = editor.locator(".omop-result", has_text="Condition A")
    expect(result_a).to_be_visible(timeout=10000)
    result_a.locator("input").check()
    editor.get_by_role("button", name="Add criterion (1 concepts)").click()

    set_explore_view(page, "tables")
    page.get_by_label("Table", exact=True).select_option("person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab.active", has_text="person")).to_be_visible(
        timeout=10000)
    set_explore_view(page, "omop")
    expect(page.locator(".omop-rule:visible")).to_have_count(1)
    expect(page.locator(".omop-rule:visible")).to_contain_text("Condition A")

    editor = page.locator(".omop-builder:visible > div:not([hidden])")
    editor.get_by_role("button", name="Count cohort").click()
    editor.get_by_role("button", name="Open clinical table").click()
    expect(page.locator(".tab.active", has_text="person")).to_be_visible(
        timeout=10000)
    expect_explore_view(page, "tables")
    set_explore_view(page, "omop")
    expect(page.locator(".omop-rule:visible")).to_have_count(1)
    expect(page.locator(".omop-rule:visible")).to_contain_text("Condition A")

    source_select.select_option("aurora:aurora-b")
    expect_explore_view(page, "tables")
    set_explore_view(page, "omop")
    expect(page.locator(".omop-rule:visible")).to_have_count(0)
    editor = page.locator(".omop-builder:visible > div:not([hidden])")
    editor.get_by_label("Concept name, ID or code").fill("Aurora B")
    editor.get_by_role("button", name="Search concepts").click()
    result_b = editor.locator(".omop-result", has_text="Condition B")
    expect(result_b).to_be_visible(timeout=10000)
    result_b.locator("input").check()
    editor.get_by_role("button", name="Add criterion (1 concepts)").click()
    expect(page.locator(".omop-rule:visible")).to_contain_text("Condition B")

    source_select.select_option("aurora:aurora-a")
    expect_explore_view(page, "omop")
    expect(page.locator(".omop-rule:visible")).to_have_count(1)
    expect(page.locator(".omop-rule:visible")).to_contain_text("Condition A")
    expect(page.locator(".omop-rule:visible")).not_to_contain_text("Condition B")

    source_select.select_option("aurora:no-cdm")
    set_explore_view(page, "omop")
    expect(page.get_by_role("status")).to_contain_text(
        "No OMOP CDM schema is visible in the selected Aurora datasource.")
    expect(page.locator(".topnav-link", has_text="OMOP cohorts")).to_have_count(0)
    expect(page.get_by_label("OMOP datasource")).to_have_count(0)

    source_select.select_option("aurora:aurora-a")
    set_explore_view(page, "omop")
    csv = tmp_path / "uploaded.csv"
    csv.write_text("person_id\n1\n", encoding="utf-8")
    page.locator('.sidebar input[type="file"]').set_input_files(str(csv))
    expect(page.locator(".tab.active", has_text="uploaded.csv")).to_be_visible(
        timeout=10000)
    expect(page.locator(".hero .detail")).to_contain_text("uploaded.csv",
                                                             timeout=10000)
    expect(page.get_by_role("cell", name="1", exact=True)).to_be_visible(
        timeout=10000)
    expect_explore_view(page, "tables")


def test_common_join_key_applies_to_all_steps(loaded_page: Page, tmp_path):
    right_a = tmp_path / "right-a.csv"
    right_b = tmp_path / "right-b.csv"
    right_a.write_text("sample_id,measure_a\nGTEX-0000,1\n", encoding="utf-8")
    right_b.write_text("sample_id,measure_b\nGTEX-0000,2\n", encoding="utf-8")
    for path in (right_a, right_b):
        loaded_page.locator('input[type="file"]').set_input_files(str(path))
        expect(loaded_page.locator(".tab", has_text=path.name)).to_be_visible(
            timeout=10000)

    loaded_page.locator(".tab-join").click()
    panel = loaded_page.locator(".join-panel")
    panel.locator("button", has_text="add another table").click()
    combo = panel.get_by_role("combobox", name="Table to join in step 2")
    combo.click()
    combo.fill("right-b")
    combo.press("Enter")

    panel.get_by_label("Common key").select_option("sample_id")
    panel.get_by_role("button", name="Apply key to all").click()
    expect(panel.locator(".join-step")).to_have_count(2)
    for step in panel.locator(".join-step").all():
        condition = step.locator(".join-cond").first
        expect(condition.locator("select").nth(0)).to_have_value("sample_id")
        expect(condition.locator("select.join-op")).to_have_value("=")
        expect(condition.locator("select").nth(2)).to_have_value("sample_id")


@pytest.mark.parametrize("sampled", [True, False])
def test_large_loaded_preview_warning(page: Page, app_url: str, tmp_path, sampled):
    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/datasets/upload", lambda route: fulfill(route, {
        "dataset_id": "large-loaded", "source": "large.csv", "rows": 100000,
        "columns": [{"name": "person_id", "dtype": "int64",
                     "filter_kind": "none"}],
        "query_scope": "loaded",
    }))
    page.route("**/api/datasets/large-loaded/query", lambda route: fulfill(route, {
        "total": 100000, "filtered": 100000, "scope": "loaded", "sampled": sampled,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                "columns": ["person_id"], "data": [[1]]},
    }))
    csv = tmp_path / "large.csv"
    csv.write_text("person_id\n1\n", encoding="utf-8")
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator('input[type="file"]').set_input_files(str(csv))
    expect(page.locator(".large-data-warning")).to_contain_text(
        "Counts cover only the loaded preview, not the full source." if sampled
        else "100,000 loaded rows", timeout=10000)
    expect(page.locator(".large-data-warning")).not_to_contain_text("Exports support")
    if sampled:
        expect(page.locator(".hero .detail")).to_contain_text("capped loaded sample")


def test_database_export_job_progress_cancel_and_download(page: Page, app_url: str):
    export_posts = []
    status_calls = {}
    deletes = []
    columns = [{"name": "person_id", "dtype": "int64", "filter_kind": "none"}]

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [{"kind": "aurora", "id": "fixture",
                                      "label": "Fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "person", "detail": "2 rows"},
    ]))
    page.route("**/api/datasets/open", lambda route: fulfill(route, {
        "dataset_id": "database-export", "source": "fixture / person",
        "rows": 2, "columns": columns,
        "source_ref": {"kind": "aurora", "resource_id": "fixture",
                       "table": "person", "schema": "public"},
        "query_scope": "database",
    }))
    page.route("**/api/datasets/database-export/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "cache": {"hit": False, "as_of": "2026-10-21T12:00:00Z",
                  "ttl_seconds": 30},
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                "columns": ["person_id"], "data": [[1], [2]]},
    }))

    def create(route):
        export_posts.append(route.request.post_data_json)
        job_id = f"job-{len(export_posts)}"
        fulfill(route, {"id": job_id, "status": "queued", "rows": 0, "bytes": 0})

    def status(route):
        job_id = route.request.url.rsplit("/", 1)[-1]
        if job_id == "job-1":
            progress = [
                {"id": job_id, "status": "running", "rows": 250},
                {"id": job_id, "status": "running", "rows": 500},
                {"id": job_id, "status": "complete", "rows": 750,
                 "bytes": 1048576},
            ]
            index = status_calls.get(job_id, 0)
            status_calls[job_id] = index + 1
            fulfill(route, progress[min(index, len(progress) - 1)])
        else:
            status_calls[job_id] = status_calls.get(job_id, 0) + 1
            fulfill(route, {"id": job_id, "status": "running", "rows": 125})

    def cancel(route):
        deletes.append(route.request.url.rsplit("/", 1)[-1])
        fulfill(route, {"ok": True})

    page.route("**/api/datasets/database-export/exports", create)
    page.route("**/api/exports/*/download", lambda route: route.fulfill(status=200))
    page.route("**/api/exports/*", lambda route: status(route)
               if route.request.method == "GET" else cancel(route))

    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".sidebar select").nth(0).select_option("aurora:fixture")
    page.get_by_label("Table", exact=True).select_option("person")
    page.get_by_role("button", name="Load table").click()

    page.get_by_role("button", name="Export TSV").click()
    expect(page.locator(".export-job")).to_contain_text("Preparing export", timeout=10000)
    expect(page.locator(".export-job")).to_contain_text("250 rows", timeout=10000)
    expect(page.locator(".export-job")).to_contain_text("500 rows", timeout=10000)
    expect(page.locator(".export-job")).to_contain_text("Export ready · 750 rows",
                                                         timeout=10000)
    download = page.get_by_role("link", name="Download TSV · 1.0 MB")
    expect(download).to_have_attribute("href", "/api/exports/job-1/download")
    page.get_by_role("button", name="Clear export").click()
    expect(page.locator(".export-job")).to_have_count(0)
    assert deletes == ["job-1"]

    page.get_by_role("button", name="Export TSV").click()
    expect(page.locator(".export-job")).to_contain_text("125 rows", timeout=10000)
    page.get_by_role("button", name="Cancel export").click()
    expect(page.locator(".export-job")).to_contain_text("Export cancelled")
    assert deletes == ["job-1", "job-2"]
    assert len(export_posts) == 2
    assert export_posts[0] == {"filters": []}


def test_join_source_ref_saves_and_reopens(page: Page, app_url: str):
    source_refs = {}
    saved_state = {}
    open_counter = 0
    columns = [{"name": "person_id", "dtype": "int64", "filter_kind": "none"}]

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "fixture", "label": "Fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "events", "detail": "2 rows"},
        {"name": "people", "detail": "2 rows"},
    ]))

    def open_source(route):
        nonlocal open_counter
        body = route.request.post_data_json
        if body.get("source_ref"):
            ref = body["source_ref"]
            source = "fixture / joined"
        else:
            open_counter += 1
            table = body["table"]
            ref = {"kind": "aurora", "resource_id": "fixture",
                   "table": table, "schema": "public"}
            source = f"fixture / {table}"
        dataset_id = f"opened-{open_counter}"
        source_refs[dataset_id] = ref
        fulfill(route, {"dataset_id": dataset_id, "source": source,
                        "rows": 2, "columns": columns,
                        "source_ref": ref, "query_scope": "database"})

    page.route("**/api/datasets/open", open_source)
    page.route("**/api/datasets/**/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "entity": None, "charts": [],
        "rows": {"page": 0, "page_size": 50,
                  "columns": ["person_id"], "data": [[1], [2]]},
    }))
    page.route("**/api/datasets/join/validate", lambda route: fulfill(route, {
        "ok": True, "engine": "aurora", "engine_reason": "",
        "capped_inputs": [], "problems": [],
        "steps": [{"problems": [], "notes": [],
                    "conditions": [{"problem": None, "note": None}]}],
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: fulfill(route, []))

    def join(route):
        body = route.request.post_data_json
        ref = {"kind": "join", "base": source_refs[body["base_id"]],
               "steps": [{"source": source_refs[step["right_id"]],
                          **{key: step[key] for key in
                             ("how", "conditions", "columns", "alias")}}
                         for step in body["steps"]]}
        fulfill(route, {
            "dataset_id": "joined-dataset", "source": "fixture / events + people",
            "rows": 2, "columns": columns, "source_ref": ref,
            "query_scope": "database",
            "join": {"engine": "aurora", "base_rows": 2, "rows": 2,
                     "total_rows": 2, "truncated": False, "steps": [],
                     "notes": [], "capped_inputs": []},
        })

    page.route("**/api/datasets/join", join)
    page.route("**/api/views?**", lambda route: fulfill(route, [{"name": "joined-view"}]))

    def views(route):
        nonlocal saved_state
        if route.request.method == "POST":
            saved_state = route.request.post_data_json
            fulfill(route, {"name": "joined-view"})
        else:
            fulfill(route, {"version": 2, "active": 0,
                            "datasets": saved_state.get("datasets", [])})

    page.route("**/api/views", views)
    page.route("**/api/views/one?**", views)

    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".sidebar select").nth(0).select_option("aurora:fixture")
    page.get_by_label("Table", exact=True).select_option("events")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="events")).to_be_visible(timeout=10000)
    page.get_by_label("Table", exact=True).select_option("people")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="people")).to_be_visible(timeout=10000)

    page.locator(".tab-join").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Left key step 1 condition 1").select_option("person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("person_id")
    expect(panel.get_by_role("button", name="Join into new tab")).to_be_enabled(
        timeout=10000)
    panel.get_by_role("button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="events + people")).to_be_visible(
        timeout=10000)

    page.locator(".view-save input").fill("joined-view")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Saved 3 tab(s).", exact=False)).to_be_visible(
        timeout=10000)
    assert saved_state["datasets"][-1]["source"]["kind"] == "join"

    with page.expect_response(lambda response:
            response.url.endswith("/api/datasets/open")
            and response.request.method == "POST"
            and response.request.post_data_json.get("source_ref", {}).get("kind") == "join") as opened_join:
        page.get_by_role("button", name="joined-view").click()
    expect(page.locator(".tab", has_text="events + people")).to_be_visible(
        timeout=10000)
    reopened = opened_join.value.request.post_data_json["source_ref"]
    assert reopened["steps"][0]["source"]["table"] == "people"


def test_aurora_schema_tables_open_with_explicit_schema_and_join(
        page: Page, app_url: str):
    opened_refs = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "fixture", "label": "Fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "person", "table": "person", "schema": "public",
         "detail": "table"},
        {"name": "cdm.person", "table": "person", "schema": "cdm",
         "detail": "table"},
    ]))

    def open_table(route):
        body = route.request.post_data_json
        source_ref = body.get("source_ref") or {
            "kind": body.get("kind"), "resource_id": body.get("resource_id"),
            "table": body.get("table"), "schema": "public",
        }
        opened_refs.append(source_ref)
        schema = source_ref["schema"]
        table_name = source_ref["table"]
        label = table_name if schema == "public" else f"{schema}.{table_name}"
        fulfill(route, {
            "dataset_id": f"opened-{schema}", "source": f"fixture / {label}",
            "rows": 2,
            "columns": [{"name": "person_id", "dtype": "int64",
                         "filter_kind": "none"}],
            "source_ref": source_ref, "query_scope": "database",
        })

    page.route("**/api/datasets/open", open_table)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "entity": None,
        "cache": {"hit": False, "as_of": "2026-10-22T12:00:00Z",
                  "ttl_seconds": 30},
        "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id"],
                 "data": [[1], [2]]},
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: fulfill(route, []))
    page.route("**/api/datasets/join/validate", lambda route: fulfill(route, {
        "ok": True, "engine": "aurora", "engine_reason": "",
        "capped_inputs": [], "problems": [],
        "steps": [{"problems": [], "notes": [],
                    "conditions": [{"problem": None, "note": None}]}],
    }))

    def join(route):
        body = route.request.post_data_json
        base_ref = next(ref for ref in opened_refs
                        if ref["schema"] == "public")
        cdm_ref = next(ref for ref in opened_refs if ref["schema"] == "cdm")
        assert body["steps"][0]["conditions"] == [
            {"left": "person_id", "op": "=", "right": "person_id"}]
        fulfill(route, {
            "dataset_id": "joined-schemas", "source": "fixture / person + cdm.person",
            "rows": 2,
            "columns": [{"name": "person_id", "dtype": "int64",
                         "filter_kind": "none"}],
            "source_ref": {"kind": "join", "base": base_ref,
                           "steps": [{"source": cdm_ref,
                                      **{key: body["steps"][0][key] for key in
                                         ("how", "conditions", "columns", "alias")}}]},
            "query_scope": "database",
            "join": {"engine": "aurora", "base_rows": 2, "rows": 2,
                     "total_rows": 2, "truncated": False, "steps": [],
                     "notes": [], "capped_inputs": []},
        })

    page.route("**/api/datasets/join", join)
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".sidebar select").nth(0).select_option("aurora:fixture")
    table_select = page.get_by_label("Table", exact=True)
    expect(table_select.locator("option", has_text="cdm.person")).to_have_count(1)
    table_select.select_option("person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="person")).to_be_visible(timeout=10000)
    table_select.select_option("cdm.person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="cdm.person")).to_be_visible(timeout=10000)

    assert opened_refs == [
        {"kind": "aurora", "resource_id": "fixture", "table": "person",
         "schema": "public"},
        {"kind": "aurora", "resource_id": "fixture", "table": "person",
         "schema": "cdm"},
    ]
    expect(page.locator(".tab")).to_have_count(2)
    page.locator(".tab-join").click()
    panel = page.locator(".join-panel")
    expect(panel).to_be_visible()
    panel.get_by_label("Left key step 1 condition 1").select_option("person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("person_id")
    expect(page.get_by_role("button", name="Save to Aurora")).to_have_count(0)
    expect(page.locator(".cohort-bar")).to_have_count(0)
    panel.get_by_role("button", name="✕").click()
    expect(page.get_by_role("button", name="Save to Aurora")).to_be_visible()
    expect(page.locator(".cohort-bar")).to_be_visible()
    page.locator(".tab-join").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Left key step 1 condition 1").select_option("person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("person_id")
    panel.get_by_role("button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="person + cdm.person")).to_be_visible(
        timeout=10000)


def test_join_can_select_source_schema_and_apply_key_recommendation(
        page: Page, app_url: str):
    refs = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "fixture", "label": "Fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "public.person", "table": "person", "schema": "public",
         "detail": "table"},
        {"name": "genetics.samples", "table": "samples", "schema": "genetics",
         "detail": "table"},
    ]))

    def open_source(route):
        ref = route.request.post_data_json["source_ref"]
        refs.append(ref)
        name = ref["table"]
        fulfill(route, {
            "dataset_id": f"opened-{ref['schema']}",
            "source": f"fixture / {ref['schema']}.{name}", "rows": 2,
            "columns": [{"name": "person_id", "dtype": "int64",
                         "filter_kind": "none"}],
            "source_ref": ref, "query_scope": "database",
        })

    page.route("**/api/datasets/open", open_source)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "entity": None, "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id"],
                 "data": [[1], [2]]},
    }))
    page.route("**/api/joins/recommend", lambda route: fulfill(route, {
        "candidates": [{
            "keys": [{"left": "person_id", "right": "person_id"}],
            "method": "foreign_key", "evidence": ["Declared foreign key"],
            "confidence": None,
        }], "warnings": [],
        "jev": {"status": "not_configured", "configured": False, "model": ""},
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: fulfill(route, []))
    page.route("**/api/datasets/join/validate", lambda route: fulfill(route, {
        "ok": True, "engine": "aurora", "engine_reason": "",
        "capped_inputs": [], "problems": [],
        "steps": [{"problems": [], "notes": [],
                    "conditions": [{"problem": None, "note": None}]}],
    }))

    def join(route):
        body = route.request.post_data_json
        assert body["steps"][0]["conditions"] == [
            {"left": "person_id", "op": "=", "right": "person_id"}]
        fulfill(route, {
            "dataset_id": "joined-source-first", "source": "fixture / samples + person",
            "rows": 2, "columns": [{"name": "person_id", "dtype": "int64",
                                      "filter_kind": "none"}],
            "source_ref": {"kind": "join", "base": refs[0], "steps": [
                {"source": refs[1], "how": "left", "conditions": body["steps"][0]["conditions"],
                 "columns": None, "alias": "person"}]},
            "query_scope": "database",
            "join": {"engine": "aurora", "base_rows": 2, "rows": 2,
                     "total_rows": 2, "truncated": False, "steps": [],
                     "notes": [], "capped_inputs": []},
        })

    page.route("**/api/datasets/join", join)
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Join schema").select_option("genetics")
    table = panel.get_by_role("combobox", name="Source table to add")
    table.fill("samples")
    table.press("Enter")
    panel.get_by_role("button", name="Add table").click()
    expect(page.locator(".tab", has_text="genetics.samples")).to_be_visible(
        timeout=10000)

    panel.get_by_label("Join schema").select_option("public")
    table.fill("person")
    table.press("Enter")
    panel.get_by_role("button", name="Add table").click()
    expect(panel.get_by_role("button", name="Apply genetics.samples: person_id = person_id · foreign key")
           ).to_be_visible(timeout=10000)
    expect(panel.get_by_label("Left key step 1 condition 1")).to_have_value("")
    panel.get_by_role("button", name="Apply genetics.samples: person_id = person_id · foreign key").click()
    expect(panel.get_by_label("Left key step 1 condition 1")).to_have_value("person_id")
    expect(panel.locator(".join-evidence")).not_to_have_attribute("open", "")
    panel.locator(".join-evidence summary").click()
    expect(panel.locator(".join-evidence")).to_have_attribute("open", "")
    expect(panel.locator(".join-evidence")).to_contain_text("Declared foreign key")
    panel.get_by_role("button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="samples + person")).to_be_visible(
        timeout=10000)
    assert refs == [
        {"kind": "aurora", "resource_id": "fixture",
         "schema": "genetics", "table": "samples"},
        {"kind": "aurora", "resource_id": "fixture",
         "schema": "public", "table": "person"},
    ]


def _durable_join_page(page: Page, app_url: str):
    opened_counts = {"people": 0, "events": 0}
    open_requests = []
    join_requests = []
    query_dataset_ids = []
    refs = {
        "people": {"kind": "aurora", "resource_id": "fixture",
                    "table": "people", "schema": "public"},
        "events": {"kind": "aurora", "resource_id": "fixture",
                   "table": "events", "schema": "public"},
    }
    columns = [{"name": "person_id", "dtype": "int64", "filter_kind": "none"}]

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "fixture", "label": "Fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": name, "table": name, "schema": "public", "detail": "table"}
        for name in ("people", "events")
    ]))

    def open_source(route):
        body = route.request.post_data_json
        ref = body["source_ref"]
        name = ref["table"]
        open_requests.append(body)
        opened_counts[name] += 1
        dataset_id = f"{name}-{opened_counts[name]}"
        fulfill(route, {
            "dataset_id": dataset_id, "source": f"fixture / {name}",
            "rows": 2, "columns": columns,
            "source_ref": refs[name], "query_scope": "database",
        })

    page.route("**/api/datasets/open", open_source)
    def query(route):
        query_dataset_ids.append(route.request.url.split("/api/datasets/", 1)[1]
                                 .split("/", 1)[0])
        fulfill(route, {
            "total": 2, "filtered": 2, "scope": "database", "sampled": False,
            "entity": None, "charts": [],
            "rows": {"page": 0, "page_size": 50,
                     "columns": ["person_id"], "data": [[1], [2]]},
        })

    page.route("**/api/datasets/*/query", query)
    page.route("**/api/datasets/join/validate", lambda route: fulfill(route, {
        "ok": True, "engine": "aurora", "engine_reason": "",
        "capped_inputs": [], "problems": [],
        "steps": [{"problems": [], "notes": [],
                    "conditions": [{"problem": None, "note": None}]}],
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: fulfill(route, []))
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".sidebar select").nth(0).select_option("aurora:fixture")
    for name in ("people", "events"):
        page.get_by_label("Table", exact=True).select_option(name)
        page.get_by_role("button", name="Load table").click()
        expect(page.locator(".tab", has_text=name)).to_be_visible(timeout=10000)
    page.locator(".tab-join").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Left key step 1 condition 1").select_option("person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("person_id")
    return refs, open_requests, join_requests, query_dataset_ids


def test_join_expiry_reopens_durable_inputs_and_retries_once(page: Page, app_url: str):
    refs, open_requests, join_requests, _ = _durable_join_page(page, app_url)

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    def join(route):
        body = route.request.post_data_json
        join_requests.append(body)
        if len(join_requests) == 1:
            fulfill(route, {"detail": {"code": "DATASET_EXPIRED",
                                       "message": "dataset expired"}}, 404)
            return
        assert body["base_id"] == "people-2"
        assert body["steps"][0]["right_id"] == "events-2"
        fulfill(route, {
            "dataset_id": "joined-recovered", "source": "fixture / people + events",
            "rows": 2, "columns": [{"name": "person_id", "dtype": "int64",
                                     "filter_kind": "none"}],
            "source_ref": {"kind": "join", "base": refs["people"],
                           "steps": [{"source": refs["events"], "how": "left",
                                      "conditions": [{"left": "person_id",
                                                      "op": "=", "right": "person_id"}],
                                      "alias": "events"}]},
            "query_scope": "database",
            "join": {"engine": "aurora", "base_rows": 2, "rows": 2,
                     "total_rows": 2, "truncated": False, "steps": [],
                     "notes": [], "capped_inputs": []},
        })

    page.route("**/api/datasets/join", join)
    panel = page.locator(".join-panel")
    panel.get_by_role("button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="people + events")).to_be_visible(
        timeout=10000)
    assert len(join_requests) == 2
    assert len(open_requests) == 4
    assert [body["source_ref"]["table"] for body in open_requests[2:]] == [
        "people", "events",
    ]


def test_join_non_expiry_error_does_not_reopen_inputs(page: Page, app_url: str):
    _, open_requests, join_requests, _ = _durable_join_page(page, app_url)

    def reject_join(route):
        join_requests.append(route.request.post_data_json)
        route.fulfill(status=404, content_type="application/json", json={
            "detail": {"code": "INVALID_JOIN", "message": "join rejected"},
        })

    page.route("**/api/datasets/join", reject_join)
    page.locator(".join-panel").get_by_role(
        "button", name="Join into new tab").click()
    expect(page.get_by_text("Join failed: join rejected", exact=False)).to_be_visible(
        timeout=10000)
    assert len(join_requests) == 1
    assert len(open_requests) == 2


def test_failed_join_recovery_closes_reopened_inputs_and_stops_after_one_retry(
        page: Page, app_url: str):
    _, open_requests, join_requests, query_dataset_ids = _durable_join_page(page, app_url)
    closed = []

    def join(route):
        join_requests.append(route.request.post_data_json)
        if len(join_requests) == 1:
            route.fulfill(status=404, content_type="application/json", json={
                "detail": {"code": "DATASET_EXPIRED", "message": "expired"},
            })
            return
        route.fulfill(status=503, content_type="application/json", json={
            "detail": "retry rejected",
        })

    def close(route):
        if route.request.method != "DELETE":
            route.fallback()
            return
        closed.append(route.request.url.rsplit("/", 1)[-1])
        route.fulfill(status=200, content_type="application/json", json={"ok": True})

    page.route("**/api/datasets/join", join)
    page.route("**/api/datasets/*", close)
    page.locator(".join-panel").get_by_role(
        "button", name="Join into new tab").click()
    expect(page.get_by_text("Automatic recovery failed: retry rejected", exact=False)
           ).to_be_visible(timeout=10000)
    assert len(join_requests) == 2
    assert len(open_requests) == 4
    assert sorted(closed) == ["events-2", "people-2"]


def test_recovered_repeat_join_opens_new_result_and_queries_new_id(
        page: Page, app_url: str):
    refs, _, _, query_ids = _durable_join_page(page, app_url)
    calls = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    def result(dataset_id):
        return {
            "dataset_id": dataset_id, "source": "fixture / people + events",
            "rows": 2, "columns": [{"name": "person_id", "dtype": "int64",
                                     "filter_kind": "none"}],
            "source_ref": {"kind": "join", "base": refs["people"],
                           "steps": [{"source": refs["events"], "how": "left",
                                      "conditions": [{"left": "person_id",
                                                      "op": "=", "right": "person_id"}],
                                      "alias": "events"}]},
            "query_scope": "database",
            "join": {"engine": "aurora", "base_rows": 2, "rows": 2,
                     "total_rows": 2, "truncated": False, "steps": [],
                     "notes": [], "capped_inputs": []},
        }

    def join(route):
        calls.append(route.request.post_data_json)
        if len(calls) == 1:
            fulfill(route, result("joined-original"))
        elif len(calls) == 2:
            fulfill(route, {"detail": {"code": "DATASET_EXPIRED",
                                       "message": "expired"}}, 404)
        else:
            assert calls[-1]["base_id"] == "people-2"
            assert calls[-1]["steps"][0]["right_id"] == "events-2"
            fulfill(route, result("joined-recovered"))

    page.route("**/api/datasets/join", join)
    page.locator(".join-panel").get_by_role(
        "button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="people + events")).to_have_count(
        1, timeout=10000)

    page.locator(".tab-join").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Left key step 1 condition 1").select_option("person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("person_id")
    with page.expect_request(lambda request:
            request.url.endswith("/api/datasets/joined-recovered/query")) as queried:
        page.locator(".join-panel").get_by_role(
            "button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="people + events")).to_have_count(
        2, timeout=10000)
    assert queried.value.url.endswith("/api/datasets/joined-recovered/query")
    assert calls[1]["base_id"] == "people-1"
    assert calls[1]["steps"][0]["right_id"] == "events-1"
    assert len(calls) == 3
    assert "joined-recovered" in query_ids


def test_expired_upload_join_shows_reopen_guidance(loaded_page: Page, tmp_path):
    second = tmp_path / "events.csv"
    second.write_text("sample_id,event\nGTEX-0000,visit\n", encoding="utf-8")
    loaded_page.locator('input[type="file"]').set_input_files(str(second))
    expect(loaded_page.locator(".tab", has_text="events.csv")).to_be_visible(
        timeout=10000)
    opened = []
    joins = []

    def reject_open(route):
        opened.append(route.request.post_data_json)
        route.fulfill(status=500, content_type="application/json", json={
            "detail": "unexpected source reopen",
        })

    def expire_join(route):
        joins.append(route.request.post_data_json)
        route.fulfill(status=404, content_type="application/json", json={
            "detail": {"code": "DATASET_EXPIRED", "message": "dataset expired"},
        })

    loaded_page.route("**/api/datasets/open", reject_open)
    loaded_page.route("**/api/datasets/join", expire_join)
    loaded_page.locator(".tab-join").click()
    panel = loaded_page.locator(".join-panel")
    panel.get_by_label("Left key step 1 condition 1").select_option("sample_id")
    panel.get_by_label("Right key step 1 condition 1").select_option("sample_id")
    panel.get_by_role("button", name="Join into new tab").click()
    expect(loaded_page.get_by_text(
        "The join inputs expired. Reopen the source or upload the data again, then retry the join.",
        exact=False)).to_be_visible(timeout=10000)
    assert len(joins) == 1
    assert opened == []
