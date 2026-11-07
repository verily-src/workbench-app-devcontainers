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


def open_data_builder(page, start_tab=None):
    """Open Data Builder; with start_tab, put that open Explore tab on the canvas first."""
    from playwright.sync_api import expect
    page.locator(".topnav-link").filter(has_text="Data Builder").click()
    canvas = page.locator(".jc")
    expect(canvas).to_be_visible()
    if start_tab:
        add_to_canvas(canvas, start_tab, tab=True)
    return canvas


def pick_table(page, datasource, table, timeout=15000):
    """Data Builder → Connections: choose `datasource` ("kind:id"), then click `table`
    (its listed name, e.g. "public.person" or "clinical/person.parquet").
    Returns the "Selected table" card (details, Live/Extract, Open in Explore)."""
    from playwright.sync_api import expect
    canvas = open_data_builder(page)
    source = canvas.locator(f'[data-source-key="{datasource}"]')
    expect(source).to_be_visible(timeout=timeout)
    if source.get_attribute("aria-pressed") != "true":
        source.click()
    row = canvas.locator(f'li.jc-table-item[data-table="{table}"] .jc-table-pick')
    expect(row).to_be_visible(timeout=timeout)
    row.click()
    card = canvas.get_by_role("region", name="Selected table")
    expect(card).to_be_visible()
    return card


def load_table(page, datasource, table, extract=None, timeout=15000):
    """Open one table in Explore from Data Builder (Live, or Extract with
    extract=(database, table_name)) and wait for its tab."""
    from playwright.sync_api import expect
    card = pick_table(page, datasource, table, timeout)
    if extract:
        card.get_by_role("radio", name="Extract").check()
        database, name = extract
        card.get_by_label("Save extract to").select_option(database)
        card.get_by_label("Extract table").fill(name)
    card.get_by_role("button", name="Open in Explore").click()
    expect(page.locator(".join-canvas-host")).to_be_hidden(timeout=timeout)
    return page


def add_to_canvas(canvas, name, tab=False):
    """Press + for an open tab ("Open tabs") or a datasource table."""
    scope = canvas.get_by_role("group", name="Open tabs") if tab else canvas
    scope.get_by_role("button", name=f"Add {name} to canvas", exact=True).click()


def set_join_keys(canvas, left, right, how=None, clause=1):
    """Fill the open Join configuration and apply it."""
    from playwright.sync_api import expect
    config = canvas.get_by_role("region", name="Join configuration")
    expect(config).to_be_visible(timeout=10000)
    if how:
        radio = config.get_by_role("radio", name=how, exact=True)
        if not radio.is_visible():   # Has match / No match sit under "More"
            config.get_by_text("More", exact=True).click()
        radio.click()
    for label, value in ((f"Left field, clause {clause}", left), (f"Right field, clause {clause}", right)):
        box = config.get_by_role("combobox", name=label)
        box.fill(value)
        box.press("Enter")
    config.get_by_role("button", name="Apply").click()
    return config


def canvas_join(page, tabs, keys, how=None, consent=False, title=None):
    """Join open Explore tabs in Data Builder and open the result.

    tabs[0] is the start table (its "⋈ Join"); each later tab is joined to it
    with the matching (left, right) pair in `keys`."""
    from playwright.sync_api import expect
    canvas = open_data_builder(page, tabs[0])
    expect(canvas.locator(".jc-node")).to_have_count(1, timeout=10000)
    for count, (tab, (left, right)) in enumerate(zip(tabs[1:], keys), start=2):
        add_to_canvas(canvas, tab, tab=True)
        expect(canvas.locator(".jc-node")).to_have_count(count, timeout=10000)
        set_join_keys(canvas, left, right, how)
    if title:
        canvas.get_by_role("textbox", name="Join name").fill(title)
    if consent:
        canvas.locator(".jc-consent input[type=checkbox]").check()
    run = canvas.get_by_role("button", name="Save & open in Explore")
    expect(run).to_be_enabled(timeout=10000)
    run.click()
    return canvas
