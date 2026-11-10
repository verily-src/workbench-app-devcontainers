import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import SearchResultsPage from "./SearchResultsPage";

/**
 * Covers the page's wiring for several conditions: every id in the URL reaches the request, the
 * resolved concepts name the search everywhere, and an edit re-runs with the list that's left.
 */

/** The top bar's usage meter reads this once results have loaded. */
const USAGE = { queries: 0, cacheHits: 0, bytesProcessed: 0, bytesBilled: 0, slotMilliseconds: 0, estimatedCostUsd: 0, since: new Date().toISOString(), searches: [] };

const TETRALOGY = { conceptId: 9000010, name: "Tetralogy of Fallot", estimatedParticipantCount: 47, participantCount: 49 };
const HCM = { conceptId: 9000040, name: "Hypertrophic cardiomyopathy", estimatedParticipantCount: 212, participantCount: 214 };

function response(variants: string[], concepts: typeof TETRALOGY[]) {
  const participantCount = concepts.length ? 260 : null;
  // Three participants have both when both are picked; alone, each concept's cell is its own count.
  const conditionOverlap =
    concepts.length === 2
      ? [
          { conceptIds: [9000010], count: 46 },
          { conceptIds: [9000040], count: 211 },
          { conceptIds: [9000010, 9000040], count: 3 },
        ]
      : concepts.map((c) => ({ conceptIds: [c.conceptId], count: c.participantCount }));
  return {
    searchSummary: { variantsRaw: variants.join("\n"), variantsEnteredCount: variants.length, variantsLimit: 50 },
    conditionSearch: concepts.length
      ? { conceptIds: concepts.map((c) => c.conceptId), concepts, participantCount, conditionOverlap }
      : null,
    ancestryBreakdown: concepts.length ? [{ label: "EUR", count: 260, percent: 100, color: "#F9C854" }] : [],
    ageBreakdown: concepts.length ? [{ label: "40–49", count: 260, percent: 100, color: "#5FAEDA" }] : [],
    cohortVariants: variants.map((variant) => ({ variant, annotated: false })),
    filteredVariants: concepts.length ? variants.map((variant) => ({ variant, gene: null, consequence: null, hasStats: false })) : [],
  };
}

/** Routes /api/search by the ids in its URL, and /api/profile. */
function stubApi() {
  const searches: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      if (url.startsWith("/api/search")) {
        searches.push(url);
        const params = new URL(url, "http://localhost").searchParams;
        const ids = params.getAll("conditionConceptIds").map(Number);
        const concepts = [TETRALOGY, HCM].filter((c) => ids.includes(c.conceptId));
        return Promise.resolve({ ok: true, json: () => Promise.resolve(response(params.getAll("variants"), concepts)) });
      }
      if (url === "/api/usage") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(USAGE) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ userEmail: "x@example.org" }) });
    }),
  );
  return searches;
}

function renderPage(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/results?${search}`]}>
      <Routes>
        <Route path="/results" element={<SearchResultsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SearchResultsPage", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("sends every condition in the URL, and names them all once loaded", async () => {
    const searches = stubApi();
    renderPage("variants=1-1-A-G&conditionConceptIds=9000010&conditionConceptIds=9000040");

    // The top bar's badge: too long to show whole, so the first and how many more, the rest in its tooltip.
    expect(await screen.findByText("Tetralogy of Fallot +1 more")).toHaveAttribute(
      "title",
      "Tetralogy of Fallot or Hypertrophic cardiomyopathy",
    );
    expect(searches).toEqual(["/api/search?variants=1-1-A-G&conditionConceptIds=9000010&conditionConceptIds=9000040"]);
    // The strip lists both, each with its own count beside it.
    expect(screen.getAllByText("260").length).toBeGreaterThan(0);
    // (Each "no matching term" chip also carries its hidden explanation, so the match is loose.)
    expect(screen.getByRole("list", { name: /Conditions, any of/ })).toHaveTextContent(
      /^Tetralogy of FallotHPOno matching term.*49Hypertrophic cardiomyopathyHPOno matching term.*214$/,
    );
    // And the search goes into history with both.
    expect(JSON.parse(window.localStorage.getItem("via.recentSearches.v2")!)[0]).toMatchObject({
      variants: ["1-1-A-G"],
      conditions: [
        { conceptId: 9000010, name: "Tetralogy of Fallot" },
        { conceptId: 9000040, name: "Hypertrophic cardiomyopathy" },
      ],
    });
  });

  it("re-runs with the conditions left after an edit", async () => {
    const searches = stubApi();
    // Different variants from the test above: fetchSearchResults caches by criteria across tests.
    renderPage("variants=2-2-C-T&conditionConceptIds=9000010&conditionConceptIds=9000040");
    await screen.findByText("Tetralogy of Fallot +1 more");

    fireEvent.click(screen.getByRole("button", { name: "Edit search" }));
    const editor = screen.getByRole("dialog", { name: "Edit search" });
    expect(editor).toHaveTextContent(/Tetralogy of Fallot.*or.*Hypertrophic cardiomyopathy/);
    fireEvent.click(screen.getByRole("button", { name: "Remove Tetralogy of Fallot" }));
    const searchButtons = screen.getAllByRole("button", { name: /^search$/i });
    fireEvent.click(searchButtons[searchButtons.length - 1]);

    await waitFor(() => expect(searches).toHaveLength(2));
    expect(searches[1]).toBe("/api/search?variants=2-2-C-T&conditionConceptIds=9000040");
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit search" })).toHaveAccessibleDescription(/Phenotype\s*Hypertrophic cardiomyopathy$/));
    expect(screen.queryByRole("list", { name: /Conditions, any of/ })).not.toBeInTheDocument();
  });
});
