import pytest
from playwright.sync_api import expect

from tests.test_e2e import app_url

pytestmark = pytest.mark.e2e


def test_database_filter_ask_history_folds_and_survives_tab_switch(page, app_url):
    tables = [
        {"name": "public.person", "schema": "public", "table": "person", "detail": "table"},
        {"name": "public.visit", "schema": "public", "table": "visit", "detail": "table"},
    ]

    def fulfill(route, body):
        route.fulfill(status=200, content_type="application/json", json=body)

    page.route("**/api/datasources", lambda route: fulfill(route, {
        "ready": True,
        "sources": [{"kind": "aurora", "id": "clinical", "label": "Clinical"}],
        "catalogs_pending": False,
    }))
    page.route("**/api/workflows**", lambda route: fulfill(route, {
        "available": False, "jobs": [], "running_count": 0,
    }))
    saved_views = []
    saved_state = {}
    saved_payloads = []

    def list_views(route):
        fulfill(route, {"views": saved_views, "unavailable": []})

    def save_view(route):
        body = route.request.post_data_json
        saved_payloads.append(body)
        saved_state.update({"version": 2, "active": body["active"],
                            "datasets": body["datasets"]})
        saved_views[:] = [{"kind": body["kind"], "resource_id": body["resource_id"],
                           "name": body["name"], "materialized_sources": 0,
                           "refreshed_at": None, "store_label": "Clinical"}]
        fulfill(route, {"name": body["name"]})

    page.route("**/api/views/all", list_views)
    page.route("**/api/views", save_view)
    page.route("**/api/views/one?**", lambda route: fulfill(route, saved_state))
    page.route("**/api/tables?**", lambda route: fulfill(route, tables))
    opened = []

    def open_dataset(route):
        source = route.request.post_data_json.get("source_ref",
                                                   route.request.post_data_json)
        opened.append(source)
        dataset_id = "db-person" if source["table"] == "person" else "db-visit"
        fulfill(route, {"dataset_id": dataset_id, "source": source["table"],
                        "source_ref": source, "rows": 2, "query_scope": "database",
                        "columns": [{"name": "person_id", "dtype": "int64",
                                     "filter_kind": "none"}]})

    page.route("**/api/datasets/open", open_dataset)
    page.route("**/api/datasets/*/query", lambda route: fulfill(route, {
        "total": 2, "filtered": 2, "scope": "database", "sampled": False,
        "charts": [], "rows": {"page": 0, "page_size": 50,
                                  "columns": ["person_id"], "data": [[1], [2]]},
    }))
    ask_calls = []

    def ask(route):
        ask_calls.append(route.request.post_data_json["question"])
        answer = f"Applied filter for question {len(ask_calls)}"
        fulfill(route, {"filters": [], "explanation": answer})

    page.route("**/api/datasets/*/ask", ask)
    page.goto(app_url)
    page.get_by_label("Source type").select_option("aurora")
    page.get_by_label("Datasource").select_option("aurora:clinical")
    page.get_by_label("Schema").select_option("public")
    expect(page.get_by_label("Table").locator("option")).to_have_count(3)
    page.get_by_label("Table").select_option("public.person")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tab.active")).to_contain_text("person")

    question = page.get_by_placeholder('Ask AI to filter — e.g. "liver samples with RIN above 7"')
    question.fill("Only people with condition A")
    page.get_by_role("button", name="Ask", exact=True).click()
    expect(page.get_by_text("Applied filter for question 1")).to_be_visible()

    history_toggle = page.locator(".filter-ask-history button")
    expect(history_toggle).to_contain_text("Question history (1)")
    expect(history_toggle).to_have_attribute("aria-expanded", "true")
    history_toggle.click()
    expect(page.get_by_role("log", name="Question history")).to_have_count(0)
    question.fill("Only people with condition B")
    page.get_by_role("button", name="Ask", exact=True).click()
    expect(page.get_by_text("Applied filter for question 2")).to_be_visible()
    expect(page.get_by_text("Only people with condition A")).to_be_visible()

    page.get_by_label("Table").select_option("public.visit")
    page.get_by_role("button", name="Load table").click()
    expect(page.locator(".tabs > span")).to_have_count(2)
    page.locator(".tabs > span").first.click()
    expect(page.get_by_text("Applied filter for question 1")).to_be_visible()
    expect(page.get_by_text("Applied filter for question 2")).to_be_visible()
    expect(page.locator(".filter-ask-history button")).to_contain_text(
        "Question history (2)")
    expect(page.locator(".filter-ask-history button")).to_have_attribute("aria-expanded", "true")
    page.get_by_label("Saved view name").fill("Ask history")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("button", name="Ask history", exact=True)).to_be_visible()
    assert saved_payloads[0]["datasets"][0]["filter_ask_history"] == [
        {"question": "Only people with condition A", "answer": "Applied filter for question 1"},
        {"question": "Only people with condition B", "answer": "Applied filter for question 2"},
    ]
    page.get_by_role("button", name="Ask history", exact=True).click()
    expect(page.get_by_text("Applied filter for question 1")).to_be_visible()
    expect(page.get_by_text("Applied filter for question 2")).to_be_visible()
    assert saved_state["datasets"][0]["filter_ask_history"] == saved_payloads[0]["datasets"][0]["filter_ask_history"]
    assert opened == [
        {"kind": "aurora", "resource_id": "clinical", "schema": "public", "table": "person"},
        {"kind": "aurora", "resource_id": "clinical", "schema": "public", "table": "visit"},
    ]
    assert ask_calls == ["Only people with condition A", "Only people with condition B"]
