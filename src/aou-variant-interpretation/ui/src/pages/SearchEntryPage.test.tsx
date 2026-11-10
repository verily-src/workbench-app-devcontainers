import { act, cleanup, configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { updatePreferences } from "../utils/preferences";
import { recordRecentSearch } from "../utils/recentSearches";
import { USE_CASES } from "../utils/useCases";
import SearchEntryPage from "./SearchEntryPage";

const TETRALOGY = { conceptId: 9000010, name: "Tetralogy of Fallot", estimatedParticipantCount: 47 };
const PENTALOGY = { conceptId: 9000013, name: "Pentalogy of Fallot", estimatedParticipantCount: 11 };
const REPAIRED = { conceptId: 9000018, name: "Fallot tetralogy, repaired", estimatedParticipantCount: 8 };

// The condition field debounces its lookup by 1s, the same as findBy*'s default timeout, so
// waiting for its options needs headroom. See ConditionSearchField.test.tsx.
configure({ asyncUtilTimeout: 2500 });

/**
 * Covers the wiring the component tests can't: that Step 2 really is the condition combobox,
 * open from the start, and that a picked condition reaches the results URL.
 */

/** Renders the URL the page navigated to, so the assertions can read it. */
function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<SearchEntryPage />} />
        <Route path="/results" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

/** The top bar's usage meter reads this on mount. */
const USAGE = { queries: 0, cacheHits: 0, bytesProcessed: 0, bytesBilled: 0, slotMilliseconds: 0, estimatedCostUsd: 0, since: new Date().toISOString(), searches: [] };

/** Routes /api/profile, /api/usage and /api/condition, which the page hits for different reasons. */
function stubApi(candidates: unknown[], term: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.startsWith("/api/condition")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ term, candidates }) });
      }
      if (url === "/api/usage") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(USAGE) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ userEmail: "x@example.org" }) });
    }),
  );
}

