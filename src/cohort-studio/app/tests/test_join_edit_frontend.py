import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_edit_join_seeds_plan_shows_compiled_sql_and_preserves_original(
        page: Page, app_url: str):
    base_ref = {
        "kind": "aurora", "resource_id": "db-main", "schema": "public",
        "table": "person",
    }
    right_ref = {
        "kind": "s3", "resource_id": "s3:lake",
        "table": "variants/part-1.parquet",
    }
    original_ref = {
        "kind": "join", "allow_loaded": False, "base": base_ref,
        "steps": [{
            "source": right_ref, "how": "left",
            "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}],
            "columns": None, "alias": "variants",
        }],
    }
    opened = []
    joins = []
    closed = []
    previews = []
    expire_right_once = True

    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "catalogs_pending": False,
        "sources": [
            {"kind": "aurora", "id": "db-main", "label": "Clinical database"},
            {"kind": "s3", "id": "s3:lake", "label": "Genetics lake"},
        ],
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {
        "views": [], "unavailable": [],
    }))
    page.route("**/api/tables?**", lambda route: fulfill(route, []))
    page.route("**/api/views/one?**", lambda route: fulfill(route, {
        "version": 2, "active": 0,
        "datasets": [{
            "source": original_ref, "title": "Existing joined result",
            "filters": [], "charts": [], "cohorts": [],
        }],
    }))

    def open_source(route):
        nonlocal expire_right_once
        source_ref = route.request.post_data_json["source_ref"]
        opened.append(source_ref)
        if source_ref["kind"] == "join":
            dataset_id, source, columns = (
                "existing-join", "db-main / person + s3:lake / variants",
                ["person_id", "variant_code"])
        elif source_ref["kind"] == "aurora":
            dataset_id, source, columns = (
                "edit-base", "db-main / person",
                ["person_id", "birth_year"])
        else:
            if expire_right_once:
                expire_right_once = False
                fulfill(route, {"detail": "Saved S3 source expired"}, status=404)
                return
            dataset_id, source, columns = (
                "edit-right", "s3:lake / variants",
                ["person_id", "study_id", "variant_code"])
        fulfill(route, {
            "dataset_id": dataset_id, "source": source, "rows": 4,
            "columns": [{"name": column, "filter_kind": "none"}
                        for column in columns],
            "source_ref": source_ref, "query_scope": "loaded",
        })

    page.route("**/api/datasets/open", open_source)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 4, "filtered": 4, "scope": "loaded", "charts": [],
        "rows": {"page": 0, "page_size": 50,
                 "columns": ["person_id", "variant_code"],
                 "data": [[1, "v1"], [2, "v2"], [3, "v3"], [4, "v4"]]},
    }))
    def validate_join(route):
        step = route.request.post_data_json["steps"][0]
        join_type = step["how"].upper()
        right_key = step["conditions"][0]["right"]
        consent = route.request.post_data_json.get("allow_loaded", False)
        invalid_key = right_key == "variant_code" or not consent
        fulfill(route, {
            "ok": not invalid_key, "engine": "duckdb", "engine_reason": "Cross-source inputs",
            "generated_sql": None if invalid_key else {
                "engine": "duckdb",
                "sql": f"WITH source_0 AS (...), source_1 AS (...)\nSELECT * FROM source_0 {join_type} JOIN source_1 ON source_0.person_id = source_1.{right_key}",
                "parameters": {"preview_limit": 20},
                "staged_inputs": ["source_0", "source_1"],
            },
            "capped_inputs": [], "problems": ["Consent required"] if invalid_key else [],
            "steps": [{"problems": [], "notes": [],
                       "conditions": [{"problem": None, "note": None}]}],
        })

    page.route("**/api/datasets/join/validate", validate_join)
    page.route("**/api/datasets/join/suggest**", lambda route: fulfill(route, []))

    def preview_join(route):
        body = route.request.post_data_json
        previews.append(body)
        fulfill(route, {
            "engine": "duckdb", "base_rows": 4, "rows": 4, "total_rows": 4,
            "truncated": False, "steps": [{
                "right_rows": 3, "rows": 4, "truncated": False,
                "rows_before": 4, "growth": 1, "fanout": False,
            }],
            "notes": [], "capped_inputs": [], "columns": ["person_id", "study_id"],
            "sample": [[1, "s1"]], "sample_truncated": False,
        })

    page.route("**/api/datasets/join/preview", preview_join)

    def run_join(route):
        body = route.request.post_data_json
        joins.append(body)
        if len(joins) == 1:
            fulfill(route, {"detail": "Join plan rejected"}, status=502)
            return
        edited_ref = {
            "kind": "join", "allow_loaded": True, "base": base_ref,
            "steps": [{**body["steps"][0], "source": right_ref}],
        }
        fulfill(route, {
            "dataset_id": "edited-join", "source": "db-main / person + s3:lake / variants",
            "rows": 4, "columns": [{"name": "person_id", "filter_kind": "none"}],
            "source_ref": edited_ref, "query_scope": "loaded",
            "join": {"engine": "duckdb", "base_rows": 4, "rows": 4,
                     "total_rows": 4, "truncated": False, "steps": [],
                     "notes": [], "capped_inputs": []},
        })

    page.route("**/api/datasets/join", run_join)
    page.route("**/api/datasets/edit-*/**", lambda route: fulfill(route, {
        "total": 4, "filtered": 4, "scope": "loaded", "charts": [],
        "rows": {"page": 0, "page_size": 50, "columns": ["person_id"],
                 "data": [[1], [2], [3], [4]]},
    }))
    def close_dataset(route):
        if route.request.method == "DELETE":
            closed.append(route.request.url)
            fulfill(route, {"ok": True})
        else:
            route.fallback()

    page.route("**/api/datasets/*", close_dataset)

    page.goto(f"{app_url}/#view=aurora:db-main:existing")
    expect(page.locator(".tab.active")).to_contain_text(
        "Existing joined result", timeout=15000)
    page.get_by_role("button", name="Edit join", exact=True).click()
    expect(page.get_by_text("Could not edit join", exact=False)).to_be_visible()
    expect(page.get_by_text("The existing result is unchanged.", exact=False)).to_be_visible()
    expect(page.locator(".tab", has_text="Existing joined result")).to_be_visible()
    assert any("edit-base" in url for url in closed)

    page.get_by_role("button", name="Edit join", exact=True).click()
    expect(page.get_by_label("Left key step 1 condition 1")).to_have_value("person_id")
    expect(page.get_by_label("Right key step 1 condition 1")).to_have_value("person_id")
    expect(page.get_by_role("radio", name="Left")).to_have_attribute("aria-checked", "true")
    consent = page.get_by_label("Allow full-source cross-source join")
    expect(consent).not_to_be_checked()
    join_button = page.get_by_role("button", name="Create edited join in new tab")
    expect(join_button).to_be_disabled()
    consent.check()
    expect(consent).to_be_checked()
    advanced = page.locator(".join-step").first.locator(".join-advanced")
    advanced.locator("summary").click()
    expect(advanced.get_by_label("Name joined columns as")).to_have_value("variants")

    page.get_by_role("radio", name="Inner").click()
    page.get_by_label("Right key step 1 condition 1").select_option("study_id")
    sql_details = page.locator(".join-evidence").filter(has_text="Generated SQL")
    sql_details.locator("summary").click()
    expect(page.get_by_text("WITH source_0 AS", exact=False)).to_be_visible()
    expect(page.get_by_label("Generated SQL")).to_contain_text(
        "INNER JOIN")
    expect(page.get_by_label("Generated SQL")).to_contain_text(
        "source_0.person_id = source_1.study_id")
    expect(page.get_by_label("SQL parameters")).to_contain_text("preview_limit")
    expect(page.get_by_text("Staged inputs: source_0, source_1")).to_be_visible()
    page.get_by_label("Right key step 1 condition 1").select_option("variant_code")
    expect(page.locator(".join-evidence")).to_have_count(0)
    page.get_by_label("Right key step 1 condition 1").select_option("study_id")
    expect(page.locator(".join-evidence")).to_have_count(1)
    consent.uncheck()
    expect(join_button).to_be_disabled()
    consent.check()
    expect(join_button).to_be_enabled()
    page.get_by_role("button", name="Preview", exact=True).click()
    assert previews[0]["steps"][0]["how"] == "inner"
    assert previews[0]["steps"][0]["conditions"][0]["right"] == "study_id"
    assert previews[0]["allow_loaded"] is True

    page.get_by_role("button", name="Create edited join in new tab").click()
    expect(page.get_by_text("Join failed", exact=False)).to_be_visible(timeout=10000)
    expect(page.locator(".tab", has_text="Existing joined result")).to_be_visible()
    expect(page.locator(".tab")).to_have_count(1)
    assert not any("existing-join" in url for url in closed)

    page.get_by_role("button", name="Create edited join in new tab").click()
    expect(page.locator(".tab", has_text="person + variants")).to_be_visible(timeout=10000)
    expect(page.locator(".tab", has_text="Existing joined result")).to_be_visible()
    expect(page.locator(".tab")).to_have_count(2)
    assert [item["kind"] for item in opened] == [
        "join", "aurora", "s3", "aurora", "s3",
    ]
    assert joins[1]["steps"][0]["how"] == "inner"
    assert joins[1]["steps"][0]["conditions"][0]["right"] == "study_id"
    assert joins[1]["allow_loaded"] is True
    assert not any("existing-join" in url for url in closed)
