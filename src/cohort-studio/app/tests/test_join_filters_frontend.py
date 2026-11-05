"""Join builder: value filters per table, quiet validation and disabled reasons."""
import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e

COLUMNS = {
    "person": [{"name": "person_id", "dtype": "int64", "filter_kind": "none"},
               {"name": "status", "dtype": "object", "filter_kind": "categorical"}],
    "genotypes": [{"name": "person_id", "dtype": "int64", "filter_kind": "none"},
                  {"name": "dosage", "dtype": "int64", "filter_kind": "range"},
                  {"name": "gene", "dtype": "object", "filter_kind": "categorical"}],
}


def _fulfill(route, body):
    route.fulfill(status=200, content_type="application/json", json=body)


def _setup(page, app_url, validations):
    sources = [{"kind": "aurora", "id": "clinical", "label": "Clinical Aurora"}]
    page.route("**/api/config", lambda route: _fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}},
    }))
    page.route("**/api/datasources", lambda route: _fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: _fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    page.route("**/api/views/all", lambda route: _fulfill(route, {"views": [], "unavailable": []}))
    page.route("**/api/tables?**", lambda route: _fulfill(route, [
        {"name": name, "schema": "public", "table": name, "detail": "Aurora"}
        for name in COLUMNS]))

    def open_job(route):
        ref = route.request.post_data_json["source_ref"]
        _fulfill(route, {"job_id": "open", "status": "complete", "kind": "open", "result": {
            "dataset_id": f"open-{ref['table']}", "source": ref["table"], "rows": 2,
            "columns": COLUMNS[ref["table"]], "source_ref": ref, "query_scope": "database"}})

    page.route("**/api/data-jobs/open", open_job)
    page.route("**/api/datasets/*/query", lambda route: _fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                               "columns": ["person_id"], "data": [[1], [2]]},
    }))
    page.route("**/api/joins/recommend", lambda route: _fulfill(route, {
        "candidates": [], "warnings": [],
        "jev": {"status": "not_configured", "configured": False, "model": ""},
    }))
    page.route("**/api/datasets/join/suggest?**", lambda route: _fulfill(route, []))

    def validate(route):
        body = route.request.post_data_json
        validations.append(body)
        step = body["steps"][0]
        filters = step.get("filters", [])
        where = " AND ".join(f"filter_input.{f['column']} {f['op']} {f['value']!r}"
                             for f in filters if "value" in f)
        sql = ("SELECT * FROM public.person AS l LEFT JOIN (SELECT * FROM public.genotypes "
               f"AS filter_input WHERE {where}) AS r ON l.person_id = r.person_id"
               if where else "SELECT * FROM public.person AS l")
        _fulfill(route, {
            "ok": bool(step["conditions"]), "engine": "aurora", "engine_reason": "Same Aurora source.",
            "generated_sql": {"engine": "aurora", "sql": sql, "copyable_sql": sql,
                              "display_sql": sql, "parameters": {}},
            "capped_inputs": [],
            "problems": [],
            "base_filters": [{"problem": None} for _ in body.get("base_filters", [])],
            "steps": [{"problems": [] if step["conditions"] else ["Step 1: add at least one join condition."],
                       "notes": [],
                       "conditions": [{"problem": None, "note": None} for _ in step["conditions"]],
                       "filters": [{"problem": None} for _ in filters]}],
        })

    page.route("**/api/datasets/join/validate", validate)
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    panel = page.locator(".join-panel")
    panel.get_by_label("Join schema").select_option("public")
    picker = panel.get_by_role("combobox", name="Source table to add")
    for table in ("person", "genotypes"):
        picker.fill(table)
        picker.press("Enter")
        expect(panel.get_by_role("button", name="Add table")).to_be_enabled(timeout=10000)
        panel.get_by_role("button", name="Add table").click()
        expect(page.locator(".tab", has_text=table)).to_be_visible(timeout=10000)
    expect(panel.get_by_label("Right key step 1 condition 1")).to_be_visible()
    return panel


