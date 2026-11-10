import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HeroSources from "./HeroSources";

const SOURCES = [
  { name: "All of Us", version: "CDRv9", url: "https://www.researchallofus.org/" },
  { name: "ClinVar", version: "2025-06-01", url: null },
];

function stubSources(response: { ok: boolean; status?: number; json?: () => Promise<unknown> }) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ status: 500, statusText: "", text: () => Promise.resolve(""), ...response })),
  );
}

describe("HeroSources", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("holds the line with placeholders, then lists each source with its version", async () => {
    stubSources({ ok: true, json: () => Promise.resolve(SOURCES) });
    render(<HeroSources />);
    expect(document.querySelector("[aria-busy='true']")).not.toBeNull();

    const sources = await screen.findByRole("list", { name: "Data sources" });
    const items = sources.querySelectorAll("li");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("All of Us CDRv9");
    expect(items[1]).toHaveTextContent("ClinVar 2025-06-01");
    expect(document.querySelector("[aria-busy='true']")).toBeNull();
    expect(fetch).toHaveBeenCalledWith("/api/sources");
  });

  it("leaves the line empty, without an error, if the sources can't be fetched", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    stubSources({ ok: false, status: 503 });
    render(<HeroSources />);
    await waitFor(() => expect(error).toHaveBeenCalled());
    expect(screen.queryByRole("list", { name: "Data sources" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(document.querySelector("[aria-busy='true']")).toBeNull();
  });
});
