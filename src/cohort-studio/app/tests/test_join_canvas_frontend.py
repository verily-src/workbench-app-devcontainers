"""Visual join canvas (Join tab): drag/keyboard building, request mapping, edit, preview, run."""
import os
import re

import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e

SHOTS = os.environ.get("JOIN_CANVAS_SCREENSHOTS", "")

COLUMNS = {
    "person": [{"name": "person_id", "dtype": "int64", "filter_kind": "none"},
               {"name": "status", "dtype": "object", "filter_kind": "categorical"},
               {"name": "birth_date", "dtype": "datetime64[ns]", "filter_kind": "range"},
               {"name": "state", "dtype": "object", "filter_kind": "categorical"}],
    "samples": [{"name": "sample_id", "dtype": "object", "filter_kind": "none"},
                {"name": "person_id", "dtype": "int64", "filter_kind": "none"}],
    "visits": [{"name": "visit_id", "dtype": "int64", "filter_kind": "none"},
               {"name": "person_id", "dtype": "int64", "filter_kind": "none"}],
    "genotypes": [{"name": "sample_id", "dtype": "object", "filter_kind": "none"},
                  {"name": "dosage", "dtype": "int64", "filter_kind": "range"},
                  {"name": "gene", "dtype": "object", "filter_kind": "categorical"}],
}
ROWS = {"person": 1200, "samples": 3400, "visits": 9100, "genotypes": 250000}


def _fulfill(route, body):
    route.fulfill(status=200, content_type="application/json", json=body)


def _ref(table):
    return {"kind": "aurora", "resource_id": "clinical", "schema": "public", "table": table}


