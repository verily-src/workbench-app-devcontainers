import { describe, expect, it } from "vitest";
import type { AnnotatedCohortVariant, FilteredVariantRow } from "../types/results";
import {
  ancestryAdjustedExpectation,
  ancestryContext,
  buildComparisonRows,
  largestMatchedAncestry,
  mergeVariantRows,
  sortByEnrichment,
} from "./comparison";

const ANNOTATED: AnnotatedCohortVariant = {
  annotated: true,
  variant: "2-122517541-C-G",
  gene: "LDLR",
  consequence: "Missense",
  proteinChange: "p.Arg123Gly",
  aouSubpopulation: "AFR",
  aouAf: 0.012,
  aouAc: 24,
  aouAn: 2000,
  aouPopulations: [
    { population: "EUR", af: 0.0004, ac: 4, an: 10000 },
    { population: "AFR", af: 0.012, ac: 24, an: 2000 },
  ],
  aouAllAf: 0.0012,
  aouAllAc: 28,
  aouAllAn: 24000,
  gnomadSubpopulation: "AFR",
  gnomadAf: 0.01,
  gnomadAc: 100,
  gnomadAn: 10000,
  gnomadPopulations: [{ population: "AFR", af: 0.01, ac: 100, an: 10000 }],
  gnomadAllAf: 0.002,
  gnomadAllAc: 200,
  gnomadAllAn: 100000,
  clinvarSignificance: "Pathogenic",
  clinvarStars: 2,
  clinvarHasConflicts: false,
  clinvarConditions: [],
  clinvarLastUpdated: null,
  spliceAi: 0.02,
  plof: null,
};

const MATCHED: FilteredVariantRow = {
  variant: "2-122517541-C-G",
  gene: "LDLR",
  consequence: "Missense",
  hasStats: true,
  cohortAc: 6,
  cohortAn: 200,
  cohortAf: 0.03,
  homozygotes: 0,
  heterozygotes: 6,
  clinvarPlpInTrans: 1,
  afRatio: 25,
};

describe("ancestryAdjustedExpectation", () => {
  it("weights each ancestry group's frequency by its matched participants", () => {
    const expected = ancestryAdjustedExpectation(ANNOTATED, [
      { label: "EUR", count: 60, percent: 60, color: "#000" },
      { label: "AFR", count: 40, percent: 40, color: "#000" },
      // No frequency recorded for AMR: contributes nothing.
      { label: "AMR", count: 10, percent: 0, color: "#000" },
    ]);
    // 60·2·0.0004 + 40·2·0.012
    expect(expected).toBeCloseTo(0.048 + 0.96, 6);
    expect(ancestryAdjustedExpectation(ANNOTATED, [])).toBeNull();
  });
});

describe("mergeVariantRows", () => {
  it("joins matched statistics onto each cohort row by variant, keeping the candidate order", () => {
    const unseen = { annotated: false as const, variant: "7-55181378-G-A" };
    const noStats: FilteredVariantRow = { variant: "7-55181378-G-A", gene: null, consequence: null, hasStats: false };
    const rows = mergeVariantRows([unseen, ANNOTATED], [MATCHED, noStats]);

    expect(rows.map((row) => row.variant)).toEqual(["7-55181378-G-A", "2-122517541-C-G"]);
    // A matched row without statistics counts as no match, so callers needn't check hasStats.
    expect(rows[0].matched).toBeNull();
    expect(rows[1].matched).toBe(MATCHED);
    expect(mergeVariantRows([ANNOTATED], [])[0].matched).toBeNull();
  });
});