def test_step_and_base_filters_reach_requests_and_generated_sql(page, app_url):
    validations, previews, joins = [], [], []
    panel = _setup(page, app_url, validations)
    panel.get_by_label("Left key step 1 condition 1").select_option(label="person_id")
    panel.get_by_label("Right key step 1 condition 1").select_option(label="person_id")
    expect(panel.locator(".join-step")).to_contain_text("number")      # column type shown

    # Step 1: genotypes.dosage >= 1 AND gene in (BRCA1, BRCA2)
    panel.get_by_role("button", name="Add filter to Step 1").click()
    expect(panel).to_contain_text("Filters this table before joining")
    panel.get_by_label("Step 1 filter 1 column").select_option("dosage")
    panel.get_by_label("Step 1 filter 1 operator").select_option(">=")
    panel.get_by_label("Step 1 filter 1 value").fill("1")
    # Only one empty filter row at a time.
    panel.get_by_role("button", name="Add filter to Step 1").click()
    expect(panel.get_by_role("button", name="Add filter to Step 1")).to_be_disabled()
    panel.get_by_label("Step 1 filter 2 column").select_option("gene")
    panel.get_by_label("Step 1 filter 2 operator").select_option("in")
    expect(panel.get_by_label("Step 1 filter 2 operator")).to_have_value("in")
    panel.get_by_label("Step 1 filter 2 value").fill("BRCA1, BRCA2")
    # Start table: status = case
    panel.get_by_role("button", name="Add filter to Start table").click()
    panel.get_by_label("Start table filter 1 column").select_option("status")
    panel.get_by_label("Start table filter 1 value").fill("case")
    # Null checks take no value.
    panel.get_by_role("button", name="Add filter to Step 1").click()
    panel.get_by_label("Step 1 filter 3 column").select_option("gene")
    panel.get_by_label("Step 1 filter 3 operator").select_option("is not null")
    expect(panel.get_by_label("Step 1 filter 3 value")).to_have_count(0)

    expected_filters = [{"column": "dosage", "op": ">=", "value": 1},
                        {"column": "gene", "op": "in", "value": ["BRCA1", "BRCA2"]},
                        {"column": "gene", "op": "is not null"}]
    expected_base = [{"column": "status", "op": "=", "value": "case"}]

    def last_validation_has_filters():
        return bool(validations) and validations[-1]["steps"][0].get("filters") == expected_filters \
            and validations[-1].get("base_filters") == expected_base
    for _ in range(50):
        if last_validation_has_filters():
            break
        page.wait_for_timeout(100)
    assert last_validation_has_filters(), validations[-1]

    sql_details = panel.locator("details.join-evidence", has_text="Generated SQL")
    sql_details.locator(":scope > summary").click()
    sql_text = panel.get_by_label("Generated SQL", exact=True)
    expect(sql_text).to_contain_text("filter_input.dosage >= 1")
    expect(sql_text).to_contain_text("filter_input.gene in ['BRCA1', 'BRCA2']")

    preview = {"engine": "aurora", "base_rows": 2, "rows": None, "total_rows": None,
               "truncated": False, "sample_only": True, "sample_truncated": False,
               "steps": [{"right_rows": 1, "rows": 2, "truncated": False, "rows_before": 2,
                          "growth": 1.0, "fanout": False, "estimated": True}],
               "growth_total": 1.0, "notes": [], "capped_inputs": [],
               "columns": ["person_id"], "sample": [[1], [2]]}

    def preview_job(route):
        previews.append(route.request.post_data_json)
        _fulfill(route, {"job_id": "pv", "kind": "join_preview", "status": "complete",
                         "result": preview})

    def join_job(route):
        body = route.request.post_data_json
        joins.append(body)
        _fulfill(route, {"job_id": "jn", "kind": "join", "status": "complete", "result": {
            "dataset_id": "joined", "source": "person + genotypes", "rows": 2,
            "columns": COLUMNS["person"], "query_scope": "database",
            "source_ref": {"kind": "join", "base": {"kind": "aurora", "resource_id": "clinical",
                                                    "schema": "public", "table": "person"},
                           "base_filters": body["base_filters"],
                           "steps": [{"source": {"kind": "aurora", "resource_id": "clinical",
                                                 "schema": "public", "table": "genotypes"},
                                      **{k: body["steps"][0][k] for k in
                                         ("how", "conditions", "columns", "alias", "filters")}}]},
            "join": {"engine": "aurora", "base_rows": 2, "rows": 2, "total_rows": 2,
                     "truncated": False, "steps": [], "notes": [], "capped_inputs": []}}})

    page.route("**/api/data-jobs/join_preview", preview_job)
    page.route("**/api/data-jobs/join", join_job)
    panel.get_by_role("button", name="Preview", exact=True).click()
    expect(panel.locator(".join-result-rows")).to_have_text("Result: ~2 rows", timeout=10000)
    assert previews[-1]["steps"][0]["filters"] == expected_filters
    assert previews[-1]["base_filters"] == expected_base
    panel.get_by_role("button", name="Join into new tab").click()
    expect(page.locator(".tab", has_text="person + genotypes")).to_be_visible(timeout=10000)
    assert joins[-1]["steps"][0]["filters"] == expected_filters
    assert joins[-1]["base_filters"] == expected_base
    assert joins[-1]["steps"][0]["conditions"] == [
        {"left": "person_id", "op": "=", "right": "person_id"}]


