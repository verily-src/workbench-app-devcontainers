import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DataSourcesPanel from "./DataSourcesPanel";

const { fetchDataSourceVersions } = vi.hoisted(() => ({
  fetchDataSourceVersions: vi.fn(),
}));

vi.mock("../../api/dataSourceVersions", () => ({
  fetchDataSourceVersions,
}));

describe("DataSourcesPanel", () => {
  beforeEach(() => {
    fetchDataSourceVersions.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows a loading placeholder before sources load", () => {
    fetchDataSourceVersions.mockReturnValue(new Promise(() => {}));

    const { container } = render(<DataSourcesPanel />);

    expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument();
  });

  it("lists each source with its version and a link to its site", async () => {
    fetchDataSourceVersions.mockResolvedValue([
      { name: "All of Us", version: "v8", description: "The research cohort", url: "https://allofus.nih.gov" },
      { name: "ClinVar", version: "2024-02", description: null, url: "https://www.ncbi.nlm.nih.gov/clinvar/" },
    ]);

    render(<DataSourcesPanel />);

    expect(await screen.findByText("All of Us")).toBeInTheDocument();
    expect(screen.getByText("v8")).toBeInTheDocument();
    expect(screen.getByText("The research cohort")).toBeInTheDocument();
    expect(screen.getByText("2024-02")).toBeInTheDocument();
    expect(screen.getByTitle("Open All of Us")).toHaveAttribute("href", "https://allofus.nih.gov");
    expect(screen.getByTitle("Open ClinVar")).toHaveTextContent("www.ncbi.nlm.nih.gov");
  });

  it("omits the outbound link for sources without a URL", async () => {
    fetchDataSourceVersions.mockResolvedValue([{ name: "gnomAD", version: "3.1.2", description: null, url: null }]);

    render(<DataSourcesPanel />);

    await screen.findByText("gnomAD");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("reports a failed request", async () => {
    fetchDataSourceVersions.mockRejectedValue(new Error("Request failed with status 500"));

    render(<DataSourcesPanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent("status 500");
  });
});
