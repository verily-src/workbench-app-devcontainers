import pytest
from playwright.sync_api import Page, expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e

CATALOG = {
    "resource_id": "fixture",
    "schemas": [{"name": "cdm", "omop": {"role": "cdm", "vocab_schema": "cdm", "default": True}},
                {"name": "public"}],
    "tables": [
        {"schema": "cdm", "name": "person", "kind": "table", "omop": True, "columns": [
            {"name": "person_id", "type": "bigint"},
            {"name": "year_of_birth", "type": "integer"},
            {"name": "gender_concept_id", "type": "integer"}]},
        {"schema": "cdm", "name": "visit_occurrence", "kind": "table", "omop": True, "columns": [
            {"name": "visit_occurrence_id", "type": "bigint"},
            {"name": "person_id", "type": "bigint"}]},
        {"schema": "public", "name": "Mixed Case", "kind": "view", "columns": [
            {"name": "Sample ID", "type": "text"}, {"name": "order", "type": "text"}]},
    ],
    "column_count": 7, "truncated": False, "limits": {"tables": 1000, "columns": 2000},
}


def _open_editor(page: Page, app_url: str, requests: list):
    def fulfill(route, body, status=200):
        route.fulfill(status=status, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "fixture", "label": "Aurora fixture"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0}))
    page.route("**/api/tables?**", lambda route: fulfill(route, []))
    page.route("**/api/sql/lint", lambda route: fulfill(route, {"ok": True, "message": "Valid read-only SELECT."}))

    def completions(route):
        requests.append(route.request.url)
        fulfill(route, CATALOG)
    page.route("**/api/sql/completions?**", completions)

    page.goto(app_url)
    expect(page.get_by_text("No data loaded")).to_be_visible(timeout=15000)
    page.locator(".topnav-link").filter(has_text="Data Builder").click()
    page.locator(".jc").get_by_role("radio", name="SQL", exact=True).click()
    panel = page.get_by_role("region", name="SQL builder")
    editor = panel.get_by_label("Data Builder SQL")
    editor.click()
    return panel, editor


def _options(panel):
    return panel.get_by_role("listbox", name="SQL suggestions").get_by_role("option")


def _caret(editor):
    return editor.evaluate("el => [el.selectionStart, el.selectionEnd]")


