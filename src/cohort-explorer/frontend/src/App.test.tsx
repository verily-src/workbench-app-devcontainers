import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

vi.mock("./api", () => ({
  fetchReady: vi.fn(),
  connectResource: vi.fn(),
  fetchActiveSchema: vi.fn(),
  fetchCounts: vi.fn(),
  fetchFilters: vi.fn(),
  fetchSamples: vi.fn(),
  getCohort: vi.fn(),
  inferSchema: vi.fn(),
  seedData: vi.fn(),
}));
import { connectResource, fetchActiveSchema, fetchCounts, fetchFilters, fetchReady, fetchSamples } from "./api";

// Stand-ins for the screens, so the test checks only what App hands to them.
vi.mock("./components/ResourceSelector", () => ({
  default: (props: { onOmopCohortReady: (id: string, schema: string, folder: string) => Promise<void> }) => (
    <StubSelector onOpen={props.onOmopCohortReady} />
  ),
}));
vi.mock("./components/FilterPanel", () => ({
  default: (props: { mappings: { column: string }[] }) => (
    <div data-testid="filter-panel">{props.mappings.map((m) => m.column).join(",")}</div>
  ),
}));
vi.mock("./components/DataGrid", () => ({ default: () => <div /> }));
vi.mock("./components/SummaryBar", () => ({
  default: (props: { datasource: string }) => <div data-testid="datasource">{props.datasource}</div>,
}));
vi.mock("./components/charts/ChartDashboard", () => ({
  default: (props: { chartConfigs: { fieldKey: string }[] }) => (
    <div data-testid="charts">{props.chartConfigs.map((c) => c.fieldKey).join(",")}</div>
  ),
}));
vi.mock("allotment", () => {
  const Allotment = ({ children }: { children: React.ReactNode }) => <div>{children}</div>;
  Allotment.Pane = ({ children }: { children: React.ReactNode }) => <div>{children}</div>;
  return { Allotment };
});

import { useState } from "react";
function StubSelector({ onOpen }: { onOpen: (id: string, schema: string, folder: string) => Promise<void> }) {
  const [message, setMessage] = useState("");
  return (
    <div>
      <button onClick={() => onOpen("my-db", "omop", "folder-1").catch((e) => setMessage(e.message))}>
        open with folder
      </button>
      <button onClick={() => onOpen("my-db", "cdm", "").catch((e) => setMessage(e.message))}>open without folder</button>
      <div data-testid="selector-message">{message}</div>
    </div>
  );
}

const OMOP_MAPPINGS = [
  { column: "person_id", type: "integer", filter: "none", label: "Person" },
  { column: "gender", type: "text", filter: "categorical", label: "Gender" },
  { column: "year_of_birth", type: "integer", filter: "range", label: "Year of birth" },
];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  vi.mocked(fetchReady).mockResolvedValue({ workspace: true, tables: true });
  vi.mocked(connectResource).mockResolvedValue({ connected: "my-db" });
  vi.mocked(fetchActiveSchema).mockResolvedValue({ mappings: OMOP_MAPPINGS });
  vi.mocked(fetchCounts).mockResolvedValue({ samples: 2 } as never);
  vi.mocked(fetchFilters).mockResolvedValue({} as never);
  vi.mocked(fetchSamples).mockResolvedValue([]);
});

async function clickOpen(name: string) {
  await userEvent.click(await screen.findByRole("button", { name }));
}

describe("App opening an OMOP cohort", () => {
  it("shows the cohort's columns in the filter panel and charts after Open in Explorer", async () => {
    render(<App />);
    await clickOpen("open with folder");

    expect((await screen.findByTestId("filter-panel")).textContent).toBe("person_id,gender,year_of_birth");
    expect(screen.getByTestId("charts").textContent).toBe("gender");
  });

  it("names the data source with the database and the schema", async () => {
    render(<App />);
    await clickOpen("open with folder");

    expect((await screen.findByTestId("datasource")).textContent).toBe("my-db:omop:omop");
  });

  it("loads the counts and rows of the new cohort", async () => {
    render(<App />);
    await clickOpen("open with folder");

    await screen.findByTestId("filter-panel");
    expect(fetchCounts).toHaveBeenCalled();
    expect(fetchSamples).toHaveBeenCalled();
  });

  it("starts the cohort folder when one is chosen", async () => {
    render(<App />);
    await clickOpen("open with folder");

    await screen.findByTestId("filter-panel");
    expect(connectResource).toHaveBeenCalledWith("my-db", "folder-1");
  });

  it("skips the connect call when no cohort folder is chosen", async () => {
    render(<App />);
    await clickOpen("open without folder");

    await screen.findByTestId("filter-panel");
    expect(connectResource).not.toHaveBeenCalled();
  });

  it("saves the connection so a reload restores it", async () => {
    render(<App />);
    await clickOpen("open with folder");
    await screen.findByTestId("filter-panel");

    const saved = JSON.parse(localStorage.getItem("cohort-explorer-state") ?? "{}");
    expect(saved.resourceId).toBe("my-db");
    expect(saved.tableName).toBe("omop:omop");
  });

  it("stays on the selector and shows the message when the cohort cannot be read", async () => {
    vi.mocked(fetchActiveSchema).mockResolvedValue({ mappings: [] });
    render(<App />);
    await clickOpen("open with folder");

    expect((await screen.findByTestId("selector-message")).textContent).toBe(
      "The cohort was not found. Click Find people again.",
    );
    expect(screen.queryByTestId("filter-panel")).toBeNull();
  });
});
