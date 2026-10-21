import re
import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url, loaded_page

pytestmark = pytest.mark.e2e


def test_entity_count_and_column_settings(loaded_page: Page):
    entity = loaded_page.locator(".entity-select select")
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


def test_database_scope_disables_loaded_frame_tools(page: Page, app_url: str):
    query_refreshes = []
    refresh_complete = False
    hold_refresh = False
    pending_refresh = []
    columns = [{"name": "person_id", "dtype": "int64", "filter_kind": "none"}]
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
                                    "columns": ["person_id"], "data": [[1], [2]]},
        }
        if refresh and hold_refresh:
            pending_refresh.append((route, response))
        else:
            fulfill(route, response)

    page.route("**/api/datasets/database-person/query", query)
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".sidebar select").nth(0).select_option("aurora:fixture")
    page.locator(".sidebar select").nth(1).select_option("person")
    page.get_by_role("button", name="Load table").click()

    expect(page.locator(".hero .detail")).to_contain_text(
        "counts cover the full database", timeout=10000)
    expect(page.locator(".large-data-warning")).to_contain_text(
        "large queries may take longer")
    expect(page.locator(".large-data-warning")).to_contain_text(
        "Exports support up to 100,000 filtered rows")
    expect(page.locator(".query-cache-row")).to_contain_text("Fetched result")
    expect(page.get_by_role("button", name="Compare groups")).to_be_disabled()
    expect(page.get_by_role("button", name=re.compile("Derived column"))).to_be_disabled()
    expect(page.get_by_text(re.compile("Compare, derive, and chat use loaded rows"))
           ).to_be_visible()
    expect(page.locator(".chat-launcher")).to_have_count(0)

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
    assert query_refreshes.count(True) == 1
    hold_refresh = True
    page.get_by_role("button", name="Refresh data").click()
    expect(page.get_by_role("button", name="Refreshing…")).to_be_disabled()
    page.locator(".entity-select select").select_option("person_id")
    expect(page.get_by_role("button", name="Refresh data")).to_be_enabled()
    for route, response in pending_refresh:
        fulfill(route, response)
    expect(page.get_by_role("button", name="Refresh data")).to_be_enabled()


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
    panel.get_by_role("button", name="Apply to all joins").click()
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
    page.locator(".sidebar select").nth(1).select_option("events")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="events")).to_be_visible(timeout=10000)
    page.locator(".sidebar select").nth(1).select_option("people")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab", has_text="people")).to_be_visible(timeout=10000)

    page.locator(".tab-join").click()
    panel = page.locator(".join-panel")
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