def test_sql_autocomplete_suggests_schemas_tables_and_columns(page: Page, app_url: str):
    requests = []
    panel, editor = _open_editor(page, app_url, requests)
    listbox = panel.get_by_role("listbox", name="SQL suggestions")
    expect(editor).to_have_attribute("aria-autocomplete", "list")

    # Schema names after FROM, marked as OMOP.
    editor.press_sequentially("SELECT * FROM cd")
    expect(listbox).to_be_visible()
    assert "resource_id=fixture" in requests[0]
    first = _options(panel).first
    expect(first).to_contain_text("cdm")
    expect(first).to_contain_text("OMOP CDM")
    expect(first).to_have_attribute("aria-selected", "true")
    assert editor.get_attribute("aria-controls") == listbox.get_attribute("id")
    assert editor.get_attribute("aria-activedescendant") == first.get_attribute("id")

    # Tab accepts: text is inserted, caret ends after it.
    editor.press("Tab")
    expect(listbox).to_have_count(0)
    expect(editor).to_have_value("SELECT * FROM cdm")
    assert _caret(editor) == [17, 17]

    # `schema.` → that schema's tables.
    editor.press_sequentially(".pe")
    expect(_options(panel)).to_have_count(1)
    expect(_options(panel).first).to_contain_text("person")
    editor.press("Enter")
    expect(editor).to_have_value("SELECT * FROM cdm.person")
    assert _caret(editor) == [24, 24]

    # Enter with the popup closed inserts a newline.
    editor.press_sequentially(" p")
    expect(listbox).to_have_count(0)  # alias position: no table/keyword starts with "p"
    editor.press("Enter")
    expect(editor).to_have_value("SELECT * FROM cdm.person p\n")

    # `alias.` → that table's columns (the FROM clause comes after the caret).
    editor.fill("SELECT  FROM cdm.person p")
    editor.evaluate("el => el.setSelectionRange(7, 7)")
    editor.press_sequentially("p.")
    expect(listbox).to_be_visible()
    labels = _options(panel).locator(".sql-complete-label").all_inner_texts()
    assert labels == ["person_id", "year_of_birth", "gender_concept_id"]
    expect(_options(panel).nth(1)).to_contain_text("integer")
    editor.press("ArrowDown")
    expect(_options(panel).nth(1)).to_have_attribute("aria-selected", "true")
    editor.press("Enter")
    expect(editor).to_have_value("SELECT p.year_of_birth FROM cdm.person p")
    assert _caret(editor) == [22, 22]

    # Unqualified columns in SELECT are scoped to the referenced tables.
    editor.press_sequentially(", vis")
    expect(listbox).to_have_count(0)  # visit_occurrence_id is not in cdm.person
    editor.press_sequentially(", gen")
    expect(_options(panel).first).to_contain_text("gender_concept_id")

    # Esc closes; Enter then inserts a newline.
    editor.press("Escape")
    expect(listbox).to_have_count(0)
    expect(panel).to_be_visible()
    editor.press("Enter")
    expect(editor).to_have_value("SELECT p.year_of_birth, vis, gen\n FROM cdm.person p")

    # Ctrl+Space opens without typing; mouse click accepts.
    editor.fill("SELECT * FROM ")
    editor.press("Control+Space")
    expect(listbox).to_be_visible()
    _options(panel).filter(has_text="cdm.visit_occurrence").click()
    expect(editor).to_have_value("SELECT * FROM cdm.visit_occurrence")
    expect(editor).to_be_focused()

    # Identifiers that need quotes are inserted quoted.
    editor.fill('SELECT  FROM public."Mixed Case" m')
    editor.evaluate("el => el.setSelectionRange(7, 7)")
    editor.press_sequentially("m.")
    expect(_options(panel)).to_have_count(2)
    editor.press("Enter")
    expect(editor).to_have_value('SELECT m."Sample ID" FROM public."Mixed Case" m')
    editor.press_sequentially(", m.or")
    editor.press("Enter")
    expect(editor).to_have_value('SELECT m."Sample ID", m."order" FROM public."Mixed Case" m')

    # No suggestions inside string literals.
    editor.fill("SELECT * FROM cdm.person WHERE x = 'cd")
    editor.press_sequentially("m")
    expect(listbox).to_have_count(0)
    assert len(requests) == 1  # metadata fetched once per resource


def test_sql_autocomplete_popup_follows_caret_under_zoom(page: Page, app_url: str):
    panel, editor = _open_editor(page, app_url, [])
    page.evaluate("document.getElementById('root').style.zoom = '1.5'")
    editor.fill("SELECT *\n\n\nFROM ")
    editor.evaluate("el => el.setSelectionRange(el.value.length, el.value.length)")
    editor.press_sequentially("cd")
    listbox = panel.get_by_role("listbox", name="SQL suggestions")
    expect(listbox).to_be_visible()
    box = editor.bounding_box()
    popup = listbox.bounding_box()
    line = 12.5 * 1.5 * 1.5  # font-size × line-height × zoom
    # Popup sits just below the fourth line, in zoomed screen pixels.
    expected_top = box["y"] + (1 + 8) * 1.5 + 4 * line
    assert abs(popup["y"] - expected_top) < line, (popup, box)
    assert box["x"] < popup["x"] < box["x"] + box["width"] / 2

    # Scrolling the editor moves the popup with the text.
    editor.fill("SELECT *" + "\n" * 30 + "FROM ")
    editor.evaluate("el => { el.setSelectionRange(el.value.length, el.value.length); el.scrollTop = el.scrollHeight; }")
    editor.press_sequentially("cd")
    expect(listbox).to_be_visible()
    box = editor.bounding_box()
    popup = listbox.bounding_box()
    assert box["y"] < popup["y"] <= box["y"] + box["height"] + 4, (popup, box)
    page.screenshot(path="/private/tmp/cohort-sql-autocomplete.png")