def test_untouched_rows_stay_quiet_and_disabled_buttons_say_why(page, app_url):
    validations = []
    panel = _setup(page, app_url, validations)
    join_button = panel.get_by_role("button", name="Join into new tab")
    reason = panel.locator(".join-disabled-reason")
    expect(join_button).to_be_disabled()
    expect(reason).to_have_text("Choose at least one matching column pair.")
    expect(join_button).to_have_attribute("aria-describedby", reason.get_attribute("id"))
    # A blank, untouched condition row shows no errors, even after validation.
    page.wait_for_timeout(600)
    assert validations and validations[-1]["steps"][0]["conditions"] == []   # blank rows not sent
    expect(panel.locator(".join-check.join-error")).to_have_count(0)
    expect(panel).not_to_contain_text("is not a column")
    expect(panel).not_to_contain_text("add at least one join condition")
    # The type line explains the selected join in plain words.
    expect(panel.locator(".join-how-hint")).to_have_text(
        "Keep all person rows; add genotypes columns where they match.")
    panel.get_by_role("radio", name="Inner").click()
    expect(panel.locator(".join-how-hint")).to_have_text(
        "Keep only rows where person and genotypes match.")

    # Picking one side and leaving the row flags the missing side by table name.
    left = panel.get_by_label("Left key step 1 condition 1")
    left.focus()
    left.select_option(label="person_id")
    expect(panel.locator(".join-check.join-error")).to_have_count(0)   # still editing the row
    left.blur()
    expect(panel.locator(".join-check.join-error")).to_have_text("Pick a column from genotypes.")
    expect(reason).to_have_text("Finish or remove the incomplete condition.")
    panel.get_by_label("Right key step 1 condition 1").select_option(label="person_id")
    expect(panel.locator(".join-check.join-error")).to_have_count(0)
    expect(join_button).to_be_enabled(timeout=10000)
    expect(reason).to_have_text("")

    # "+ condition" adds one blank row at a time; blank rows are ignored.
    add = panel.get_by_role("button", name="+ condition")
    add.click()
    expect(add).to_be_disabled()
    expect(panel.locator(".join-step .join-cond")).to_have_count(2)
    expect(join_button).to_be_enabled()
    panel.get_by_role("button", name="Remove step 1 condition 2").click()
    expect(panel.locator(".join-step .join-cond")).to_have_count(1)

    # An incomplete filter blocks the join and says why once the row is left.
    panel.get_by_role("button", name="Add filter to Step 1").click()
    column = panel.get_by_label("Step 1 filter 1 column")
    column.focus()
    column.select_option("dosage")
    column.blur()
    expect(panel.locator(".join-check.join-error")).to_have_text("Enter a value for dosage.")
    expect(join_button).to_be_disabled()
    expect(reason).to_have_text("Enter a value for dosage.")
    panel.get_by_label("Step 1 filter 1 value").fill("2")
    expect(join_button).to_be_enabled(timeout=10000)
    expect(panel.locator(".join-check.join-error")).to_have_count(0)

    # List values: quoted items may contain commas and doubled quotes.
    panel.get_by_role("button", name="Add filter to Step 1").click()
    panel.get_by_label("Step 1 filter 2 column").select_option("gene")
    panel.get_by_label("Step 1 filter 2 operator").select_option("in")
    panel.get_by_label("Step 1 filter 2 value").fill('"Smith, John", Doe ,"say ""hi"""')
    expected = {"column": "gene", "op": "in", "value": ["Smith, John", "Doe", 'say "hi"']}
    for _ in range(50):
        if validations[-1]["steps"][0].get("filters", [None, None])[-1] == expected:
            break
        page.wait_for_timeout(100)
    assert validations[-1]["steps"][0]["filters"] == [
        {"column": "dosage", "op": "=", "value": 2}, expected]
    # Switching to a single-value operator turns the one quoted list item back into plain text.
    value = panel.get_by_label("Step 1 filter 2 value")
    value.fill('"Smith, John"')
    panel.get_by_label("Step 1 filter 2 operator").select_option("=")
    expect(value).to_have_value("Smith, John")
    scalar = {"column": "gene", "op": "=", "value": "Smith, John"}
    for _ in range(50):
        if validations[-1]["steps"][0].get("filters", [None, None])[-1] == scalar:
            break
        page.wait_for_timeout(100)
    assert validations[-1]["steps"][0]["filters"][-1] == scalar
    # And back to a list operator: the value is quoted so it stays one item.
    panel.get_by_label("Step 1 filter 2 operator").select_option("in")
    expect(value).to_have_value('"Smith, John"')
    # A null check in between keeps the list as a list, and a later scalar operator unquotes it.
    value.fill("BRCA1, BRCA2")
    panel.get_by_label("Step 1 filter 2 operator").select_option("is null")
    panel.get_by_label("Step 1 filter 2 operator").select_option("in")
    expect(value).to_have_value("BRCA1, BRCA2")
    value.fill('"Smith, John"')
    panel.get_by_label("Step 1 filter 2 operator").select_option("is null")
    panel.get_by_label("Step 1 filter 2 operator").select_option("=")
    expect(value).to_have_value("Smith, John")
