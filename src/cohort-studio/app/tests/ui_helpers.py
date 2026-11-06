"""Shared browser-test helpers."""


def menu(page, name):
    """Open the header menu called `name` (idempotent) and return the page.

    Tabs keep rarely used actions in menus: "Export options" (downloads,
    PLINK 2, PDF, Save to Aurora) and "Add to this view" (calculated field,
    aggregation filter, group summary)."""
    button = page.get_by_role("button", name=name, exact=True).first
    if button.get_attribute("aria-expanded") != "true":
        button.click()
    return page
