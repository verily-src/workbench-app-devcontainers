import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_expired_join_recipe_reopens_with_saved_filters_charts_and_rename(
        page: Page, app_url: str):
    source_ref = {
        "kind": "join",
        "base": {"kind": "omop_cohort", "resource_id": "clinical",
                 "membership_mode": "live", "spec": {"filters": []}},
        "steps": [{"source": {"kind": "aurora", "resource_id": "genetics",
                               "schema": "public", "table": "variants"},
                    "how": "inner", "alias": "genetics",
                    "conditions": [{"left": "person_id", "op": "=",
                                    "right": "person_id"}],
                    "columns": ["variant_id", "dosage"]}],
    }
    columns = [
        {"name": "person_id", "dtype": "int64", "filter_kind": "none"},
        {"name": "variant_id", "dtype": "object", "filter_kind": "categorical",
         "values": ["SYN_VAR_0021", "SYN_VAR_0022"]},
        {"name": "dosage", "dtype": "float64", "filter_kind": "range",
         "min": 0, "max": 2},
    ]
    query_calls = []
    opened_refs = []

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/one**", lambda route: fulfill(route, {
        "version": 1, "active": 0,
        "datasets": [{"source": source_ref, "title": "OMOP + genetics",
                      "filters": [{"column": "variant_id", "kind": "categorical",
                                   "values": ["SYN_VAR_0021"]}],
                      "charts": [{"kind": "bar", "x": "variant_id"}]}],
    }))

    def open_source(route):
        ref = route.request.post_data_json["source_ref"]
        opened_refs.append(ref)
        dataset_id = "expired-join" if len(opened_refs) == 1 else "recovered-join"
        fulfill(route, {"dataset_id": dataset_id, "source": "OMOP + genetics",
                        "rows": 1475, "columns": columns,
                        "source_ref": ref, "query_scope": "database"})

    def query(route):
        dataset_id = route.request.url.split("/api/datasets/", 1)[1].split("/", 1)[0]
        query_calls.append((dataset_id, route.request.post_data_json))
        if dataset_id == "expired-join":
            fulfill(route, {"detail": {"code": "DATASET_EXPIRED",
                                        "message": "dataset expired"}}, 404)
            return
        fulfill(route, {"total": 1475, "filtered": 1475, "scope": "database",
                        "entity": None, "charts": [],
                        "rows": {"page": 0, "page_size": 50,
                                 "columns": ["person_id"], "data": [[1]]}})

    page.route("**/api/datasets/open", open_source)
    page.route("**/api/datasets/*/query", query)
    page.goto(f"{app_url}/#view=aurora:clinical:genetics")

    tab = page.locator(".tab.active")
    expect(tab).to_contain_text("OMOP + genetics", timeout=15000)
    expect(tab).to_contain_text("Rename")
    expect(page.get_by_text("Query failed:", exact=False)).to_have_count(0)
    expect(page.locator(".chart-card")).to_have_count(1)
    assert [call[0] for call in query_calls] == ["expired-join", "recovered-join"]
    assert opened_refs == [source_ref, source_ref]
    assert query_calls[-1][1]["filters"] == [
        {"column": "variant_id", "kind": "categorical", "values": ["SYN_VAR_0021"]}
    ]
    assert query_calls[-1][1]["charts"] == [{"kind": "bar", "x": "variant_id"}]

    tab.get_by_role("button", name="Rename OMOP + genetics").click()
    page.get_by_role("textbox", name="Name for OMOP + genetics").fill("Genetics cohort")
    page.get_by_role("button", name="Save tab name").click()
    expect(page.locator(".tab.active")).to_contain_text("Genetics cohort")


def test_expired_upload_clears_stale_results_with_reopen_guidance(
        page: Page, app_url: str):
    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": [], "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/datasets/upload", lambda route: fulfill(route, {
        "dataset_id": "expired-upload", "source": "fixture upload",
        "rows": 1, "columns": [{"name": "value", "dtype": "int64",
                                    "filter_kind": "range", "min": 1, "max": 1}],
        "query_scope": "loaded",
    }))
    page.route("**/api/datasets/expired-upload/query", lambda route: fulfill(route, {
        "detail": {"code": "DATASET_EXPIRED", "message": "dataset expired"},
    }, 404))
    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator('input[type="file"]').set_input_files({
        "name": "cohort.csv", "mimeType": "text/csv", "buffer": b"value\n1\n",
    })
    expect(page.get_by_text("no saved source recipe", exact=False)).to_be_visible(
        timeout=10000)
    expect(page.locator(".chart-card")).to_have_count(0)