def _setup(page, app_url, calls, view_ref=None):
    sources = [{"kind": "aurora", "id": "clinical", "label": "Clinical Aurora"},
               {"kind": "s3", "id": "lake", "label": "Genetics lake"}]
    page.route("**/api/config", lambda route: _fulfill(route, {
        "chart_palette": "verily", "llm": {"provider": "anthropic", "providers": {}}}))
    page.route("**/api/datasources", lambda route: _fulfill(route, {
        "ready": True, "sources": sources, "catalogs_pending": False}))
    page.route("**/api/workflows**", lambda route: _fulfill(route, {
        "available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/views/all", lambda route: _fulfill(route, {"views": [], "unavailable": []}))

    def tables(route):
        calls.setdefault("tables", []).append(route.request.url)
        if "kind=s3" in route.request.url:
            _fulfill(route, [{"name": "variants.parquet", "table": "variants.parquet", "detail": "S3"}])
            return
        _fulfill(route, [{"name": name, "schema": "public", "table": name, "detail": "Aurora",
                          "rows": ROWS[name], "rows_estimated": True, "columns": len(COLUMNS[name])}
                         for name in COLUMNS])
    page.route("**/api/tables?**", tables)
    if view_ref is not None:
        page.route("**/api/views/one?**", lambda route: _fulfill(route, {
            "version": 2, "active": 0, "datasets": [{
                "source": view_ref, "title": "Existing joined result",
                "filters": [], "charts": [], "cohorts": []}]}))

    def open_job(route):
        ref = route.request.post_data_json["source_ref"]
        calls.setdefault("opened", []).append(ref)
        if ref["kind"] == "join":
            result = {"dataset_id": "existing-join", "source": "person + samples + genotypes",
                      "rows": 3, "columns": COLUMNS["person"], "source_ref": ref,
                      "query_scope": "database"}
        else:
            table = ref.get("table") or ref.get("name") or "sql"   # SQL sources have no table
            result = {"dataset_id": f"open-{table}", "source": table, "rows": 2,
                      "columns": COLUMNS.get(table, COLUMNS["person"]), "source_ref": ref,
                      "query_scope": "database"}
        _fulfill(route, {"job_id": "open", "status": "complete", "kind": "open", "result": result})
    page.route("**/api/data-jobs/open", open_job)

    def query(route):
        table = route.request.url.split("/api/datasets/")[1].split("/")[0].replace("open-", "")
        cols = [c["name"] for c in COLUMNS.get(table, COLUMNS["person"])]
        _fulfill(route, {"total": 2, "filtered": 2, "scope": "database", "sampled": False, "charts": [],
                         "rows": {"page": 0, "page_size": 50, "columns": cols,
                                  "data": [[f"{c}-1" for c in cols], [f"{c}-2" for c in cols]]}})
    page.route("**/api/datasets/*/query", query)
    page.route("**/api/joins/recommend", lambda route: _fulfill(route, {
        "candidates": [], "warnings": [],
        "jev": {"status": "not_configured", "configured": False, "model": ""}}))
    page.route("**/api/datasets/join/suggest?**", lambda route: _fulfill(route, []))

    def validate(route):
        body = route.request.post_data_json
        calls.setdefault("validate", []).append(body)
        sql = "SELECT * FROM public.person AS l " + " ".join(
            f"{s['how'].upper()} JOIN {s['alias']}" for s in body["steps"])
        _fulfill(route, {
            "ok": all(s["conditions"] for s in body["steps"]), "engine": "aurora",
            "engine_reason": "Same Aurora source.",
            "generated_sql": {"engine": "aurora", "sql": sql, "copyable_sql": sql,
                              "display_sql": sql, "parameters": {}},
            "capped_inputs": [], "problems": [],
            "base_filters": [{"problem": None} for _ in body.get("base_filters", [])],
            "steps": [{"problems": [], "notes": [],
                       "conditions": [{"problem": None, "note": None} for _ in s["conditions"]],
                       "filters": [{"problem": None} for _ in s.get("filters", [])]}
                      for s in body["steps"]]})
    page.route("**/api/datasets/join/validate", validate)

    def preview_job(route):
        body = route.request.post_data_json
        calls.setdefault("preview", []).append(body)
        cols = ["person_id", "status"] + [f"{s['alias']} → {c['name']}" for s in body["steps"]
                                          for c in COLUMNS[s["right_id"].replace("open-", "")][:1]]
        _fulfill(route, {"job_id": "pv", "kind": "join_preview", "status": "complete", "result": {
            "engine": "aurora", "base_rows": 1200, "rows": None, "total_rows": None,
            "truncated": False, "sample_only": True, "sample_truncated": False,
            "steps": [{"right_rows": 10, "rows": 1180, "truncated": False, "rows_before": 1200,
                       "growth": 1.0, "fanout": False, "estimated": True} for _ in body["steps"]],
            "growth_total": 1.0, "notes": [], "capped_inputs": [], "columns": cols,
            "sample": [[1, "case"] + ["S1"] * (len(cols) - 2), [2, "control"] + [None] * (len(cols) - 2)]}})
    page.route("**/api/data-jobs/join_preview", preview_job)

    def join_job(route):
        body = route.request.post_data_json
        calls.setdefault("join", []).append(body)
        ref = {"kind": "join", "base": _ref(body["base_id"].replace("open-", "")),
               "steps": [{"source": _ref(s["right_id"].replace("open-", "")),
                          **{k: v for k, v in s.items() if k != "right_id"}} for s in body["steps"]]}
        if body.get("base_filters"):
            ref["base_filters"] = body["base_filters"]
        _fulfill(route, {"job_id": "jn", "kind": "join", "status": "complete", "result": {
            "dataset_id": "joined", "source": "person + genotypes", "rows": 2,
            "columns": COLUMNS["person"], "query_scope": "database", "source_ref": ref,
            "join": {"engine": "aurora", "base_rows": 2, "rows": 2, "total_rows": 2,
                     "truncated": False, "steps": [], "notes": [], "capped_inputs": []}}})
    page.route("**/api/data-jobs/join", join_job)

    def close_dataset(route):
        if route.request.method == "DELETE":
            calls.setdefault("closed", []).append(route.request.url)
            _fulfill(route, {"ok": True})
        else:
            route.fallback()
    page.route("**/api/datasets/*", close_dataset)


def _open_canvas(page, first_table="person"):
    if SHOTS:
        page.set_viewport_size({"width": 1480, "height": 960})
    page.locator(".topnav-link").filter(has_text=re.compile(r"^Data Builder$")).click()
    canvas = page.locator(".jc")
    expect(canvas).to_be_visible()
    expect(canvas.locator(f".jc-table-item[data-table='{first_table}']")).to_be_visible(timeout=10000)
    return canvas


def _wait_for(calls, key, predicate, page):
    for _ in range(60):
        if calls.get(key) and predicate(calls[key][-1]):
            return calls[key][-1]
        page.wait_for_timeout(100)
    raise AssertionError(f"{key}: {calls.get(key, [])[-1:]}")


def _pick(canvas, label, text):
    box = canvas.get_by_role("combobox", name=label)
    box.fill(text)
    box.press("Enter")


def _set_keys(canvas, left, right, how=None):
    config = canvas.get_by_role("region", name="Join configuration")
    expect(config).to_be_visible(timeout=10000)
    if how:
        config.get_by_role("radio", name=how, exact=True).click()
    _pick(config, "Left field, clause 1", left)
    _pick(config, "Right field, clause 1", right)
    return config


def test_drag_and_keyboard_build_two_table_join(page, app_url):
    calls = {}
    _setup(page, app_url, calls)
    page.goto(app_url)
    canvas = _open_canvas(page)
    expect(canvas.get_by_text("Drag a table here to start")).to_be_visible()

    # Drag the start table; add the second with the keyboard alternative.
    canvas.locator(".jc-table-item[data-table='person']").drag_to(page.get_by_test_id("join-canvas"))
    expect(canvas.get_by_role("button", name="person (start table). Table details")).to_be_visible(timeout=10000)
    expect(canvas.locator(".jc-node", has_text="person")).to_contain_text("~1,200 rows")
    canvas.get_by_role("button", name="Add genotypes to canvas").click()
    expect(canvas.get_by_role("button", name=re.compile("^Join person to genotypes"))).to_be_visible(timeout=10000)

    # The new link opens its join configuration; nothing is sent until Apply.
    config = _set_keys(canvas, "person_id", "sample_id", how="Inner")
    expect(config).to_contain_text("Returns rows only where person and genotypes have matching values")
    expect(config).to_contain_text("person_id is number and sample_id is text")
    _pick(config, "Right field, clause 1", "dosage")
    config.get_by_role("button", name="Add filter to genotypes").click()
    config.get_by_label("genotypes filter 1 column").select_option("dosage")
    config.get_by_label("genotypes filter 1 operator").select_option(">=")
    config.get_by_label("genotypes filter 1 value").fill("1")
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "join-canvas-config.png"), full_page=False)
    config.get_by_role("button", name="Apply").click()
    expect(config).to_have_count(0)

    # Start-table filter through the top bar's Filters dialog.
    canvas.locator(".jc-filters-summary").get_by_role("button", name="Add").click()
    dialog = page.get_by_role("dialog", name="Filters")
    dialog.get_by_role("button", name="Add filter to Start table").click()
    dialog.get_by_label("Start table filter 1 column").select_option("status")
    dialog.get_by_label("Start table filter 1 value").fill("case")
    dialog.get_by_role("button", name="Done").click()
    expect(canvas.locator(".jc-filters-summary strong")).to_have_text("2")

    expected = {
        "base_id": "open-person", "allow_loaded": False,
        "base_filters": [{"column": "status", "op": "=", "value": "case"}],
        "steps": [{"right_id": "open-genotypes", "how": "inner", "columns": None, "alias": "genotypes",
                   "conditions": [{"left": "person_id", "op": "=", "right": "dosage"}],
                   "filters": [{"column": "dosage", "op": ">=", "value": 1}]}],
    }
    assert _wait_for(calls, "validate", lambda body: body == expected, page) == expected

    # Show SQL with copy.
    canvas.get_by_role("button", name="Show SQL").click()
    expect(page.get_by_label("Generated SQL", exact=True)).to_contain_text("INNER JOIN genotypes")
    page.get_by_role("button", name="Close SQL").click()

    # Preview fills the grid with typed, table-labelled columns and row counts.
    canvas.get_by_role("button", name="Preview", exact=True).first.click()
    grid = canvas.get_by_role("table", name="Joined result rows")
    expect(grid).to_be_visible(timeout=10000)
    expect(grid.locator("th").nth(2)).to_contain_text("genotypes")
    expect(grid.locator("th").nth(2)).to_contain_text("sample_id")
    expect(canvas.get_by_label("Row counts")).to_contain_text("~1,180")
    assert calls["preview"][-1] == expected
    fields = canvas.get_by_role("table", name="Fields")
    expect(fields.get_by_label("Name for genotypes → gene")).to_have_value("genotypes → gene")
    # Start-table fields can be dropped and any field renamed (applied after the join).
    fields.get_by_label("Include state").uncheck()
    fields.get_by_label("Name for genotypes → gene").fill("gene_symbol")
    expect(fields.get_by_label("Name for state")).to_be_disabled()
    canvas.get_by_role("button", name="Preview", exact=True).first.click()
    _wait_for(calls, "preview", lambda body: body.get("output") == {
        "exclude": ["state"], "rename": {"genotypes → gene": "gene_symbol"}}, page)
    # Showing an input table and changing the join keeps the renames.
    canvas.get_by_label("Preview table").select_option(label="genotypes")
    canvas.get_by_role("button", name=re.compile("^Join person to genotypes")).click()
    config = canvas.get_by_role("region", name="Join configuration")
    config.get_by_role("radio", name="Left", exact=True).click()
    config.get_by_role("button", name="Apply").click()
    canvas.get_by_label("Preview table").select_option(label="Joined result")
    canvas.get_by_role("button", name="Preview", exact=True).first.click()
    _wait_for(calls, "preview", lambda body: body.get("output", {}).get("rename") == {
        "genotypes → gene": "gene_symbol"} and body["steps"][0]["how"] == "left", page)
    canvas.get_by_role("button", name=re.compile("^Join person to genotypes")).click()
    config.get_by_role("radio", name="Inner", exact=True).click()
    config.get_by_role("button", name="Apply").click()
    # Restoring the defaults sends no output at all.
    fields.get_by_label("Include state").check()
    fields.get_by_label("Name for genotypes → gene").fill("genotypes → gene")
    canvas.get_by_role("button", name="Preview", exact=True).first.click()
    _wait_for(calls, "preview", lambda body: "output" not in body, page)
    # Excluding a joined field changes the request's columns.
    fields.get_by_label("Include genotypes → gene").uncheck()
    _wait_for(calls, "validate", lambda body: body["steps"][0]["columns"] == ["sample_id", "dosage"], page)
    fields.get_by_label("Include genotypes → gene").check()
    _wait_for(calls, "validate", lambda body: body["steps"][0]["columns"] is None, page)
    # A single canvas table previews its own rows.
    canvas.get_by_label("Preview table").select_option(label="genotypes")
    expect(canvas.get_by_role("table", name="genotypes rows")).to_contain_text("dosage-1")
    canvas.get_by_label("Preview table").select_option(label="Joined result")
    if SHOTS:
        canvas.get_by_role("button", name="Preview", exact=True).first.click()
        expect(canvas.get_by_role("table", name="Joined result rows")).to_be_visible(timeout=10000)
        page.screenshot(path=os.path.join(SHOTS, "join-canvas-grid.png"), full_page=False)

    # Create opens the joined result as a tab in Explore, named after the model.
    canvas.get_by_role("textbox", name="Join name").fill("Person genotypes")
    canvas.get_by_role("button", name="Save & open in Explore").click()
    expect(page.locator(".tab", has_text="Person genotypes")).to_be_visible(timeout=10000)
    expect(canvas).to_be_hidden()
    assert calls["join"][-1] == expected
    # Canvas inputs stay open after a live join (the canvas keeps its draft).
    assert not any("/api/datasets/open-" in url for url in calls.get("closed", []))


