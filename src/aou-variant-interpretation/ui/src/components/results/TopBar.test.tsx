import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { updatePreferences } from "../../utils/preferences";
import { recordRecentSearch } from "../../utils/recentSearches";
import TopBar, { USAGE_REFRESH_MS } from "./TopBar";

/** The meter is opt-in; these tests turn it on. */
const showMeter = () => updatePreferences({ showUsageMeter: true });

/** What /api/usage answers: 2.25 GiB scanned ("2.3 GB"), 2.5 GiB billed ("2.5 GB"). */
const USAGE = {
  queries: 14,
  cacheHits: 5,
  bytesProcessed: 2415919104,
  bytesBilled: 2684354560,
  slotMilliseconds: 48211,
  estimatedCostUsd: 0.0146,
  since: new Date().toISOString(),
  searches: [],
};

function renderTopBar(props: Parameters<typeof TopBar>[0]) {
  return render(
    <MemoryRouter>
      <TopBar {...props} />
    </MemoryRouter>,
  );
}

describe("TopBar", () => {
  afterEach(() => {
    cleanup();
    window.localStorage.clear();
  });

  it("renders the user email even without search controls", () => {
    renderTopBar({ userEmail: "user@example.org" });

    expect(screen.getByText("user@example.org")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "VIA home, new search" })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("button", { name: "Edit search" })).not.toBeInTheDocument();
  });

  it("renders the loaded search summary when modify controls are enabled", () => {
    renderTopBar({
      userEmail: "user@example.org",
      variantsEnteredCount: 17,
      phenotypes: ["Seizure"],
      onModifySearch: vi.fn(),
    });

    expect(screen.getByRole("link", { name: "VIA home, new search" })).toBeInTheDocument();
    expect(screen.getByText("Variants")).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();
    expect(screen.getByText("Seizure")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit search" })).toBeEnabled();
  });

  it("opens the drawer from anywhere in the search box, which describes the current terms", () => {
    const onModifySearch = vi.fn();
    const { rerender } = renderTopBar({
      userEmail: "user@example.org",
      variantsEnteredCount: 17,
      phenotypes: ["Seizure"],
      onModifySearch,
    });
    const searchBox = screen.getByRole("button", { name: "Edit search" });

    expect(searchBox).toHaveAccessibleDescription(/Variants\s*17.*Phenotype\s*Seizure/);
    expect(searchBox).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(screen.getByText("Seizure"));
    expect(onModifySearch).toHaveBeenCalledTimes(1);

    rerender(
      <MemoryRouter>
        <TopBar
          userEmail="user@example.org"
          variantsEnteredCount={17}
          phenotypes={["Seizure"]}
          onModifySearch={onModifySearch}
          modifyOpen
        />
      </MemoryRouter>,
    );
    expect(searchBox).toHaveAttribute("aria-expanded", "true");
  });

  it("returns focus to the search box when the drawer closes", () => {
    const props = { userEmail: "user@example.org", variantsEnteredCount: 3, phenotypes: [], onModifySearch: vi.fn() };
    const { rerender } = renderTopBar({ ...props, modifyOpen: true });
    const searchBox = screen.getByRole("button", { name: "Edit search" });
    expect(searchBox).not.toHaveFocus();

    rerender(
      <MemoryRouter>
        <TopBar {...props} modifyOpen={false} />
      </MemoryRouter>,
    );

    expect(searchBox).toHaveFocus();
  });

  it("doesn't take focus on first render with the drawer closed", () => {
    renderTopBar({ userEmail: "user@example.org", variantsEnteredCount: 3, phenotypes: [], onModifySearch: vi.fn() });

    expect(screen.getByRole("button", { name: "Edit search" })).not.toHaveFocus();
  });

  /**
   * Regression guard. The box's border was once the `border` shorthand with a `borderColor`
   * override for hover and open, and ending either state left it with no colour at all -- so it
   * fell back to the text colour, a near-black outline.
   */
  it("goes back to its grey border after a hover or the drawer closing", () => {
    const props = { userEmail: "user@example.org", variantsEnteredCount: 3, phenotypes: [], onModifySearch: vi.fn() };
    const { rerender } = renderTopBar({ ...props, modifyOpen: true });
    const searchBox = screen.getByRole("button", { name: "Edit search" });
    const grey = "rgb(199, 198, 192)";

    rerender(
      <MemoryRouter>
        <TopBar {...props} modifyOpen={false} />
      </MemoryRouter>,
    );
    expect(searchBox.style.borderColor).toBe(grey);

    fireEvent.mouseEnter(searchBox);
    expect(searchBox.style.borderColor).not.toBe(grey);
    fireEvent.mouseLeave(searchBox);
    expect(searchBox.style.borderColor).toBe(grey);
  });

  /**
   * Regression guard. The edit-search popover's backdrop is fixed to the window and starts at
   * the bar's height. When the bar scrolled with the page, that left an undimmed strip at the
   * top of the window, over the results, once the page was scrolled.
   */
  it("stays pinned to the top of the window", () => {
    const { container } = renderTopBar({ userEmail: "user@example.org" });

    expect(container.firstChild).toHaveStyle({ position: "sticky", top: "0px" });
  });

  it("names two conditions as alternatives, and a long list by its first and how many more", () => {
    renderTopBar({ userEmail: "user@example.org", variantsEnteredCount: 2, phenotypes: ["Seizure", "Ataxia"], onModifySearch: vi.fn() });
    expect(screen.getByText("Seizure or Ataxia")).toHaveAttribute("title", "Seizure or Ataxia");
    cleanup();

    const long = ["Hypertrophic cardiomyopathy", "Long QT syndrome", "Familial hypercholesterolemia"];
    renderTopBar({ userEmail: "user@example.org", variantsEnteredCount: 2, phenotypes: long, onModifySearch: vi.fn() });
    expect(screen.getByText("Hypertrophic cardiomyopathy +2 more")).toHaveAttribute(
      "title",
      "Hypertrophic cardiomyopathy, Long QT syndrome or Familial hypercholesterolemia",
    );
  });

  it("renders the fallback phenotype label when no condition is set", () => {
    renderTopBar({
      userEmail: "user@example.org",
      variantsEnteredCount: 4,
      phenotypes: [],
      onModifySearch: vi.fn(),
    });

    expect(screen.getByText("None entered")).toBeInTheDocument();
  });

  it("renders loading skeletons and disables modify while loading", () => {
    renderTopBar({
      userEmail: "user@example.org",
      loading: true,
      onModifySearch: vi.fn(),
    });

    expect(screen.queryByText("None entered")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".animate-skeleton-pulse")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Edit search" })).toBeDisabled();
  });

  it("links home from the VIA mark, in place of the old back arrow", () => {
    renderTopBar({
      userEmail: "user@example.org",
      variantsEnteredCount: 9,
      phenotypes: ["Ataxia"],
      onModifySearch: vi.fn(),
    });

    const brand = screen.getByRole("link", { name: "VIA home, new search" });
    expect(brand).toHaveAttribute("href", "/");
    expect(brand).toHaveTextContent("VIA");
    expect(screen.queryByRole("button", { name: "Back to search" })).not.toBeInTheDocument();
  });

  it("calls onModifySearch when the search box is pressed", () => {
    const onModifySearch = vi.fn();
    renderTopBar({
      userEmail: "user@example.org",
      variantsEnteredCount: 9,
      phenotypes: ["Ataxia"],
      onModifySearch,
    });

    fireEvent.click(screen.getByRole("button", { name: "Edit search" }));

    expect(onModifySearch).toHaveBeenCalledTimes(1);
  });

  /** Answers the settings panels' requests and the bar's own usage read. */
  function stubBackend(usage: unknown = USAGE) {
    const json = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url === "/api/usage"
          ? json(usage)
          : url === "/api/status"
            ? json({ accessible: true, tables: [] })
            : json([{ name: "gnomAD", version: "v3.1.2", url: null }]),
      ),
    );
  }

  it("opens the sidebar from the hamburger, listing the search and each workspace page", () => {
    stubBackend();
    renderTopBar({ userEmail: "user@example.org" });

    const button = screen.getByRole("button", { name: "Menu" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog", { name: "Menu" })).not.toBeInTheDocument();

    fireEvent.click(button);
    const drawer = screen.getByRole("dialog", { name: "Menu" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(drawer).toHaveFocus();
    const nav = within(drawer).getByRole("navigation", { name: "Menu" });
    expect(within(nav).getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["New search", "/"],
      ["Sources", "/data-sources"],
      ["Status", "/system-status"],
      ["Usage", "/usage"],
      ["Settings", "/settings"],
    ]);
    expect(within(nav).getByText("Workspace")).toBeInTheDocument();
    expect(within(nav).queryByText("Recent")).not.toBeInTheDocument();
    // The page being shown is marked; the bar renders at "/" here.
    expect(within(nav).getByRole("link", { name: "New search" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Usage" })).not.toHaveAttribute("aria-current");
    // Who is signed in, and the version, at the bottom.
    // Who is signed in stays in the top bar; the drawer's last line is the footer's.
    expect(within(drawer).queryByText("user@example.org")).not.toBeInTheDocument();
    expect(within(drawer).getByTitle("VIA version")).toBeInTheDocument();

    // Escape closes it and hands focus back to the hamburger.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Menu" })).not.toBeInTheDocument();
    expect(button).toHaveFocus();

    // So do the close button, the scrim, and following a link.
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));
    expect(screen.queryByRole("dialog", { name: "Menu" })).not.toBeInTheDocument();
    fireEvent.click(button);
    fireEvent.click(screen.getByTestId("appDrawerScrim"));
    expect(screen.queryByRole("dialog", { name: "Menu" })).not.toBeInTheDocument();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole("dialog", { name: "Menu" })).getByRole("link", { name: "Usage" }));
    expect(screen.queryByRole("dialog", { name: "Menu" })).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("lists the last few searches in the sidebar, each linking to its results", () => {
    stubBackend();
    recordRecentSearch({ variants: ["8-11708582-C-T", "8-11708590-G-GAA", "8-11708598-T-C"], conditions: [{ conceptId: 4208906, name: "Tetralogy of Fallot" }] });
    recordRecentSearch({ variants: ["14-23412740-C-T"], conditions: [] });
    renderTopBar({ userEmail: "user@example.org" });

    fireEvent.click(screen.getByRole("button", { name: "Menu" }));
    const recent = within(screen.getByRole("list", { name: "Recent searches" })).getAllByRole("link");
    expect(recent).toHaveLength(2);
    // Newest first, variants summarised, then the phenotype and when.
    expect(recent[0]).toHaveTextContent("14-23412740-C-T");
    expect(recent[0]).toHaveTextContent("No phenotype · just now");
    expect(recent[0]).toHaveAttribute("href", "/results?variants=14-23412740-C-T");
    expect(recent[1]).toHaveTextContent("8-11708582-C-T, 8-11708590-G-GAA +1");
    expect(recent[1]).toHaveTextContent("Tetralogy of Fallot · just now");
    expect(recent[1]).toHaveAttribute("href", "/results?variants=8-11708582-C-T&variants=8-11708590-G-GAA&variants=8-11708598-T-C&conditionConceptIds=4208906");
    expect(recent[1]).toHaveAccessibleName("Run again: 3 variants, Tetralogy of Fallot · just now");
    vi.unstubAllGlobals();
  });

  it("keeps the meter off the bar by default, without reading usage", async () => {
    stubBackend();
    renderTopBar({ userEmail: "user@example.org" });

    expect(screen.queryByRole("link", { name: /BigQuery usage/ })).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith("/api/usage");

    // Switched on from the Usage page, it appears without a reload.
    act(() => updatePreferences({ showUsageMeter: true }));
    expect(await screen.findByRole("link", { name: /BigQuery usage this session: 2.3 GB scanned/ })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("shows the session's bytes scanned, and links the meter to the Usage page", async () => {
    showMeter();
    stubBackend();
    renderTopBar({ userEmail: "user@example.org" });

    const meter = await screen.findByRole("link", {
      name: "BigQuery usage this session: 2.3 GB scanned, 2.5 GB billed, $0.01 estimated. Open usage details",
    });
    expect(meter).toHaveTextContent("2.3 GB·2.5 GB·$0.01");
    expect(meter).toHaveAttribute("title", "BigQuery this session: 2.3 GB scanned · 2.5 GB billed · $0.01 estimated");
    expect(meter).toHaveAttribute("href", "/usage");
    vi.unstubAllGlobals();
  });

  it("leaves the meter off the bar when usage can't be read", async () => {
    showMeter();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve({ ok: false, status: 503, statusText: "Service Unavailable", text: () => Promise.resolve("") })),
    );
    renderTopBar({ userEmail: "user@example.org" });

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/usage"));
    expect(screen.queryByRole("link", { name: /BigQuery usage/ })).not.toBeInTheDocument();
    expect(screen.getByText("user@example.org")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  it("takes the meter down when a later read fails", async () => {
    showMeter();
    let down = false;
    const json = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url === "/api/usage" && down
          ? Promise.resolve({ ok: false, status: 503, statusText: "Service Unavailable", text: () => Promise.resolve("") })
          : json(url === "/api/usage" ? USAGE : []),
      ),
    );
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      renderTopBar({ userEmail: "user@example.org" });
      expect(await screen.findByText("2.3 GB")).toBeInTheDocument();

      down = true;
      act(() => vi.advanceTimersByTime(USAGE_REFRESH_MS));
      await waitFor(() => expect(screen.queryByRole("link", { name: /BigQuery usage/ })).not.toBeInTheDocument());

      // Back up on the next tick.
      down = false;
      act(() => vi.advanceTimersByTime(USAGE_REFRESH_MS));
      expect(await screen.findByText("2.3 GB")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
    vi.unstubAllGlobals();
  });

  it("re-reads usage every minute while shown, and stops when switched off", async () => {
    showMeter();
    let bytes = USAGE.bytesProcessed;
    const json = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => (url === "/api/usage" ? json({ ...USAGE, bytesProcessed: bytes }) : json([]))),
    );
    // Only the interval is faked, so fetch's promises and findBy's polling still run for real.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    try {
      renderTopBar({ userEmail: "user@example.org" });
      expect(await screen.findByText("2.3 GB")).toBeInTheDocument();
      expect(fetch).toHaveBeenCalledTimes(1);

      // Another 2.25 GiB scanned since the first read; the meter catches up on its next tick.
      bytes *= 2;
      act(() => vi.advanceTimersByTime(USAGE_REFRESH_MS - 1));
      expect(fetch).toHaveBeenCalledTimes(1);
      act(() => vi.advanceTimersByTime(1));
      expect(fetch).toHaveBeenCalledTimes(2);
      expect(await screen.findByText("4.5 GB")).toBeInTheDocument();

      // Off again: the meter goes, and so do the reads.
      act(() => updatePreferences({ showUsageMeter: false }));
      expect(screen.queryByRole("link", { name: /BigQuery usage/ })).not.toBeInTheDocument();
      act(() => vi.advanceTimersByTime(USAGE_REFRESH_MS * 3));
      expect(fetch).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
    vi.unstubAllGlobals();
  });

  it("re-reads usage once a search has loaded", async () => {
    showMeter();
    stubBackend();
    const { rerender } = renderTopBar({ userEmail: "user@example.org", loading: true, onModifySearch: vi.fn() });

    expect(fetch).not.toHaveBeenCalledWith("/api/usage");
    rerender(
      <MemoryRouter>
        <TopBar userEmail="user@example.org" loading={false} variantsEnteredCount={1} onModifySearch={vi.fn()} />
      </MemoryRouter>,
    );

    expect(await screen.findByText("2.3 GB")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });

  describe("at narrow width", () => {
    const matchMedia = window.matchMedia;
    beforeEach(() => {
      window.matchMedia = ((query: string) => ({ ...matchMedia(query), matches: true })) as typeof window.matchMedia;
    });
    afterEach(() => {
      window.matchMedia = matchMedia;
    });

    const props = { userEmail: "user@example.org", onModifySearch: vi.fn() };

    it("shows only the estimated cost in the usage meter, with the rest in its tooltip", async () => {
      showMeter();
      stubBackend();
      renderTopBar(props);

      const meter = await screen.findByRole("link", { name: /BigQuery usage this session/ });
      expect(meter).toHaveTextContent("$0.01");
      expect(meter).not.toHaveTextContent("GB");
      expect(meter).toHaveAttribute("title", expect.stringContaining("2.3 GB scanned"));
      vi.unstubAllGlobals();
    });

    it("moves the email into the user icon's tooltip, still readable by screen readers", () => {
      const { container } = renderTopBar({ ...props, variantsEnteredCount: 3, phenotypes: [] });

      expect(container.querySelector('[title="user@example.org"]')).toBeInTheDocument();
      expect(screen.getByText("user@example.org").style.position).toBe("absolute");
    });

    it("shows a variant count without its label, and drops an empty phenotype", () => {
      renderTopBar({ ...props, variantsEnteredCount: 1, phenotypes: [] });
      const searchBox = screen.getByRole("button", { name: "Edit search" });

      expect(screen.getByText("1 variant")).toBeInTheDocument();
      expect(screen.getByText("Variants").style.position).toBe("absolute");
      expect(searchBox).toHaveAccessibleDescription(/Phenotype\s*None entered/);
      expect(screen.queryByText("Edit")).not.toBeInTheDocument();
    });

    it("keeps a picked phenotype, pluralizing the count", () => {
      renderTopBar({ ...props, variantsEnteredCount: 2, phenotypes: ["Tetralogy of Fallot"] });

      expect(screen.getByText("2 variants")).toBeInTheDocument();
      expect(screen.getByText("Tetralogy of Fallot")).toHaveAttribute("title", "Tetralogy of Fallot");
    });
  });
});
