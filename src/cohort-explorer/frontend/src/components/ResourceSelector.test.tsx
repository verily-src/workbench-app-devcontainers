import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ResourceSelector from "./ResourceSelector";

vi.mock("../api", () => ({
  fetchDatasources: vi.fn(),
  searchOmopConcepts: vi.fn(),
  createOmopCohort: vi.fn(),
  listS3Files: vi.fn(),
  refreshDatasources: vi.fn(),
  connectResource: vi.fn(),
}));
import { createOmopCohort, fetchDatasources } from "../api";

const AURORA = {
  id: "my-db",
  name: "OMOP demo",
  database: "omop_demo",
  rw_endpoint: null,
  resource_type: "AURORA",
  tables: [],
};

beforeEach(() => {
  vi.mocked(fetchDatasources).mockResolvedValue({
    resources: [AURORA],
    s3_folders: [],
    active: "my-db",
    has_local: false,
    ready: true,
  });
});

describe("ResourceSelector OMOP cohort builder", () => {
  it("offers the OMOP cohort builder next to Single table and Join tables", async () => {
    render(<ResourceSelector onConnected={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "Single table" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Join tables" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "OMOP cohort builder" })).toBeTruthy();
  });

  it("shows the cohort panel and hides Connect after choosing the OMOP cohort builder", async () => {
    render(<ResourceSelector onConnected={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "OMOP cohort builder" }));

    expect(screen.getByText("Build a cohort by condition and drug")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
  });

  it("does not show the cohort panel for a single table", async () => {
    render(<ResourceSelector onConnected={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "Connect" })).toBeTruthy();
    expect(screen.queryByText("Build a cohort by condition and drug")).toBeNull();
  });

  it("sends the chosen database to the cohort request", async () => {
    vi.mocked(createOmopCohort).mockResolvedValue({ count: 2 });
    const { searchOmopConcepts } = await import("../api");
    vi.mocked(searchOmopConcepts).mockResolvedValue([
      { concept_id: 201826, name: "Type 2 diabetes mellitus", vocabulary: "SNOMED", persons: 3 },
    ]);
    render(<ResourceSelector onConnected={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: "OMOP cohort builder" }));
    await userEvent.click(screen.getByLabelText("Search by name"));
    await userEvent.click(await screen.findByText("Type 2 diabetes mellitus"));

    await userEvent.click(screen.getByRole("button", { name: /find people/i }));

    expect(vi.mocked(createOmopCohort).mock.calls[0][0]).toBe("my-db");
  });
});
