import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readPreferences } from "../utils/preferences";
import { loadRecentSearches, recordRecentSearch } from "../utils/recentSearches";
import AppSettingsPage from "./AppSettingsPage";
import DataSourcesPage from "./DataSourcesPage";
import SystemStatusPage from "./SystemStatusPage";
import UsagePage from "./UsagePage";

/** Answers /api/status with the given body, /api/sources with SOURCES and /api/usage with USAGE. */
function mockStatus(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url === "/api/sources"
        ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(SOURCES) })
        : url === "/api/usage"
          ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(USAGE) })
          : Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(body) }),
    ),
  );
}

function mockUsage(usage: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url === "/api/usage"
        ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(usage) })
        : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(SOURCES) }),
    ),
  );
}

const NOW = new Date();
const minutesAgo = (minutes: number) => new Date(NOW.getTime() - minutes * 60_000).toISOString();
const USAGE = {
  queries: 14,
  cacheHits: 5,
  bytesProcessed: 2415919104,
  bytesBilled: 2516582400,
  slotMilliseconds: 48211,
  estimatedCostUsd: 0.0146,
  since: NOW.toISOString(),
  searches: [
    {
      id: 3,
      kind: "condition",
      at: minutesAgo(0.5),
      variants: [],
      phenotypes: [],
      term: "long qt",
      queries: [{ name: "Condition candidates", at: minutesAgo(0.5), cacheHit: false, bytesProcessed: 4096, bytesBilled: 10485760, slotMilliseconds: 20 }],
      cacheHits: 0,
      bytesProcessed: 4096,
      bytesBilled: 10485760,
      estimatedCostUsd: 0.00006,
    },
    {
      id: 2,
      kind: "search",
      at: minutesAgo(1),
      variants: ["14-23424218-G-A", "11-47332274-G-A", "1-156134903-A-G"],
      phenotypes: ["Hypertrophic cardiomyopathy", "Long QT syndrome"],
      term: null,
      queries: [
        { name: "VAT lookup", at: minutesAgo(1), cacheHit: true, bytesProcessed: 26000, bytesBilled: 0, slotMilliseconds: 0 },
        { name: "Resolve concept", at: minutesAgo(1), cacheHit: true, bytesProcessed: 4000, bytesBilled: 0, slotMilliseconds: 0 },
        { name: "Cohort count", at: minutesAgo(1), cacheHit: true, bytesProcessed: 23000, bytesBilled: 0, slotMilliseconds: 0 },
      ],
      cacheHits: 3,
      bytesProcessed: 53000,
      bytesBilled: 0,
      estimatedCostUsd: 0,
    },
    {
      id: 1,
      kind: "search",
      at: minutesAgo(2),
      variants: ["14-23424218-G-A", "11-47332274-G-A", "1-156134903-A-G"],
      phenotypes: [],
      term: null,
      queries: [{ name: "VAT lookup", at: minutesAgo(2), cacheHit: false, bytesProcessed: 26000, bytesBilled: 10485760, slotMilliseconds: 30 }],
      cacheHits: 0,
      bytesProcessed: 26000,
      bytesBilled: 10485760,
      estimatedCostUsd: 0.00006,
    },
  ],
};

const SOURCES = [{ name: "gnomAD", version: "v3.1.2", url: "https://gnomad.broadinstitute.org/" }];

const ACCESSIBLE = {
  accessible: true,
  tables: [
    { table: "proj.vat.v1", accessible: true, detail: null },
    { table: "cdr.C2024.cb_criteria", accessible: true, detail: null },
  ],
};

const renderPage = (page: React.ReactElement) => render(<MemoryRouter>{page}</MemoryRouter>);

/** The usage log's request rows, each with the chevron that opens it, in the order shown. */
const requestRows = () =>
  screen.getAllByRole("button", { name: /queries for request \d+$/ }).map((toggle) => ({ toggle, row: toggle.closest("tr")! }));