def test_three_table_tree_orders_steps_and_resolves_left_aliases(page, app_url):
    calls = {}
    _setup(page, app_url, calls)
    page.goto(app_url)
    canvas = _open_canvas(page)
    target = page.get_by_test_id("join-canvas")
    canvas.get_by_role("button", name="Add person to canvas").click()
    expect(canvas.locator(".jc-node", has_text="person")).to_be_visible(timeout=10000)
    # Drop samples onto the person card: a child of person.
    canvas.locator(".jc-table-item[data-table='samples']").drag_to(canvas.locator(".jc-node", has_text="person"))
    _set_keys(canvas, "person_id", "person_id")
    canvas.get_by_role("button", name="Apply").click()
    # Drop visits on empty canvas: joins to the start table.
    canvas.locator(".jc-table-item[data-table='visits']").drag_to(target, target_position={"x": 8, "y": 8})
    config = _set_keys(canvas, "person_id", "person_id", how="Left")
    config.get_by_role("button", name="Apply").click()
    # Grandchild: select samples, then add genotypes with the keyboard.
    canvas.get_by_role("button", name="samples. Table details").click()
    canvas.get_by_role("button", name="Add genotypes to canvas").click()
    expect(canvas.get_by_role("button", name=re.compile("^Join samples to genotypes"))).to_be_visible(timeout=10000)
    config = _set_keys(canvas, "sample_id", "sample_id", how="Outer")
    config.get_by_role("button", name="Apply").click()
    expect(canvas.locator(".jc-badge")).to_have_count(3)

    def cond(left, right):
        return [{"left": left, "op": "=", "right": right}]
    expected_steps = [
        {"right_id": "open-samples", "how": "left", "columns": None, "alias": "samples",
         "conditions": cond("person_id", "person_id")},
        {"right_id": "open-visits", "how": "left", "columns": None, "alias": "visits",
         "conditions": cond("person_id", "person_id")},
        {"right_id": "open-genotypes", "how": "full", "columns": None, "alias": "genotypes",
         "conditions": cond("samples → sample_id", "sample_id")},
    ]
    body = _wait_for(calls, "validate", lambda b: b["steps"] == expected_steps, page)
    assert body["base_id"] == "open-person"

    # Renaming a joined table's alias updates the references of tables joined to it.
    canvas.get_by_role("button", name="samples. Table details").click()
    details = canvas.get_by_role("region", name="samples details")
    details.get_by_label("Name joined columns as").fill("s")
    _wait_for(calls, "validate", lambda b: b["steps"][2]["conditions"] == cond("s → sample_id", "sample_id")
              and b["steps"][0]["alias"] == "s", page)
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "join-canvas-tree.png"), full_page=False)
    # Re-parent visits under samples with the "Join to" select (non-drag alternative).
    canvas.get_by_role("button", name="visits. Table details").click()
    canvas.get_by_label("Join visits to").select_option(label="samples")
    _set_keys(canvas, "person_id", "person_id")
    canvas.get_by_role("button", name="Apply").click()
    _wait_for(calls, "validate", lambda b: b["steps"][1]["conditions"] == cond("s → person_id", "person_id"), page)
    # Removing samples removes the tables joined to it.
    canvas.get_by_role("button", name="Remove samples").click()
    expect(canvas.locator(".jc-node")).to_have_count(1)


