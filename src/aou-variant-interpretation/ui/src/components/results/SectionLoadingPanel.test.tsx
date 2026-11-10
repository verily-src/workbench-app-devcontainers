import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SectionLoadingPanel from "./SectionLoadingPanel";

describe("SectionLoadingPanel", () => {
  it("renders the section title and default loading message", () => {
    render(<SectionLoadingPanel title="Phenotype filter" />);

    expect(screen.getByRole("heading", { name: "Phenotype filter" })).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders a custom loading message", () => {
    render(<SectionLoadingPanel title="Candidate variants" message="Loading variants…" />);

    expect(screen.getByText("Loading variants…")).toBeInTheDocument();
  });

  it("applies the requested content minHeight", () => {
    const { container } = render(<SectionLoadingPanel title="Candidate variants" minHeight={425} />);
    const content = container.querySelector('svg[role="status"]')?.parentElement as HTMLElement;

    expect(content).toHaveStyle({
      minHeight: "425px",
    });
  });

  it("renders the DNA spinner at the placeholder size", () => {
    const { container } = render(<SectionLoadingPanel title="Candidate variants" />);
    const spinner = container.querySelector('svg[role="status"][aria-label="Loading"]') as SVGElement;

    expect(spinner).toHaveAttribute("width", "56");
  });
});