describe("SearchEntryPage", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("names the app and what it gives you above the form, and each step says its part", () => {
    stubApi([], "");
    renderPage();
    const title = screen.getByRole("heading", { level: 1, name: "All of Us Variant Interpretation" });
    // The Beta chip sits beside the name (the footer has one too).
    expect(title.parentElement).toHaveTextContent(/^All of Us Variant InterpretationBeta$/);
    // The hero positions; the instructions are the steps' own lines.
    expect(screen.getByText(/Enter the variants you're interpreting/)).toBeInTheDocument();
    expect(screen.getByText(/among participants recorded with any of up to three conditions/)).toBeInTheDocument();
  });

  it("shows the phenotype step open from the start, as the condition combobox", () => {
    stubApi([], "");
    renderPage();

    const combobox = screen.getByRole("combobox");
    expect(combobox).toHaveAttribute("placeholder", "e.g. tetralogy of fallot");
    expect(screen.getByText("Optional")).toBeInTheDocument();
    expect(screen.getByText("limit 3")).toBeInTheDocument();
    // Nothing to open: the step is the form.
    expect(screen.queryByRole("button", { name: /Add a phenotype/ })).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("e.g. HP:0001636")).not.toBeInTheDocument();
  });

  it("ends with the footer", () => {
    stubApi([], "");
    renderPage();

    expect(screen.getByRole("contentinfo")).toContainElement(screen.getByRole("img", { name: "Broad Institute" }));
  });

  it("counts the variants entered, ignoring blank lines, and flags going over the limit", () => {
    stubApi([], "");
    renderPage();
    const textarea = screen.getByPlaceholderText(/8-11708582-C-T/);

    expect(screen.getByText("0 entered")).toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: "8-11708582-C-T\n\n  8-11708590-G-GAA  \n" } });
    expect(screen.getByText("2 entered")).toHaveAttribute("title", "Variants entered, one per line.");

    const tooMany = Array.from({ length: 51 }, (_, index) => `1-${index + 1}-A-G`).join("\n");
    fireEvent.change(textarea, { target: { value: tooMany } });
    expect(screen.getByText("51 entered")).toHaveAttribute("title", "Search is limited to 50 variants.");
  });

  it("disables search above the limit, and says how many to remove", () => {
    stubApi([], "");
    renderPage();
    const textarea = screen.getByPlaceholderText(/8-11708582-C-T/);
    const variantLines = (count: number) =>
      Array.from({ length: count }, (_, index) => `1-${index + 1}-A-G`).join("\n");

    fireEvent.change(textarea, { target: { value: variantLines(50) } });
    expect(screen.getByRole("button", { name: /search/i })).toBeEnabled();

    fireEvent.change(textarea, { target: { value: variantLines(53) } });
    expect(screen.getByRole("button", { name: /search/i })).toBeDisabled();
    expect(screen.getByText(/53 variants entered\. Remove 3 to search \(limit 50\)\./)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /search/i }));
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: variantLines(50) } });
    expect(screen.getByRole("button", { name: /search/i })).toBeEnabled();
    expect(screen.queryByText(/Remove \d+ to search/)).not.toBeInTheDocument();
  });

  it("disables search until a variant is entered", () => {
    stubApi([], "");
    renderPage();
    const textarea = screen.getByPlaceholderText(/8-11708582-C-T/);

    expect(screen.getByRole("button", { name: /search/i })).toBeDisabled();

    // Blank lines alone don't count as a variant.
    fireEvent.change(textarea, { target: { value: "\n  \n" } });
    expect(screen.getByRole("button", { name: /search/i })).toBeDisabled();

    fireEvent.change(textarea, { target: { value: "8-11708582-C-T" } });
    expect(screen.getByRole("button", { name: /search/i })).toBeEnabled();
  });

  /**
   * The backend counts exactly the concept that was picked, which is what makes a low- or
   * zero-estimate concept countable. Its name isn't sent: there's no free-text path to use it.
   */
  it("offers 'Try an example' only in demo mode", () => {
    stubApi([], "");
    renderPage();
    expect(screen.queryByRole("button", { name: "Try an example" })).not.toBeInTheDocument();

    act(() => updatePreferences({ demoMode: true }));
    expect(screen.getByRole("button", { name: "Try an example" })).toBeInTheDocument();
  });

  it("fills in a use case's variants and condition from 'Try an example', ready to search", async () => {
    stubApi([], "");
    updatePreferences({ demoMode: true });
    renderPage();
    const hcm = USE_CASES.find((useCase) => useCase.key === "hypertrophic_cardiomyopathy")!;

    fireEvent.click(screen.getByRole("button", { name: "Try an example" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Hypertrophic cardiomyopathy/ }));

    expect(screen.getByPlaceholderText(/8-11708582-C-T/)).toHaveValue(hcm.variants.join("\n"));
    expect(screen.getByText(`${hcm.variants.length} entered`)).toBeInTheDocument();
    // The example's condition is picked, and the field is ready for another.
    expect(screen.getByRole("list", { name: "Picked phenotypes" })).toHaveTextContent("Hypertrophic cardiomyopathy");
    expect(screen.getByRole("combobox")).toHaveAttribute("placeholder", "Add another condition");
    // The menu steps aside once the field has variants in it.
    expect(screen.queryByRole("button", { name: "Try an example" })).not.toBeInTheDocument();

    // Picked, not just typed: the search filters by it.
    fireEvent.click(screen.getByRole("button", { name: /search/i }));
    expect(await screen.findByTestId("location")).toHaveTextContent(
      `/results?${hcm.variants.map((variant) => `variants=${variant}`).join("&")}&conditionConceptIds=9000040`,
    );
  });

  it("opens the example menu into its first item, and closes it on Escape", () => {
    stubApi([], "");
    updatePreferences({ demoMode: true });
    renderPage();
    const trigger = screen.getByRole("button", { name: "Try an example" });

    fireEvent.click(trigger);
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(USE_CASES.length);
    expect(items[0]).toHaveFocus();
    fireEvent.keyDown(items[0], { key: "ArrowDown" });
    expect(items[1]).toHaveFocus();

    fireEvent.keyDown(items[1], { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("says in the footer what's needed to search, and what's ready", () => {
    stubApi([], "");
    renderPage();
    const textarea = screen.getByPlaceholderText(/8-11708582-C-T/);

    expect(screen.getByText("Enter at least one variant to search.")).toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: "8-11708582-C-T" } });
    expect(screen.getByText("1 variant ready")).toBeInTheDocument();

    fireEvent.change(textarea, { target: { value: "8-11708582-C-T\n8-11708590-G-GAA" } });
    expect(screen.getByText("2 variants ready")).toBeInTheDocument();
  });

  it("searches with Ctrl+Enter from the variants field, but plain Enter is a new line", async () => {
    stubApi([], "");
    renderPage();
    const textarea = screen.getByPlaceholderText(/8-11708582-C-T/);
    fireEvent.change(textarea, { target: { value: "8-11708582-C-T" } });

    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();

    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    expect(await screen.findByTestId("location")).toHaveTextContent("/results?variants=8-11708582-C-T");
  });

  it("doesn't search with Ctrl+Enter while there's nothing to search", () => {
    stubApi([], "");
    renderPage();

    fireEvent.keyDown(screen.getByPlaceholderText(/8-11708582-C-T/), { key: "Enter", ctrlKey: true });

    expect(screen.queryByTestId("location")).not.toBeInTheDocument();
  });

  it("searches with Ctrl+Enter from the phenotype field too", async () => {
    stubApi([], "");
    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/8-11708582-C-T/), { target: { value: "8-11708582-C-T" } });

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter", ctrlKey: true });

    expect(await screen.findByTestId("location")).toHaveTextContent("/results?variants=8-11708582-C-T");
  });

  it("lets Ctrl+Enter on a highlighted condition pick it rather than search, then searches with it", async () => {
    stubApi([TETRALOGY], "tetralogy");
    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/8-11708582-C-T/), { target: { value: "8-11708582-C-T" } });
    const combobox = screen.getByRole("combobox");
    fireEvent.focus(combobox);
    fireEvent.change(combobox, { target: { value: "tetralogy" } });
    await screen.findByRole("option", { name: /Tetralogy of Fallot/ });
    fireEvent.keyDown(combobox, { key: "ArrowDown" });

    fireEvent.keyDown(combobox, { key: "Enter", ctrlKey: true });
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Picked phenotypes" })).toHaveTextContent("Tetralogy of Fallot");

    // Nothing highlighted now, so the shortcut from the (emptied) field searches.
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter", ctrlKey: true });
    expect(await screen.findByTestId("location")).toHaveTextContent(
      "/results?variants=8-11708582-C-T&conditionConceptIds=9000010",
    );
  });

  it("offers recent searches once there are some, and picking one fills both steps without running it", async () => {
    stubApi([], "");
    renderPage();
    expect(screen.queryByRole("button", { name: "Recent searches" })).not.toBeInTheDocument();
    cleanup();

    recordRecentSearch({
      variants: ["1-1-A-G", "2-2-C-T"],
      conditions: [{ ...TETRALOGY, hpo: { id: "HP:0001636", name: "Tetralogy of Fallot", match: "exact" } }],
    });
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Recent searches" }));
    const item = screen.getByRole("menuitem", { name: /Tetralogy of Fallot/ });
    expect(item).toHaveTextContent("1-1-A-G, 2-2-C-T");
    expect(item).toHaveTextContent("just now");
    fireEvent.click(item);

    expect(screen.getByRole("textbox", { name: "Candidate variants" })).toHaveValue("1-1-A-G\n2-2-C-T");
    const picked = screen.getByRole("list", { name: "Picked phenotypes" });
    expect(picked).toHaveTextContent("Tetralogy of Fallot");
    expect(picked).toHaveTextContent("~47");
    expect(picked).toHaveTextContent("HP:0001636");
    expect(screen.queryByTestId("location")).not.toBeInTheDocument();
    // The links go while the box has text, like the example link does.
    expect(screen.queryByRole("button", { name: "Recent searches" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));
    expect(await screen.findByTestId("location")).toHaveTextContent(
      "/results?variants=1-1-A-G&variants=2-2-C-T&conditionConceptIds=9000010",
    );
  });

  it("fills a recent search with several conditions as chips, and one without as none", () => {
    stubApi([], "");
    recordRecentSearch({ variants: ["9-9-A-G"], conditions: [] }, Date.now() - 60 * 60 * 1000);
    recordRecentSearch({
      variants: ["1-1-A-G"],
      conditions: [
        { conceptId: 9000010, name: "Tetralogy of Fallot" },
        { conceptId: 9000040, name: "Hypertrophic cardiomyopathy" },
      ],
    });
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Recent searches" }));
    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringMatching(/^Tetralogy of Fallot or Hypertrophic cardiomyopathyjust now1-1-A-G$/),
      expect.stringMatching(/^No phenotype1 hour ago9-9-A-G$/),
    ]);
    fireEvent.click(items[0]);
    const picked = screen.getByRole("list", { name: "Picked phenotypes" });
    expect(picked).toHaveTextContent("Tetralogy of Fallot");
    expect(picked).toHaveTextContent("Hypertrophic cardiomyopathy");

    fireEvent.change(screen.getByRole("textbox", { name: "Candidate variants" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Recent searches" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /No phenotype/ }));
    expect(screen.getByRole("textbox", { name: "Candidate variants" })).toHaveValue("9-9-A-G");
    expect(screen.queryByRole("list", { name: "Picked phenotypes" })).not.toBeInTheDocument();
  });

  it("carries the picked concept's id into the results URL", async () => {
    stubApi([TETRALOGY], "tetralogy");
    renderPage();

    fireEvent.change(screen.getByPlaceholderText(/8-11708582-C-T/), {
      target: { value: "8-11708582-C-T" },
    });
    const combobox = screen.getByRole("combobox");
    fireEvent.focus(combobox);
    fireEvent.change(combobox, { target: { value: "tetralogy" } });
    // Scoped to the option role on purpose, so nothing else on the page saying "Tetralogy of
    // Fallot" is picked up instead.
    fireEvent.mouseDown(await screen.findByRole("option", { name: /Tetralogy of Fallot/ }));
    // The pick becomes a chip, and the field clears for the next one.
    expect(screen.getByRole("list", { name: "Picked phenotypes" })).toHaveTextContent("Tetralogy of Fallot");
    // With the estimate the dropdown showed for it.
    expect(screen.getByRole("list", { name: "Picked phenotypes" })).toHaveTextContent("~47");
    expect(screen.getByRole("combobox")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/results?variants=8-11708582-C-T&conditionConceptIds=9000010",
      ),
    );
    expect(screen.getByTestId("location")).not.toHaveTextContent("condition=");
  });

  it("drops a picked phenotype from the search when its chip is removed, and brings the field back", async () => {
    stubApi([TETRALOGY], "tetralogy");
    renderPage();

    fireEvent.change(screen.getByPlaceholderText(/8-11708582-C-T/), {
      target: { value: "8-11708582-C-T" },
    });
    const combobox = screen.getByRole("combobox");
    fireEvent.focus(combobox);
    fireEvent.change(combobox, { target: { value: "tetralogy" } });
    fireEvent.mouseDown(await screen.findByRole("option", { name: /Tetralogy of Fallot/ }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Tetralogy of Fallot" }));

    expect(screen.queryByRole("list", { name: "Picked phenotypes" })).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/results?variants=8-11708582-C-T"),
    );
    expect(screen.getByTestId("location")).not.toHaveTextContent("conditionConceptId");
  });

  /** Picks a condition from the list, for a field already open; the lookup is stubbed per term. */
  async function pick(name: RegExp, term: string) {
    const combobox = screen.getByRole("combobox");
    fireEvent.focus(combobox);
    fireEvent.change(combobox, { target: { value: term } });
    fireEvent.mouseDown(await screen.findByRole("option", { name }));
  }

  it("takes up to three phenotypes, with 'or' between them, leaving a picked one out of the list", async () => {
    stubApi([TETRALOGY, PENTALOGY, REPAIRED], "fallot");
    renderPage();
    fireEvent.change(screen.getByPlaceholderText(/8-11708582-C-T/), { target: { value: "8-11708582-C-T" } });

    await pick(/Tetralogy of Fallot/, "fallot");
    const picked = screen.getByRole("list", { name: "Picked phenotypes" });
    expect(picked).not.toHaveTextContent(/\bor\b/);
    expect(screen.getByText("Add up to 2 more. A participant recorded with any of these conditions is matched.")).toBeInTheDocument();
    expect(screen.getByText("1 variant ready").parentElement).toHaveTextContent("filtered by Tetralogy of Fallot");

    // The one already picked isn't offered again.
    const combobox = screen.getByRole("combobox");
    fireEvent.focus(combobox);
    fireEvent.change(combobox, { target: { value: "fallot" } });
    await screen.findByRole("option", { name: /Pentalogy of Fallot/ });
    expect(screen.queryByRole("option", { name: /Tetralogy of Fallot/ })).not.toBeInTheDocument();
    fireEvent.mouseDown(screen.getByRole("option", { name: /Pentalogy of Fallot/ }));
    expect(picked).toHaveTextContent(/Tetralogy of Fallot.*or.*Pentalogy of Fallot/);
    expect(screen.getByText("1 variant ready").parentElement).toHaveTextContent(
      "filtered by Tetralogy of Fallot or Pentalogy of Fallot",
    );

    // The third pick fills the search; the field gives way to the limit line until one is removed.
    await pick(/Fallot tetralogy, repaired/, "fallot");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.getByText("You have reached the maximum of 3 phenotypes. Remove one to pick another.")).toBeInTheDocument();
    expect(screen.getByText("1 variant ready").parentElement).toHaveTextContent(
      "filtered by Tetralogy of Fallot, Pentalogy of Fallot or Fallot tetralogy, repaired",
    );
    fireEvent.click(screen.getByRole("button", { name: "Remove Pentalogy of Fallot" }));
    expect(screen.getByRole("combobox")).toBeInTheDocument();

    // In the order picked, one param each.
    fireEvent.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/results?variants=8-11708582-C-T&conditionConceptIds=9000010&conditionConceptIds=9000018",
      ),
    );
  });

  it("ignores typed-but-unpicked text", async () => {
    stubApi([], "");
    renderPage();

    fireEvent.change(screen.getByPlaceholderText(/8-11708582-C-T/), {
      target: { value: "8-11708582-C-T" },
    });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "  diabetes  " } });
    fireEvent.click(screen.getByRole("button", { name: /search/i }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/results?variants=8-11708582-C-T"),
    );
    expect(screen.getByTestId("location")).not.toHaveTextContent("condition");
  });
});
