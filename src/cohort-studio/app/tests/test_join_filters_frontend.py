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
    page.locator(".topnav-link").filter(has_text="Data Builder").click()
    canvas = page.locator(".jc")
    canvas.get_by_role("button", name="Add person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)
    canvas.get_by_role("button", name="Add genotypes to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(2, timeout=10000)
    config = canvas.get_by_role("region", name="Join configuration")
    expect(config).to_be_visible(timeout=10000)
    return canvas, config


def _keys(config, left="person_id", right="person_id"):
    for label, value in (("Left field, clause 1", left), ("Right field, clause 1", right)):
        box = config.get_by_role("combobox", name=label)
        box.fill(value)
        box.press("Enter")


def test_step_and_base_filters_reach_requests_and_generated_sql(page, app_url):
    validations, previews, joins = [], [], []
    canvas, config = _setup(page, app_url, validations)
    _keys(config)

    # genotypes: dosage >= 1 AND gene in (BRCA1, BRCA2) AND gene is not null
    config.get_by_role("button", name="Add filter to genotypes").click()
    config.get_by_label("genotypes filter 1 column").select_option("dosage")
    config.get_by_label("genotypes filter 1 operator").select_option(">=")
    config.get_by_label("genotypes filter 1 value").fill("1")
    # Only one empty filter row at a time.
    config.get_by_role("button", name="Add filter to genotypes").click()
    expect(config.get_by_role("button", name="Add filter to genotypes")).to_be_disabled()
    config.get_by_label("genotypes filter 2 column").select_option("gene")
    config.get_by_label("genotypes filter 2 operator").select_option("in")
    expect(config.get_by_label("genotypes filter 2 operator")).to_have_value("in")
    config.get_by_label("genotypes filter 2 value").fill("BRCA1, BRCA2")
    # Null checks take no value.
    config.get_by_role("button", name="Add filter to genotypes").click()
    config.get_by_label("genotypes filter 3 column").select_option("gene")
    config.get_by_label("genotypes filter 3 operator").select_option("is not null")
    expect(config.get_by_label("genotypes filter 3 value")).to_have_count(0)
    config.get_by_role("button", name="Apply").click()
    # Start table: status = case (Filters → Add)
    canvas.locator(".jc-filters-summary").get_by_role("button", name="Add").click()
    filters = page.get_by_role("dialog", name="Filters")
    filters.get_by_role("button", name="Add filter to Start table").click()
    filters.get_by_label("Start table filter 1 column").select_option("status")
    filters.get_by_label("Start table filter 1 value").fill("case")
    filters.get_by_role("button", name="Close filters").click()

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

    canvas.get_by_role("button", name="Show SQL").click()
    dialog = page.get_by_role("dialog", name="Generated SQL dialog")
    sql_text = dialog.get_by_label("Generated SQL", exact=True)
    expect(sql_text).to_contain_text("filter_input.dosage >= 1")
    expect(sql_text).to_contain_text("filter_input.gene in ['BRCA1', 'BRCA2']")
    dialog.get_by_role("button", name="Close SQL").click()

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
    canvas.get_by_role("button", name="Preview", exact=True).first.click()
    expect(canvas.locator(".join-result-rows")).to_contain_text("~2", timeout=10000)
    assert previews[-1]["steps"][0]["filters"] == expected_filters
    assert previews[-1]["base_filters"] == expected_base
    canvas.get_by_role("button", name="Save & open in Explore").click()
    expect(page.locator(".tab", has_text="person + genotypes")).to_be_visible(timeout=10000)
    assert joins[-1]["steps"][0]["filters"] == expected_filters
    assert joins[-1]["base_filters"] == expected_base
    assert joins[-1]["steps"][0]["conditions"] == [
        {"left": "person_id", "op": "=", "right": "person_id"}]


def test_filter_rows_validate_quietly_and_lists_round_trip(page, app_url):
    """The shared filter editor in Data Builder: quiet until a row is left,
    quoted list values, and list <-> scalar conversion when the operator changes."""
    validations = []
    canvas, config = _setup(page, app_url, validations)
    run = canvas.get_by_role("button", name="Save & open in Explore")
    expect(run).to_be_disabled()
    _keys(config)

    def wait_filters(expected):
        for _ in range(50):
            if validations and validations[-1]["steps"][0].get("filters") == expected:
                return
            page.wait_for_timeout(100)
        assert validations[-1]["steps"][0].get("filters") == expected, validations[-1]

    def reopen():
        canvas.get_by_role("button", name="Join person to genotypes", exact=False).first.click()
        expect(config).to_be_visible(timeout=10000)

    # An incomplete filter says why once the row is left, and blocks Apply.
    config.get_by_role("button", name="Add filter to genotypes").click()
    column = config.get_by_label("genotypes filter 1 column")
    column.focus()
    column.select_option("dosage")
    expect(config.locator(".join-check.join-error")).to_have_count(0)   # still editing the row
    column.blur()
    expect(config.locator(".join-check.join-error")).to_have_text("Enter a value for dosage.")
    config.get_by_label("genotypes filter 1 value").fill("2")
    expect(config.locator(".join-check.join-error")).to_have_count(0)

    # List values: quoted items may contain commas and doubled quotes.
    config.get_by_role("button", name="Add filter to genotypes").click()
    config.get_by_label("genotypes filter 2 column").select_option("gene")
    config.get_by_label("genotypes filter 2 operator").select_option("in")
    config.get_by_label("genotypes filter 2 value").fill('"Smith, John", Doe ,"say ""hi"""')
    config.get_by_role("button", name="Apply").click()
    expected = {"column": "gene", "op": "in", "value": ["Smith, John", "Doe", 'say "hi"']}
    wait_filters([{"column": "dosage", "op": "=", "value": 2}, expected])
    expect(run).to_be_enabled(timeout=10000)

    # Switching to a single-value operator turns the one quoted list item back into plain text.
    reopen()
    value = config.get_by_label("genotypes filter 2 value")
    value.fill('"Smith, John"')
    config.get_by_label("genotypes filter 2 operator").select_option("=")
    expect(value).to_have_value("Smith, John")
    config.get_by_role("button", name="Apply").click()
    wait_filters([{"column": "dosage", "op": "=", "value": 2},
                  {"column": "gene", "op": "=", "value": "Smith, John"}])
    # And back to a list operator: the value is quoted so it stays one item.
    reopen()
    value = config.get_by_label("genotypes filter 2 value")
    config.get_by_label("genotypes filter 2 operator").select_option("in")
    expect(value).to_have_value('"Smith, John"')
    # A null check in between keeps the list as a list, and a later scalar operator unquotes it.
    value.fill("BRCA1, BRCA2")
    config.get_by_label("genotypes filter 2 operator").select_option("is null")
    config.get_by_label("genotypes filter 2 operator").select_option("in")
    expect(value).to_have_value("BRCA1, BRCA2")
    value.fill('"Smith, John"')
    config.get_by_label("genotypes filter 2 operator").select_option("is null")
    config.get_by_label("genotypes filter 2 operator").select_option("=")
    expect(value).to_have_value("Smith, John")
