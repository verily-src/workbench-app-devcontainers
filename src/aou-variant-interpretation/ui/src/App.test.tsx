import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App", () => {
  beforeEach(() => {
    // These are sanity checks that each route renders, not that the fetched
    // data displays correctly, so fetch is stubbed to never resolve -- every
    // assertion below only depends on the pre-data UI.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the search entry page at /", () => {
    renderAt("/");
    expect(screen.getByRole("heading", { name: /^All of Us Variant Interpretation$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /search/i })).toBeInTheDocument();
  });

  it("renders the search results page at /results", () => {
    renderAt("/results");
    expect(screen.getAllByRole("heading", { name: "Candidate variants" }).length).toBeGreaterThan(0);
  });
});
