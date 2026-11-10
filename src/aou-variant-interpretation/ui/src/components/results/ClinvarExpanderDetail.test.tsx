import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AnnotatedCohortVariant } from "../../types/results";
import ClinvarExpanderDetail from "./ClinvarExpanderDetail";

function makeVariant(overrides: Partial<AnnotatedCohortVariant> = {}): AnnotatedCohortVariant {
  return {
    annotated: true,
    variant: "1-12345-A-G",
    gene: "SCN1A",
    consequence: "Missense",
    proteinChange: "p.Arg1Gly",
    aouSubpopulation: "EUR",
    aouAf: 0.001,
    aouAc: 1,
    aouAn: 1000,
    aouPopulations: [],
    aouAllAf: 0.001,
    aouAllAc: 1,
    aouAllAn: 1000,
    gnomadSubpopulation: "NFE",
    gnomadAf: 0.002,
    gnomadAc: 2,
    gnomadAn: 1000,
    gnomadPopulations: [],
    gnomadAllAf: 0.002,
    gnomadAllAc: 2,
    gnomadAllAn: 1000,
    clinvarSignificance: "Pathogenic",
    clinvarStars: 2,
    clinvarHasConflicts: false,
    clinvarConditions: ["Condition A", "Condition B", "Condition C"],
    clinvarLastUpdated: "2024-02-14",
    spliceAi: 0.12,
    plof: "HC",
    ...overrides,
  };
}

describe("ClinvarExpanderDetail", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders the empty state when there is no ClinVar record", () => {
    render(<ClinvarExpanderDetail variant={makeVariant({ clinvarSignificance: null, clinvarLastUpdated: null })} />);

    expect(screen.getByText("ClinVar")).toBeInTheDocument();
    expect(screen.getByText("No ClinVar record for this variant.")).toBeInTheDocument();
  });

  it("renders the ClinVar summary, badge, conditions and updated date", () => {
    render(<ClinvarExpanderDetail variant={makeVariant()} />);

    expect(screen.getAllByText("Pathogenic")[0]).toBeInTheDocument();
    expect(screen.getByText("criteria provided, multiple submitters, no conflicts")).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "2 of 4 stars" }).length).toBeGreaterThan(0);
    expect(screen.getByText("Condition A")).toBeInTheDocument();
    expect(screen.getByText("Condition B")).toBeInTheDocument();
    expect(screen.getByText("14 Feb 2024")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in ClinVar ↗" })).toHaveAttribute(
      "href",
      "https://www.ncbi.nlm.nih.gov/clinvar/?term=1-12345-A-G",
    );
    // The badge links to the same place, so the classification itself is clickable.
    expect(screen.getByRole("link", { name: /^ClinVar: Pathogenic/ })).toHaveAttribute(
      "href",
      "https://www.ncbi.nlm.nih.gov/clinvar/?term=1-12345-A-G",
    );
  });

  it("renders the no-consensus fallback when significance is missing", () => {
    render(<ClinvarExpanderDetail variant={makeVariant({ clinvarSignificance: null })} />);

    expect(screen.getByText("No consensus classification")).toBeInTheDocument();
  });

  it("lists conditions one per line, expanding past the first two when the disclosure is clicked", () => {
    render(<ClinvarExpanderDetail variant={makeVariant()} />);
    expect(screen.queryByText("Condition C")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "+1 more" }));

    expect(screen.getByText("Condition C")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+1 more" })).not.toBeInTheDocument();
  });

  it("omits the ClinVar link when there's nothing in ClinVar to open", () => {
    render(<ClinvarExpanderDetail variant={makeVariant({ clinvarSignificance: null, clinvarLastUpdated: null })} />);

    expect(screen.queryByRole("link", { name: "Open in ClinVar ↗" })).not.toBeInTheDocument();
  });
});
