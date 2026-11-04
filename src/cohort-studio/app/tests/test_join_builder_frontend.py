import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_three_table_builder_join_to_reorder_and_alias_rename(page, app_url):
    sources = [{"kind": "aurora", "id": "clinical", "label": "Clinical Aurora"}]

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/config", lambda route: fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}},
    }))
    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: fulfill(route, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda route: fulfill(route, [
        {"name": "person", "schema": "public", "table": "person", "detail": "Aurora"},
        {"name": "visit", "schema": "public", "table": "visit", "detail": "Aurora"},
        {"name": "drug", "schema": "public", "table": "drug", "detail": "Aurora"},
    ]))

    def open_source(route):
        ref = route.request.post_data_json["source_ref"]
        fulfill(route, {"dataset_id": f"open-{ref['table']}", "source": ref["table"],
            "rows": 2, "columns": [{"name": c, "dtype": "int64", "filter_kind": "none"}
                                   for c in {"person": ["person_id", "year"],
                                             "visit": ["person_id", "visit_id"],
                                             "drug": ["person_id", "drug_id"]}[ref["table"]]],
            "source_ref": ref, "query_scope": "database"})

    def open_source_job(route):
        class JobRoute:
            request = route.request
            def fulfill(self, **kw):
                route.fulfill(status=kw.get('status', 200), content_type='application/json',
                              json={'job_id':'open', 'status':'complete', 'result':kw['json']})
        open_source(JobRoute())
    page.route("**/api/data-jobs/open", open_source_job)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
            "columns": ["person_id"], "data": [[1], [2]]},
    }))
    page.route("**/api/joins/recommend", lambda route: fulfill(route, {
        "candidates": [], "warnings": [],
        "jev": {"status": "not_configured", "configured": False, "model": ""},
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: fulfill(route, []))
    page.route("**/api/datasets/join/validate", lambda route: fulfill(route, {
        "ok": True, "engine": "aurora", "engine_reason": "Same Aurora source.",
        "generated_sql": {
            "engine": "aurora",
            "sql": "SELECT person_id FROM public.person WHERE person_id = :person_id",
            "copyable_sql": "SELECT person_id FROM public.person WHERE person_id = 1",
            "display_sql": "SELECT\n  person_id\nFROM public.person\nWHERE person_id = 1",
            "parameters": {"person_id": 1},
        },
        "capped_inputs": [], "problems": [], "steps": [{
            "problems": [], "notes": [], "conditions": [{"problem": None, "note": None}],
        }],
    }))
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Join schema").select_option("public")
    picker = panel.get_by_role("combobox", name="Source table to add")
    picker.fill("person")
    picker.press("Enter")
    panel.get_by_role("button", name="Add table").click()
    expect(page.locator(".tab", has_text="person")).to_be_visible(timeout=10000)
    picker.fill("visit")
    picker.press("Enter")
    expect(panel.get_by_role("button", name="Add table")).to_be_enabled(timeout=10000)
    panel.get_by_role("button", name="Add table").click()
    expect(panel.get_by_role("button", name="Add table")).to_be_disabled(timeout=10000)
    picker.fill("")
    picker.fill("drug")
    option = page.get_by_role("option", name="drug")
    if option.count():
        option.first.click()
    else:
        picker.press("Enter")
    expect(panel.get_by_role("button", name="Add table")).to_be_enabled(timeout=10000)
    panel.get_by_role("button", name="Add table").click()
    step2_left = panel.get_by_label("Left key step 2 condition 1")
    expect(step2_left).to_be_visible(timeout=10000)

    # Left keys are grouped by the table they come from.
    labels = step2_left.locator("optgroup").evaluate_all("els => els.map(e => e.label)")
    assert labels[0] == "person" and len(labels) == 2, labels
    assert "visit → visit_id" in step2_left.locator("option").all_inner_texts()

    # Join to the base table: only its columns are offered.
    panel.get_by_label("Join step 2 to").select_option(label="person")
    options = step2_left.locator("option").all_inner_texts()
    assert "year" in options and not any("visit" in o for o in options), options
    panel.get_by_label("Join step 2 to").select_option(label="Any earlier table")
    step2_left.select_option(label="visit → person_id")

    # Renaming step 1's alias keeps step 2's condition pointing at it.
    step1 = panel.locator(".join-step").nth(0)
    step1.locator("details.join-advanced > summary").click()
    alias = step1.get_by_label("Name joined columns as")
    alias.fill("v")
    expect(step2_left).to_have_value("v → person_id")

    # Typing through another step's alias must not capture its conditions.
    step2 = panel.locator(".join-step").nth(1)
    step2.locator("details.join-advanced > summary").click()
    step2.get_by_label("Name joined columns as").fill("d")
    alias.fill("d")          # step 1 briefly collides with step 2's alias
    alias.fill("dr")
    expect(step2_left).to_have_value("v → person_id")
    alias.fill("v")

    # Step 2 still uses step 1's columns, so it can't move above it.
    up = panel.get_by_role("button", name="Move step 2 up")
    expect(up).to_be_disabled()
    expect(up).to_have_attribute("title", "Uses columns from step 1; change that condition first")
    step2_left.select_option(label="person_id")          # base column: no dependency
    expect(up).to_be_enabled()

    # Reorder: step 2 (drug) moves above step 1 (visit).
    tables_before = [panel.get_by_label(f"Table to join in step {n}").input_value() for n in (1, 2)]
    panel.get_by_role("button", name="Move step 2 up").click()
    tables_after = [panel.get_by_label(f"Table to join in step {n}").input_value() for n in (1, 2)]
    assert tables_after == list(reversed(tables_before)), (tables_before, tables_after)
    page.screenshot(path="/private/tmp/cohort-join-builder-3-tables.png")