describe("buildComparisonRows / sortByEnrichment", () => {
  it("sorts a one-participant inconclusive row below a supported signal", () => {
    // Two alleles with none a carrier: inconclusive, with a finite bound and a zero strength
    // (see statistics.test), so it lands in the inconclusive tier, after the supported row.
    const rows = buildComparisonRows(
      [{ ...ANNOTATED, variant: "1-1-A-T", aouAllAc: 5577, aouAllAn: 479860 }, ANNOTATED],
      [{ ...MATCHED, variant: "1-1-A-T", cohortAc: 0, cohortAn: 2, cohortAf: 0, homozygotes: 0, heterozygotes: 0 }, MATCHED],
    );
    expect(sortByEnrichment(rows).map((row) => row.variant)).toEqual(["2-122517541-C-G", "1-1-A-T"]);
  });

  it("ranks an inconclusive fluke below a supported signal, however extreme its ratio", () => {
    const fluke: AnnotatedCohortVariant = { ...ANNOTATED, variant: "7-150974917-G-A", aouAllAc: 3, aouAllAn: 481436 };
    const flukeMatched: FilteredVariantRow = { ...MATCHED, variant: "7-150974917-G-A", cohortAc: 1, cohortAn: 262, cohortAf: 0.0038, afRatio: 600 };
    const rows = buildComparisonRows([fluke, ANNOTATED], [flukeMatched, MATCHED]);
    expect(rows[0].enrichment!.ratio).toBeGreaterThan(100);
    expect(rows[0].enrichment!.verdict).toBe("inconclusive");

    const sorted = sortByEnrichment(rows);
    expect(sorted.map((row) => row.variant)).toEqual(["2-122517541-C-G", "7-150974917-G-A"]);
  });

  it("joins cohort-wide and matched rows by variant, passes the ancestry breakdown through, and orders by support", () => {
    const flat: AnnotatedCohortVariant = { ...ANNOTATED, variant: "1-100-A-T", aouAllAc: 300, aouAllAn: 20000 };
    const flatMatched: FilteredVariantRow = { ...MATCHED, variant: "1-100-A-T", cohortAc: 3, cohortAn: 200, cohortAf: 0.015, afRatio: 1 };
    const rows = buildComparisonRows(
      [flat, ANNOTATED, { annotated: false, variant: "7-1-G-A" }],
      [MATCHED, flatMatched, { variant: "7-1-G-A", gene: null, consequence: null, hasStats: false }],
      [{ label: "AFR", count: 100, percent: 100, color: "#000" }],
    );

    expect(rows.map((row) => row.variant)).toEqual(["1-100-A-T", "2-122517541-C-G", "7-1-G-A"]);
    expect(rows[1].enrichment!.expectedAdjustedAc).toBeCloseTo(100 * 2 * 0.012, 6);
    expect(rows[2].cohort).toBeNull();
    expect(rows[2].matched).toBeNull();
    expect(rows[2].enrichment).toBeNull();

    const sorted = sortByEnrichment(rows);
    expect(sorted.map((row) => row.variant)).toEqual(["2-122517541-C-G", "1-100-A-T", "7-1-G-A"]);
  });
});

describe("ancestryContext", () => {
  it("pairs each All of Us ancestry group's share of the matched cohort with the variant's frequency in it", () => {
    const rows = ancestryContext(ANNOTATED, [
      { label: "EUR", count: 30, percent: 60, color: "#000" },
      { label: "AFR", count: 20, percent: 40, color: "#000" },
    ]);

    expect(rows.map((row) => row.population)).toEqual(["EUR", "AFR", "AMR", "EAS", "SAS", "MID", "OTH"]);
    const afr = rows.find((row) => row.population === "AFR")!;
    expect(afr).toMatchObject({ matchedCount: 20, matchedPercent: 40, aouAf: 0.012, gnomadAf: 0.01, isAouPopmax: true });
    const eur = rows.find((row) => row.population === "EUR")!;
    // gnomAD has no EUR group.
    expect(eur).toMatchObject({ matchedCount: 30, aouAf: 0.0004, gnomadAf: null, isAouPopmax: false });
    expect(rows.find((row) => row.population === "AMR")).toMatchObject({ matchedCount: null, aouAf: null });

    expect(largestMatchedAncestry(rows)?.population).toBe("EUR");
  });
});
