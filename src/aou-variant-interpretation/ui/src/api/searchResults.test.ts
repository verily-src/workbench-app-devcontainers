import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchSearchResults } from "./searchResults";

const EMPTY_RESPONSE = {
  searchSummary: { variantsRaw: "1-1-A-G", variantsEnteredCount: 1, variantsLimit: 50 },
  conditionSearch: null,
  ancestryBreakdown: [],
  ageBreakdown: [],
  cohortVariants: [],
  filteredVariants: [],
};

function stubFetch() {
  const fetchMock = vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(EMPTY_RESPONSE) }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("fetchSearchResults", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends one conditionConceptIds param per concept, in the order given", async () => {
    const fetchMock = stubFetch();

    await fetchSearchResults({ variants: ["1-1-A-G", "2-2-C-T"], conditionConceptIds: [9000040, 9000010] });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/search?variants=1-1-A-G&variants=2-2-C-T&conditionConceptIds=9000040&conditionConceptIds=9000010",
    );
  });

  /** Conditions are OR'd, so the same set in another order is the same search, and one request. */
  it("shares one request between the same concepts in a different order", async () => {
    const fetchMock = stubFetch();

    const first = fetchSearchResults({ variants: ["3-3-G-A"], conditionConceptIds: [9000010, 9000060] });
    const second = fetchSearchResults({ variants: ["3-3-G-A"], conditionConceptIds: [9000060, 9000010] });

    expect(await second).toBe(await first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("is a different search with a different set of concepts", async () => {
    const fetchMock = stubFetch();

    await fetchSearchResults({ variants: ["4-4-A-C"], conditionConceptIds: [9000010] });
    await fetchSearchResults({ variants: ["4-4-A-C"], conditionConceptIds: [9000010, 9000040] });
    await fetchSearchResults({ variants: ["4-4-A-C"] });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock).toHaveBeenLastCalledWith("/api/search?variants=4-4-A-C");
  });
});
