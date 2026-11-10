import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import ResultsPanel from "./ResultsPanel";

describe("ResultsPanel", () => {
  afterEach(cleanup);

  it("shows its title, the header's right-hand content and its body", () => {
    render(
      <ResultsPanel title="Candidate variants" headerRight={<button type="button">Export TSV</button>}>
        <p>Body</p>
      </ResultsPanel>,
    );

    expect(screen.getByRole("heading", { name: "Candidate variants" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export TSV" })).toBeInTheDocument();
    expect(screen.getByText("Body")).toBeInTheDocument();
  });
});
