import { afterEach, describe, expect, it, vi } from "vitest";
import { clearRecentSearches, describeSearchedAt, loadRecentSearches, recordRecentSearch } from "./recentSearches";

const TETRALOGY = { conceptId: 9000010, name: "Tetralogy of Fallot" };
const HCM = { conceptId: 9000040, name: "Hypertrophic cardiomyopathy" };

describe("recent searches", () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("starts empty", () => {
    expect(loadRecentSearches()).toEqual([]);
  });

  it("keeps searches newest first", () => {
    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [] }, 1000);
    recordRecentSearch({ variants: ["2-2-C-T"], conditions: [TETRALOGY] }, 2000);

    expect(loadRecentSearches()).toEqual([
      { variants: ["2-2-C-T"], conditions: [TETRALOGY], searchedAt: 2000 },
      { variants: ["1-1-A-G"], conditions: [], searchedAt: 1000 },
    ]);
  });

  it("moves a re-run of the same criteria to the top instead of repeating it", () => {
    recordRecentSearch({ variants: ["1-1-A-G", "2-2-C-T"], conditions: [TETRALOGY] }, 1000);
    recordRecentSearch({ variants: ["3-3-G-A"], conditions: [] }, 2000);
    recordRecentSearch({ variants: ["2-2-C-T", "1-1-A-G"], conditions: [TETRALOGY] }, 3000);

    const searches = loadRecentSearches();
    expect(searches).toHaveLength(2);
    expect(searches[0]).toMatchObject({ variants: ["2-2-C-T", "1-1-A-G"], searchedAt: 3000 });
  });

  it("treats a different condition as a different search", () => {
    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [TETRALOGY] }, 1000);
    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [] }, 2000);
    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [TETRALOGY, HCM] }, 3000);

    expect(loadRecentSearches()).toHaveLength(3);
  });

  /** Conditions are OR'd, so the same set in another order is the same search. */
  it("treats the same conditions in another order as the same search", () => {
    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [TETRALOGY, HCM] }, 1000);
    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [HCM, TETRALOGY] }, 2000);

    const searches = loadRecentSearches();
    expect(searches).toHaveLength(1);
    expect(searches[0]).toMatchObject({ conditions: [HCM, TETRALOGY], searchedAt: 2000 });
  });

  /** The v1 shape held one `condition`; it's under its own key, so it's simply no longer read. */
  it("ignores history in the old one-condition shape", () => {
    window.localStorage.setItem(
      "via.recentSearches.v1",
      JSON.stringify([{ variants: ["1-1-A-G"], condition: TETRALOGY, searchedAt: 5 }]),
    );
    expect(loadRecentSearches()).toEqual([]);

    window.localStorage.setItem(
      "via.recentSearches.v2",
      JSON.stringify([
        { variants: ["1-1-A-G"], condition: TETRALOGY, searchedAt: 5 },
        { variants: ["2-2-C-T"], conditions: [{ conceptId: "x", name: "y" }], searchedAt: 6 },
        { variants: ["3-3-G-A"], conditions: [TETRALOGY, HCM], searchedAt: 7 },
      ]),
    );
    expect(loadRecentSearches()).toEqual([{ variants: ["3-3-G-A"], conditions: [TETRALOGY, HCM], searchedAt: 7 }]);
  });

  it("keeps only the twenty most recent", () => {
    for (let i = 1; i <= 23; i++) {
      recordRecentSearch({ variants: [`${i}-1-A-G`], conditions: [] }, i);
    }

    const kept = loadRecentSearches().map((search) => search.variants[0]);
    expect(kept).toHaveLength(20);
    expect(kept[0]).toBe("23-1-A-G");
    expect(kept[19]).toBe("4-1-A-G");
  });

  /** What a chip shows comes back with the condition; history from before it was kept still loads. */
  it("keeps a condition's estimate and HPO term when it has them", () => {
    const hpo = { id: "HP:0001636", name: "Tetralogy of Fallot", match: "exact" as const };
    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [{ ...TETRALOGY, estimatedParticipantCount: 47, hpo }] }, 1000);
    recordRecentSearch({ variants: ["2-2-C-T"], conditions: [{ ...HCM, estimatedParticipantCount: null, hpo: null }] }, 2000);

    expect(loadRecentSearches()).toEqual([
      { variants: ["2-2-C-T"], conditions: [{ ...HCM, estimatedParticipantCount: null, hpo: null }], searchedAt: 2000 },
      { variants: ["1-1-A-G"], conditions: [{ ...TETRALOGY, estimatedParticipantCount: 47, hpo }], searchedAt: 1000 },
    ]);

    window.localStorage.setItem(
      "via.recentSearches.v2",
      JSON.stringify([{ variants: ["3-3-G-A"], conditions: [{ ...TETRALOGY, estimatedParticipantCount: "many" }], searchedAt: 7 }]),
    );
    expect(loadRecentSearches()).toEqual([]);
  });

  it("ignores a search with no variants", () => {
    recordRecentSearch({ variants: [], conditions: [] });

    expect(loadRecentSearches()).toEqual([]);
  });

  it("clears", () => {
    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [] });
    clearRecentSearches();

    expect(loadRecentSearches()).toEqual([]);
  });

  it("drops unreadable or malformed data instead of failing", () => {
    window.localStorage.setItem("via.recentSearches.v2", "not json");
    expect(loadRecentSearches()).toEqual([]);

    window.localStorage.setItem(
      "via.recentSearches.v2",
      JSON.stringify([{ variants: "oops" }, { variants: ["1-1-A-G"], conditions: [], searchedAt: 5 }]),
    );
    expect(loadRecentSearches()).toEqual([{ variants: ["1-1-A-G"], conditions: [], searchedAt: 5 }]);
  });

  it("treats blocked storage as no history", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });

    expect(() => recordRecentSearch({ variants: ["1-1-A-G"], conditions: [] })).not.toThrow();
    expect(loadRecentSearches()).toEqual([]);
  });
});

describe("describeSearchedAt", () => {
  const now = Date.UTC(2026, 8, 27, 12);

  it("describes how long ago, in the largest unit that fits", () => {
    expect(describeSearchedAt(now - 20 * 1000, now)).toBe("just now");
    expect(describeSearchedAt(now - 5 * 60 * 1000, now)).toBe("5 minutes ago");
    expect(describeSearchedAt(now - 2 * 60 * 60 * 1000, now)).toBe("2 hours ago");
    expect(describeSearchedAt(now - 24 * 60 * 60 * 1000, now)).toBe("yesterday");
    expect(describeSearchedAt(now - 15 * 24 * 60 * 60 * 1000, now)).toBe("2 weeks ago");
  });
});