describe("DataSourcesPage", () => {
  beforeEach(() => mockStatus(ACCESSIBLE));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("lists the sources, without checking status", async () => {
    renderPage(<DataSourcesPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Sources" })).toBeInTheDocument();
    expect(await screen.findByText("gnomAD")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/sources");
    expect(fetch).not.toHaveBeenCalledWith("/api/status");
  });
});

describe("SystemStatusPage", () => {
  beforeEach(() => mockStatus(ACCESSIBLE));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("lists every checked table", async () => {
    renderPage(<SystemStatusPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Status" })).toBeInTheDocument();
    expect(await screen.findByText("All tables accessible")).toBeInTheDocument();
    expect(screen.getByText("proj.vat.v1")).toBeInTheDocument();
    expect(screen.getByText("cdr.C2024.cb_criteria")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/status");
  });

  it("marks each unavailable table with its reason", async () => {
    mockStatus({
      accessible: false,
      tables: [
        { table: "proj.vat.v1", accessible: true, detail: null },
        { table: "cdr.C2024.concept_ancestor", accessible: false, detail: "Access Denied" },
      ],
    });
    renderPage(<SystemStatusPage />);
    expect(await screen.findByText("1 of 2 tables unavailable")).toBeInTheDocument();
    expect(screen.getByText("Access Denied")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("reports a failed status request", async () => {
    mockStatus({}, false);
    renderPage(<SystemStatusPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("status 500");
  });

  it("refreshes on demand", async () => {
    renderPage(<SystemStatusPage />);
    await screen.findByText("All tables accessible");

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === "/api/status")).toHaveLength(2);
    expect(await screen.findByText("All tables accessible")).toBeInTheDocument();
  });
});

describe("AppSettingsPage", () => {
  beforeEach(() => mockStatus(ACCESSIBLE));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("offers demo mode as a checkbox, off by default, and keeps the choice", () => {
    renderPage(<AppSettingsPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();

    const box = screen.getByRole("checkbox", { name: /Demo mode/ });
    expect(box).not.toBeChecked();
    expect(readPreferences().demoMode).toBe(false);

    fireEvent.click(box);
    expect(box).toBeChecked();
    expect(readPreferences().demoMode).toBe(true);
    // The usage meter's switch is here, off by default and untouched by the other.
    expect(screen.getByRole("checkbox", { name: /Show usage in the top bar/ })).not.toBeChecked();
    expect(readPreferences().showUsageMeter).toBe(false);

    cleanup();
    renderPage(<AppSettingsPage />);
    expect(screen.getByRole("checkbox", { name: /Demo mode/ })).toBeChecked();
  });

  it("says how many recent searches are kept, and clears them", () => {
    renderPage(<AppSettingsPage />);
    expect(screen.getByText("This will remove 0 searches from your history.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear recent searches" })).toBeDisabled();
    cleanup();

    recordRecentSearch({ variants: ["1-1-A-G"], conditions: [] }, 1000);
    recordRecentSearch({ variants: ["2-2-C-T"], conditions: [] }, 2000);
    renderPage(<AppSettingsPage />);
    expect(screen.getByText("This will remove 2 searches from your history.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear recent searches" }));

    expect(screen.getByText("This will remove 0 searches from your history.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear recent searches" })).toBeDisabled();
    expect(loadRecentSearches()).toEqual([]);
  });
});

describe("UsagePage", () => {
  beforeEach(() => mockStatus(ACCESSIBLE));
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  it("shows this session's BigQuery usage as totals and a log of searches, each opening into its queries", async () => {
    renderPage(<UsagePage />);
    expect(screen.getByRole("heading", { level: 1, name: "Usage" })).toBeInTheDocument();

    const totals = await screen.findByRole("group", { name: "This session's totals" });
    expect(within(totals).getAllByRole("term").map((term) => term.textContent)).toEqual(["Billed", "Est. cost", "Queries", "Slot time"]);
    expect(within(totals).getAllByRole("definition").map((cell) => cell.textContent)).toEqual([
      "2.3 GB",
      "$0.01on-demand",
      "145 from cache",
      "48.2 s",
    ]);
    expect(screen.getByText("Recent requests")).toBeInTheDocument();
    expect(screen.getByText(/^Searches and phenotype lookups since \d{1,2}:\d{2} [AP]M, newest first$/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/usage");

    const rows = requestRows();
    expect(rows).toHaveLength(3);
    // Newest first: the phenotype box's lookup, billed like anything else, named by what was typed.
    expect(rows[0].row).toHaveTextContent("Condition lookup “long qt”");
    expect(rows[0].row).toHaveTextContent(/—14 KB10 MB20 ms< \$0\.01billed$/);
    // Then the search, closed; opening it lists its three cached queries, and the repeat is marked as such.
    expect(rows[1].toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("rowgroup", { name: "Queries run by request 2" })).not.toBeInTheDocument();
    fireEvent.click(rows[1].row);
    expect(rows[1].toggle).toHaveAttribute("aria-expanded", "true");
    expect(rows[1].row).toHaveTextContent("14-23424218-G-A, 11-47332274-G-A +1 more");
    expect(rows[1].row).toHaveTextContent("Hypertrophic cardiomyopathyLong QT syndrome");
    expect(rows[1].row).toHaveTextContent(/352 KB0 B0 ms\$0\.00cached$/);
    const jobs = screen.getByRole("rowgroup", { name: "Queries run by request 2" });
    expect(within(jobs).getAllByRole("row").map((row) => row.textContent)).toEqual([
      expect.stringMatching(/VAT lookup25 KB0 B0 mscache$/),
      expect.stringMatching(/Resolve concept4 KB0 B0 mscache$/),
      expect.stringMatching(/Cohort count22 KB0 B0 mscache$/),
    ]);
    // The oldest is closed and billed; opening it, by its chevron, lists its one billed query.
    expect(rows[2].toggle).toHaveAttribute("aria-expanded", "false");
    expect(rows[2].row).toHaveTextContent(/125 KB10 MB30 ms< \$0\.01billed$/);
    expect(screen.queryByRole("rowgroup", { name: "Queries run by request 1" })).not.toBeInTheDocument();
    fireEvent.click(rows[2].toggle);
    expect(within(screen.getByRole("rowgroup", { name: "Queries run by request 1" })).getAllByRole("row")[0]).toHaveTextContent(/VAT lookup25 KB10 MB30 msbilled$/);
    fireEvent.click(rows[1].row);
    expect(screen.queryByRole("rowgroup", { name: "Queries run by request 2" })).not.toBeInTheDocument();
  });

  it("pages through the searches ten at a time, newest first", async () => {
    const searches = Array.from({ length: 13 }, (_, index) => ({
      ...USAGE.searches[2],
      id: 13 - index,
      variants: [`${13 - index}-1-A-G`],
    }));
    mockUsage({ ...USAGE, searches });
    renderPage(<UsagePage />);
    await screen.findByText("1–10 of 13");

    const list = () => requestRows().map(({ row }) => row);
    expect(list()).toHaveLength(10);
    expect(list()[0]).toHaveTextContent("13-1-A-G");
    expect(list()[9]).toHaveTextContent("4-1-A-G");
    expect(screen.getByRole("button", { name: "Newer requests" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Older requests" }));
    expect(screen.getByText("11–13 of 13")).toBeInTheDocument();
    expect(list()).toHaveLength(3);
    expect(list()[0]).toHaveTextContent("3-1-A-G");
    expect(screen.getByRole("button", { name: "Older requests" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Newer requests" }));
    expect(screen.getByText("1–10 of 13")).toBeInTheDocument();
  });

  it("has no pager for ten searches or fewer", async () => {
    renderPage(<UsagePage />);
    await screen.findByText("Recent requests");
    expect(screen.queryByRole("navigation", { name: "Requests, by page" })).not.toBeInTheDocument();
  });

  it("says when no search has run yet", async () => {
    mockUsage({ ...USAGE, queries: 0, searches: [] });
    renderPage(<UsagePage />);
    expect(await screen.findByText("Nothing has queried BigQuery yet this session.")).toBeInTheDocument();
  });
});
