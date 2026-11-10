import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AnnotatedCohortVariant } from "../../types/results";
import PopulationFrequencyTable from "./PopulationFrequencyTable";

function makeVariant(overrides: Partial<AnnotatedCohortVariant> = {}): AnnotatedCohortVariant {
  return {
    annotated: true,
    variant: "1-12345-A-G",
    gene: "SCN1A",
    consequence: "Missense",
    proteinChange: "p.Arg1Gly",
    aouSubpopulation: "EUR",
    aouAf: 0.02,
    aouAc: 20,
    aouAn: 1000,
    // All of Us reports EUR and MID, but not gnomAD's ASJ, FIN or NFE.
    aouPopulations: [
      { population: "EUR", af: 0.02, ac: 20, an: 1000 },
      { population: "AFR", af: 0.01, ac: 10, an: 1000 },
      { population: "AMR", af: 0.01, ac: 5, an: 500 },
      { population: "EAS", af: 0.01, ac: 5, an: 500 },
      { population: "SAS", af: 0.01, ac: 5, an: 500 },
      { population: "MID", af: 0, ac: 0, an: 500 },
      { population: "OTH", af: 0.01, ac: 5, an: 500 },
    ],
    aouAllAf: 0.012,
    aouAllAc: 30,
    aouAllAn: 2500,
    gnomadSubpopulation: null,
    gnomadAf: null,
    gnomadAc: null,
    gnomadAn: null,
    // gnomAD covers its populations but has no record of this variant.
    gnomadPopulations: [
      { population: "AFR", af: null, ac: null, an: null },
      { population: "NFE", af: null, ac: null, an: null },
    ],
    gnomadAllAf: null,
    gnomadAllAc: null,
    gnomadAllAn: null,
    clinvarSignificance: null,
    clinvarStars: null,
    clinvarHasConflicts: false,
    clinvarConditions: [],
    clinvarLastUpdated: null,
    spliceAi: null,
    plof: null,
    ...overrides,
  } as AnnotatedCohortVariant;
}

describe("PopulationFrequencyTable", () => {
  afterEach(cleanup);

  it("marks a population the source doesn't report as not covered, naming it in the tooltip", () => {
    render(<PopulationFrequencyTable variant={makeVariant()} />);

    const notCovered = screen.getAllByText("Not an inferred ancestry category");
    // ASJ, FIN and NFE for All of Us.
    expect(notCovered).toHaveLength(3);
    expect(notCovered.map((cell) => cell.getAttribute("title"))).toContain(
      "All of Us doesn't report a Finnish population.",
    );
  });

  it("collapses a source with no record of the variant into one not-observed block", () => {
    render(<PopulationFrequencyTable variant={makeVariant()} />);

    const block = screen.getByText("Not observed in gnomAD");
    expect(block).toHaveAttribute("colspan", "2");
    // Every population row plus "All populations".
    expect(block).toHaveAttribute("rowspan", "11");
  });

  it("links the gnomAD header to the variant's gnomAD page only when gnomAD has a record of it", () => {
    const { unmount } = render(<PopulationFrequencyTable variant={makeVariant({ gnomadSubpopulation: "NFE" })} />);
    expect(screen.getByRole("link", { name: "Open 1-12345-A-G in gnomAD (opens in new tab)" })).toHaveAttribute(
      "href",
      "https://gnomad.broadinstitute.org/variant/1-12345-A-G",
    );
    unmount();

    render(<PopulationFrequencyTable variant={makeVariant()} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("keeps a covered population with no carriers as a real zero, explained in its tooltip", () => {
    render(<PopulationFrequencyTable variant={makeVariant()} />);

    expect(screen.getByText("0 / 500")).toHaveAttribute("title", "No carriers among 500 alleles sampled in All of Us.");
  });
});