def test_edit_join_in_canvas_reconstructs_tree(page, app_url):
    calls = {}
    original = {
        "kind": "join", "base": _ref("person"),
        "base_filters": [{"column": "status", "op": "=", "value": "case"}],
        "steps": [
            {"source": _ref("samples"), "how": "inner", "columns": None, "alias": "samples",
             "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}]},
            {"source": _ref("genotypes"), "how": "left", "columns": ["dosage"], "alias": "genotypes",
             "conditions": [{"left": "samples → sample_id", "op": "=", "right": "sample_id"}],
             "filters": [{"column": "gene", "op": "in", "value": ["BRCA1", "BRCA2"]}]},
        ],
        "output": {"exclude": ["state"], "rename": {"genotypes → dosage": "dose"}},
    }
    _setup(page, app_url, calls, view_ref=original)
    page.goto(f"{app_url}/#view=aurora:clinical:existing")
    expect(page.locator(".tab.active")).to_contain_text("Existing joined result", timeout=15000)
    page.get_by_role("button", name="Edit in Data Builder").click()
    canvas = page.locator(".jc")
    expect(canvas).to_be_visible()
    expect(canvas.get_by_role("textbox", name="Join name")).to_have_value("Existing joined result (edited)")
    expect(canvas.locator(".jc-node")).to_have_count(3, timeout=10000)
    expect(canvas.get_by_role("button", name=re.compile("^Join person to samples: Inner join"))).to_be_visible()
    expect(canvas.get_by_role("button", name=re.compile("^Join samples to genotypes: Left join"))).to_be_visible()
    expected = {
        "base_id": "open-person", "allow_loaded": False, "base_filters": original["base_filters"],
        "steps": [{"right_id": f"open-{s['source']['table']}",
                   **{k: v for k, v in s.items() if k != "source"}} for s in original["steps"]],
    }
    assert _wait_for(calls, "validate", lambda b: b == expected, page) == expected
    # The saved field choices come back with the recipe.
    canvas.get_by_role("button", name="Preview", exact=True).first.click()
    _wait_for(calls, "preview", lambda b: b.get("output") == original["output"], page)
    canvas.get_by_role("button", name=re.compile("^Join samples to genotypes")).click()
    config = canvas.get_by_role("region", name="Join configuration")
    expect(config.get_by_role("combobox", name="Left field, clause 1")).to_have_value("sample_id")
    expect(config.get_by_role("radio", name="Left", exact=True)).to_have_attribute("aria-checked", "true")
    expect(config.get_by_label("genotypes filter 1 value")).to_have_value("BRCA1, BRCA2")
    config.get_by_role("button", name="Cancel").click()
    canvas.get_by_role("button", name="Save & open in Explore").click()
    expect(page.locator(".tab", has_text="Existing joined result (edited)")).to_be_visible(timeout=10000)
    expect(page.locator(".tab", has_text="Existing joined result")).to_have_count(2)
    assert calls["join"][-1] == {**expected, "output": original["output"]}


def test_join_entry_points_open_data_builder(page, app_url):
    """There is one join builder: "Join tables" opens Data Builder, where open
    Explore tabs can be added to the canvas."""
    calls = {}
    _setup(page, app_url, calls)
    page.goto(app_url)
    page.get_by_role("button", name="Join tables").click()
    canvas = page.locator(".jc")
    expect(canvas).to_be_visible()
    expect(page.locator(".join-panel")).to_have_count(0)
    canvas.get_by_role("button", name="Cancel", exact=True).click()
    # Open a table in Explore, then "⋈ Join" it.
    page.get_by_label("Source type", exact=True).select_option("aurora")
    page.get_by_label("Datasource", exact=True).select_option("aurora:clinical")
    page.get_by_label("Schema", exact=True).select_option("public")
    page.get_by_label("Table", exact=True).select_option("person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab.active")).to_contain_text("person", timeout=10000)
    expect(page.get_by_role("button", name="Edit join")).to_have_count(0)
    # No join button on Explore tabs: open tabs are offered in Data Builder instead.
    expect(page.locator(".tab-join")).to_have_count(0)
    page.locator(".topnav-link").filter(has_text=re.compile(r"^Data Builder$")).click()
    canvas.get_by_role("group", name="Open tabs").get_by_role("button", name="Add person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)


def _extract_result(dataset_id, rows, refreshed_at):
    ref = {"kind": "aurora", "resource_id": "clinical", "table": "person_samples"}
    return {"dataset_id": dataset_id, "source": "person_samples", "rows": rows,
            "columns": COLUMNS["person"], "source_ref": ref, "query_scope": "database",
            "extract": {"table": "person_samples", "title": "Person samples", "rows": rows,
                        "created_at": "2026-11-06T10:00:00+00:00", "refreshed_at": refreshed_at,
                        "refreshable": True}}


def test_extract_mode_writes_every_row_refreshes_and_save_reopens(page, app_url):
    calls = {}
    _setup(page, app_url, calls)

    def extract(route):
        calls.setdefault("extract", []).append(route.request.post_data_json)
        _fulfill(route, {"job_id": "x1", "kind": "extract", "status": "complete",
                         "result": _extract_result("extract-1", 250_000, "2026-11-06T10:00:00+00:00")})
    page.route("**/api/data-jobs/extract", extract)

    def refresh(route):
        calls.setdefault("refresh", []).append(route.request.post_data_json)
        _fulfill(route, {"job_id": "x2", "kind": "refresh_extract", "status": "complete",
                         "result": _extract_result("extract-2", 260_000, "2026-11-06T11:00:00+00:00")})
    page.route("**/api/data-jobs/refresh_extract", refresh)
    page.goto(app_url)
    canvas = _open_canvas(page)
    canvas.get_by_role("button", name="Add person to canvas").click()
    expect(canvas.locator(".jc-node", has_text="person")).to_be_visible(timeout=10000)
    canvas.get_by_role("button", name="Add samples to canvas").click()
    _set_keys(canvas, "person_id", "person_id")
    canvas.get_by_role("button", name="Apply").click()

    # Save keeps the recipe in this browser; Cancel clears the canvas.
    canvas.get_by_role("textbox", name="Join name").fill("Person samples")
    canvas.get_by_role("button", name="Save", exact=True).click()
    expect(canvas.get_by_role("status").filter(has_text="Saved “Person samples”")).to_be_visible()
    canvas.get_by_role("button", name="Cancel", exact=True).click()
    expect(canvas).to_be_hidden()
    canvas = _open_canvas(page)
    expect(canvas.locator(".jc-node")).to_have_count(0)
    canvas.get_by_role("button", name="Reopen saved join “Person samples”").click()
    expect(canvas.locator(".jc-node")).to_have_count(2, timeout=10000)
    expect(canvas.get_by_role("textbox", name="Join name")).to_have_value("Person samples")

    # Extract: join, save the rows as a database table, open that table.
    canvas.get_by_role("radio", name="Extract").check()
    expect(canvas.get_by_label("Extract table name")).to_have_value("person_samples")
    canvas.get_by_role("button", name="Save & open in Explore").click()
    expect(page.locator(".tab", has_text="Person samples")).to_be_visible(timeout=10000)
    # One extract job writes every row and opens the new table.
    assert calls["extract"][-1] == {"dataset_id": "joined", "kind": "aurora", "resource_id": "clinical",
                                    "table": "person_samples", "title": "Person samples"}
    assert any(url.endswith("/api/datasets/joined") for url in calls["closed"])   # intermediate join closed

    # The extract tab says it is an extract and can be refreshed in place.
    bar = page.get_by_role("group", name="Extract")
    expect(bar).to_have_attribute("title", re.compile("250,000 rows"))
    expect(page.locator(".hero .count")).to_be_visible()
    bar.get_by_role("button", name="Refresh extract").click()
    expect(bar).to_have_attribute("title", re.compile("260,000 rows"))
    assert calls["refresh"][-1] == {"kind": "aurora", "resource_id": "clinical", "table": "person_samples"}
    expect(page.locator(".tab")).to_have_count(1)
    expect(page.locator(".tab.active")).to_contain_text("Person samples")
    for _ in range(50):  # the replaced dataset is closed
        if any(url.endswith("/api/datasets/extract-1") for url in calls["closed"]):
            break
        page.wait_for_timeout(100)
    else:
        raise AssertionError(calls["closed"])
    assert calls["join"][-1]["steps"][0]["conditions"] == [
        {"left": "person_id", "op": "=", "right": "person_id"}]
    # The recipe is stored under a key scoped to this app's path (apps share an origin).
    keys = page.evaluate("Object.keys(localStorage)")
    path = page.evaluate("window.location.pathname")
    assert f"cohort-studio.join-canvas.saved:{path}" in keys
    assert "cohort-studio.join-canvas.saved" not in keys


def test_saved_join_from_another_app_path_is_not_offered(page, app_url):
    calls = {}
    _setup(page, app_url, calls)
    recipe = {"name": "Other app join", "savedAt": "2026-01-01T00:00:00Z", "ref": {
        "kind": "join", "base": _ref("person"),
        "steps": [{"source": _ref("samples"), "how": "left", "columns": None, "alias": "samples",
                   "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}]}]}}
    page.add_init_script(f"""
      const recipe = {__import__("json").dumps(recipe)};
      localStorage.setItem("cohort-studio.join-canvas.saved", JSON.stringify(recipe));
      localStorage.setItem("cohort-studio.join-canvas.saved:/some/other/app/", JSON.stringify(recipe));
    """)
    page.goto(app_url)
    canvas = _open_canvas(page)
    expect(canvas.get_by_role("button", name=re.compile("^Reopen saved join"))).to_have_count(0)


def test_removing_one_of_two_steps_sharing_a_source_keeps_its_dataset(page, app_url):
    calls = {}
    cond = [{"left": "person_id", "op": "=", "right": "person_id"}]
    original = {
        "kind": "join", "base": _ref("person"),
        "steps": [
            {"source": _ref("samples"), "how": "left", "columns": None, "alias": "samples",
             "conditions": cond},
            {"source": _ref("samples"), "how": "inner", "columns": None, "alias": "samples_again",
             "conditions": cond},
        ],
    }
    _setup(page, app_url, calls, view_ref=original)
    page.goto(f"{app_url}/#view=aurora:clinical:existing")
    expect(page.locator(".tab.active")).to_contain_text("Existing joined result", timeout=15000)
    page.get_by_role("button", name="Edit in Data Builder").click()
    canvas = page.locator(".jc")
    expect(canvas.locator(".jc-node")).to_have_count(3, timeout=10000)
    _wait_for(calls, "validate", lambda b: [s["right_id"] for s in b["steps"]]
              == ["open-samples", "open-samples"], page)
    # The first samples node owns the shared dataset; removing it must not close it.
    canvas.get_by_role("button", name="Remove samples", exact=True).first.click()
    expect(canvas.locator(".jc-node")).to_have_count(2)
    body = _wait_for(calls, "validate", lambda b: len(b["steps"]) == 1, page)
    assert body["steps"][0]["right_id"] == "open-samples"
    assert body["steps"][0]["alias"] == "samples_again"
    page.wait_for_timeout(300)
    assert not any(url.endswith("/api/datasets/open-samples") for url in calls.get("closed", []))
    # Removing the last user closes it.
    canvas.get_by_role("button", name="Remove samples", exact=True).click()
    expect(canvas.locator(".jc-node")).to_have_count(1)
    for _ in range(30):
        if any(url.endswith("/api/datasets/open-samples") for url in calls.get("closed", [])):
            break
        page.wait_for_timeout(100)
    assert sum(url.endswith("/api/datasets/open-samples") for url in calls.get("closed", [])) == 1


def test_loaded_status_card_shows_only_on_explore(page, app_url):
    calls = {}
    _setup(page, app_url, calls, view_ref=_ref("person"))
    page.goto(f"{app_url}/#view=aurora:clinical:existing")
    expect(page.locator(".tab.active")).to_contain_text("Existing joined result", timeout=15000)
    loaded = page.locator(".data-job-done")
    expect(loaded).to_be_visible()
    page.locator(".topnav-link").filter(has_text=re.compile(r"^Data Builder$")).click()
    expect(page.locator(".jc")).to_be_visible()
    expect(loaded).to_have_count(0)
    page.locator(".topnav-link").filter(has_text=re.compile(r"^Explore Cohort$")).click()
    expect(loaded).to_be_visible()


def test_canvas_names_join_from_tables_and_long_names_fit(page, app_url):
    """The join is named after its tables until the user types a name, and
    long schema-qualified names and big row counts stay inside the cards."""
    calls = {}
    _setup(page, app_url, calls)
    schema = "cms_synpuf_100k_with_a_long_schema_name"
    page.route("**/api/tables?**", lambda route: _fulfill(route, [
        {"name": "variants.parquet", "table": "variants.parquet", "detail": "S3"}]
        if "kind=s3" in route.request.url else [
        {"name": f"{schema}.{name}", "schema": schema, "table": name, "detail": "Aurora",
         "rows": 12_486_453, "rows_estimated": True, "columns": len(COLUMNS[name])}
        for name in COLUMNS]))
    page.goto(app_url)
    canvas = _open_canvas(page, f"{schema}.person")
    name_box = canvas.get_by_role("textbox", name="Join name")
    expect(name_box).to_have_value("New join")
    expect(canvas.locator(".jc-name .jc-label")).to_have_text("Name")

    canvas.get_by_role("button", name=f"Add {schema}.person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)
    expect(name_box).to_have_value("person")
    canvas.get_by_role("button", name=f"Add {schema}.genotypes to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(2, timeout=10000)
    expect(name_box).to_have_value("person + genotypes")

    node = canvas.locator(".jc-node").first
    expect(node.locator(".jc-node-title")).to_have_attribute("title", f"{schema}.person")
    expect(node.locator(".jc-node-title > span").first).to_have_text("person")
    expect(node).to_contain_text("~12.5M rows")
    # Nothing in a card spills past its border.
    overflow = page.evaluate("""() => [...document.querySelectorAll('.jc-node')].flatMap((card) => {
        const box = card.getBoundingClientRect();
        return [...card.querySelectorAll('.jc-node-main *')]
          .filter((el) => el.getClientRects().length)
          .map((el) => el.getBoundingClientRect())
          .filter((r) => r.right > box.right + 1 || r.left < box.left - 1)
          .map((r) => Math.round(r.right - box.right));
    })""")
    assert overflow == [], overflow
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, "join-canvas-long-names.png"), full_page=False)

    # File names keep their extension (only schema.table names are shortened).
    canvas.get_by_role("button", name=re.compile("^Genetics lake")).click()
    canvas.get_by_role("button", name="Add variants.parquet to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(3, timeout=10000)
    expect(canvas.locator(".jc-node").nth(2).locator(".jc-node-title > span").first).to_have_text("variants.parquet")
    expect(name_box).to_have_value("person + genotypes + variants.parquet")
    canvas.get_by_role("button", name="Remove variants.parquet", exact=True).click()
    expect(canvas.locator(".jc-node")).to_have_count(2)
    canvas.get_by_role("button", name=re.compile("^Clinical Aurora")).click()

    # A typed name sticks while more tables are added.
    name_box.fill("Synpuf cohort")
    canvas.get_by_role("button", name=f"Add {schema}.visits to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(3, timeout=10000)
    expect(name_box).to_have_value("Synpuf cohort")


def test_bigquery_join_asks_before_reading_full_tables(page, app_url):
    calls = {}
    _setup(page, app_url, calls)
    page.route("**/api/datasources", lambda route: _fulfill(route, {
        "ready": True, "catalogs_pending": False,
        "sources": [{"kind": "bq", "id": "warehouse", "label": "Warehouse BigQuery"}]}))
    page.route("**/api/tables?**", lambda route: _fulfill(route, [
        {"name": name, "table": name, "schema": "genomics", "detail": "BigQuery", "columns": len(COLUMNS[name])}
        for name in ("person", "genotypes")]))

    def open_bq(route):
        ref = route.request.post_data_json["source_ref"]
        calls.setdefault("opened", []).append(ref)
        _fulfill(route, {"job_id": "open", "status": "complete", "kind": "open", "result": {
            "dataset_id": f"open-{ref['table']}", "source": ref["table"], "rows": 2, "capped": True,
            "columns": COLUMNS[ref["table"]], "source_ref": ref, "query_scope": "loaded"}})
    page.route("**/api/data-jobs/open", open_bq)
    page.goto(app_url)
    page.locator(".topnav-link").filter(has_text=re.compile(r"^Data Builder$")).click()
    canvas = page.locator(".jc")
    canvas.get_by_role("button", name="Add person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)
    canvas.get_by_role("button", name="Add genotypes to canvas").click()
    _set_keys(canvas, "person_id", "sample_id")
    canvas.get_by_role("button", name="Apply").click()
    consent = canvas.get_by_label(re.compile("Allow reading the full BigQuery tables"))
    expect(consent).to_be_visible()
    expect(canvas.locator(".jc-consent")).to_contain_text("BigQuery bills by bytes scanned")
    expect(canvas.locator(".join-disabled-reason")).to_contain_text("Allow reading the full BigQuery tables")
    expect(canvas.get_by_role("button", name="Save & open in Explore")).to_be_disabled()
    consent.check()
    canvas.get_by_role("button", name="Save & open in Explore").click()
    _wait_for(calls, "join", lambda body: body["allow_loaded"] is True, page)


def test_running_job_cards_stay_off_the_data_builder(page, app_url):
    calls = {}
    _setup(page, app_url, calls)
    page.route("**/api/data-jobs/open", lambda route: _fulfill(route, {
        "job_id": "slow", "kind": "open", "status": "running", "label": "person from clinical"}))
    page.route("**/api/data-jobs/slow", lambda route: _fulfill(route, {
        "job_id": "slow", "kind": "open", "status": "running", "label": "person from clinical"}))
    page.goto(app_url)
    canvas = _open_canvas(page)
    canvas.get_by_role("button", name="Add person to canvas").click()
    expect(canvas.locator(".jc-node")).to_contain_text("Opening…", timeout=10000)
    page.wait_for_timeout(1000)  # a few polls
    expect(page.locator(".data-jobs")).to_have_count(0)
    page.locator(".topnav-link").filter(has_text=re.compile(r"^Explore Cohort$")).click()
    expect(page.locator(".data-jobs")).to_contain_text("person from clinical", timeout=10000)


def _sql_routes(page, calls):
    page.route("**/api/sql/lint", lambda route: _fulfill(route, {"ok": True, "message": "Looks valid."}))
    page.route("**/api/sql/completions**", lambda route: _fulfill(route, {"schemas": [], "keywords": []}))

    def preview(route):
        calls.setdefault("sql_preview", []).append(route.request.post_data_json)
        _fulfill(route, {"source_ref": {"kind": "sql", "resource_id": "clinical", "sql": "x"},
                         "columns": ["person_id", "n"], "sample": [[1, 3], [2, 5]], "rows": 2, "truncated": False})
    page.route("**/api/sql/preview", preview)


def test_sql_mode_previews_and_opens_a_sql_tab(page, app_url):
    calls = {}
    _setup(page, app_url, calls)
    _sql_routes(page, calls)
    page.goto(app_url)
    canvas = _open_canvas(page)
    canvas.get_by_role("radio", name="SQL", exact=True).click()
    sql = canvas.get_by_role("region", name="SQL builder")
    expect(sql.get_by_label("SQL database")).to_have_value("clinical")
    expect(canvas.get_by_role("button", name="Save & open in Explore")).to_be_disabled()
    query = "SELECT person_id, count(*) AS n FROM public.samples GROUP BY 1"
    sql.get_by_label("Data Builder SQL").fill(query)
    canvas.get_by_role("button", name="Preview", exact=True).click()
    expect(sql.get_by_role("table", name="SQL result rows")).to_contain_text("person_id")
    assert calls["sql_preview"][-1] == {"resource_id": "clinical", "sql": query}
    expect(canvas.get_by_role("button", name="Save", exact=True)).to_be_disabled()
    canvas.get_by_role("textbox", name="Join name").fill("Samples per person")
    canvas.get_by_role("button", name="Save & open in Explore").click()
    _wait_for(calls, "opened", lambda ref: ref.get("kind") == "sql", page)
    assert calls["opened"][-1] == {"kind": "sql", "resource_id": "clinical", "sql": query,
                                   "name": "Samples per person"}
    expect(page.locator(".tab", has_text="Samples per person")).to_be_visible(timeout=10000)


def test_canvas_join_can_be_edited_as_sql(page, app_url):
    calls = {}
    _setup(page, app_url, calls)
    _sql_routes(page, calls)
    page.goto(app_url)
    canvas = _open_canvas(page)
    canvas.get_by_role("button", name="Add person to canvas").click()
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)
    canvas.get_by_role("button", name="Add samples to canvas").click()
    _set_keys(canvas, "person_id", "person_id")
    canvas.get_by_role("button", name="Apply").click()
    _wait_for(calls, "validate", lambda body: body["steps"][0]["conditions"], page)
    canvas.get_by_role("button", name="Show SQL").click()
    page.get_by_role("dialog", name="Generated SQL dialog").get_by_role("button", name="Edit as SQL").click()
    sql = canvas.get_by_role("region", name="SQL builder")
    expect(sql.get_by_label("Data Builder SQL")).to_have_value(re.compile(r"^SELECT \* FROM public.person AS l LEFT JOIN samples"))
    expect(sql.get_by_label("SQL database")).to_have_value("clinical")
    # Back to the canvas: the visual join is still there.
    canvas.get_by_role("radio", name="Visual", exact=True).click()
    expect(canvas.locator(".jc-node")).to_have_count(2)


def test_edit_extract_reopens_its_join_and_rewrites_the_table(page, app_url):
    calls = {}
    extract_ref = {"kind": "aurora", "resource_id": "clinical", "table": "person_samples"}
    recipe = {"kind": "join", "base": _ref("person"), "steps": [
        {"source": _ref("samples"), "how": "left", "columns": None, "alias": "samples",
         "conditions": [{"left": "person_id", "op": "=", "right": "person_id"}]}],
        "output": {"exclude": ["state"]}}
    info = {"table": "person_samples", "title": "Person samples", "rows": 42, "refreshable": True,
            "created_at": "2026-11-06T10:00:00+00:00", "refreshed_at": "2026-11-06T10:00:00+00:00",
            "recipe": recipe}
    _setup(page, app_url, calls, view_ref=extract_ref)
    page.route("**/api/extracts/info?**", lambda route: _fulfill(route, {"extract": info}))

    def extract(route):
        calls.setdefault("extract", []).append(route.request.post_data_json)
        body = route.request.post_data_json
        _fulfill(route, {"job_id": "x1", "kind": "extract", "status": "complete", "result": {
            "dataset_id": f"extract-{len(calls['extract'])}", "source": body["table"], "rows": 50,
            "columns": COLUMNS["person"],
            "source_ref": {**extract_ref, "table": body["table"]}, "query_scope": "database",
            "extract": {**info, "rows": 50, "refreshed_at": "2026-11-06T12:00:00+00:00"}}})
    page.route("**/api/data-jobs/extract", extract)
    page.goto(f"{app_url}/#view=aurora:clinical:existing")
    expect(page.locator(".tab.active")).to_contain_text("Existing joined result", timeout=15000)
    bar = page.get_by_role("group", name="Extract")
    bar.get_by_role("button", name="Edit in Data Builder").click()
    canvas = page.locator(".jc")
    expect(canvas.locator(".jc-node")).to_have_count(2, timeout=10000)
    expect(canvas.get_by_role("radio", name="Extract")).to_be_checked()
    expect(canvas.get_by_label("Extract table name")).to_have_value("person_samples")
    expect(canvas.get_by_role("textbox", name="Join name")).to_have_value("Existing joined result")
    canvas.get_by_role("button", name="Save & open in Explore").click()
    _wait_for(calls, "extract", lambda body: body["table"] == "person_samples", page)
    # The join ran with the saved field choices, and the tab was replaced, not duplicated.
    assert calls["join"][-1]["output"] == {"exclude": ["state"]}
    expect(page.locator(".tab")).to_have_count(1)
    expect(bar).to_have_attribute("title", re.compile("50 rows"))

    # Saving the edit to another table opens a new tab and keeps the original.
    bar.get_by_role("button", name="Edit in Data Builder").click()
    expect(canvas.get_by_label("Extract table name")).to_have_value("person_samples")
    canvas.get_by_label("Extract table name").fill("person_samples_v2")
    canvas.get_by_role("button", name="Save & open in Explore").click()
    _wait_for(calls, "extract", lambda body: body["table"] == "person_samples_v2", page)
    expect(page.locator(".tab")).to_have_count(2)

    # Cancel drops the extract destination: the next join is Live again.
    page.locator(".topnav-link").filter(has_text=re.compile(r"^Data Builder$")).click()
    canvas.get_by_role("button", name="Cancel", exact=True).click()
    page.locator(".topnav-link").filter(has_text=re.compile(r"^Data Builder$")).click()
    expect(canvas.get_by_role("radio", name="Live")).to_be_checked()
