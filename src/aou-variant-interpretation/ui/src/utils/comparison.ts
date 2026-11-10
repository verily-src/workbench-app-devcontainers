// The rows the table and Review work from: each candidate variant's cohort-wide record from the
// VAT joined with its statistics among the phenotype-matched participants, the comparison between
// the two worked out (see statistics.ts), and the matched cohort's ancestry makeup laid against it.
//
// Everything here is pure and takes the rows the results page already has; nothing is fetched.

import type {
  AnnotatedCohortVariant,
  BreakdownSegment,
  CohortVariantRow,
  FilteredVariantRow,
  FilteredVariantWithStats,
  GnomadSubpopCode,
  SubpopCode,
} from "../types/results";
import { computeEnrichment, type Enrichment } from "./statistics";
import { AOU_SUBPOP_CODES } from "./subpopulations";

/**
 * One candidate variant with both sides of the comparison: its cohort-wide record from the VAT and,
 * when a phenotype filter matched anyone, its statistics among the matched participants. The
 * table and Review both start from these.
 */
export interface MergedVariantRow {
  variant: string;
  cohort: CohortVariantRow;
  /** Null when the search had no phenotype, or the matched participants have no statistics for it. */
  matched: FilteredVariantWithStats | null;
}

/** Joins the cohort-wide and matched rows by variant, keeping the candidate list's order. */
export function mergeVariantRows(
  cohortVariants: CohortVariantRow[],
  filteredVariants: FilteredVariantRow[],
): MergedVariantRow[] {
  const matchedByVariant = new Map(filteredVariants.map((row) => [row.variant, row]));
  return cohortVariants.map((cohort) => {
    const filtered = matchedByVariant.get(cohort.variant);
    return { variant: cohort.variant, cohort, matched: filtered?.hasStats ? filtered : null };
  });
}

/** A merged row as Review reads it: annotated or nothing, and the comparison worked out. */
export interface ComparisonRow {
  variant: string;
  cohort: AnnotatedCohortVariant | null;
  matched: FilteredVariantWithStats | null;
  /** Null when either side lacks counts. */
  enrichment: Enrichment | null;
}

/** The merged rows with each one's enrichment computed, keeping the candidate list's order. */
export function buildComparisonRows(
  cohortVariants: CohortVariantRow[],
  filteredVariants: FilteredVariantRow[],
  ancestryBreakdown: BreakdownSegment[] = [],
): ComparisonRow[] {
  return mergeVariantRows(cohortVariants, filteredVariants).map(({ variant, cohort: row, matched }) => {
    const cohort = row.annotated ? row : null;
    const enrichment =
      cohort && matched && cohort.aouAllAc !== null && cohort.aouAllAn !== null
        ? computeEnrichment(matched.cohortAc, matched.cohortAn, cohort.aouAllAc, cohort.aouAllAn, {
            expectedAdjustedAc: ancestryAdjustedExpectation(cohort, ancestryBreakdown),
          })
        : null;
    return { variant, cohort, matched, enrichment };
  });
}

/**
 * Most informative first: verdicts the interval supports, by how far it clears 1; then similar;
 * then inconclusive; then rows with nothing to compare. Within a tier, the larger the gap between
 * observed and expected alleles the higher, so a single-allele fluke never outranks a real signal.
 */
export function sortByEnrichment(rows: ComparisonRow[]): ComparisonRow[] {
  return [...rows].sort((a, b) => {
    const tierDiff = tier(a.enrichment) - tier(b.enrichment);
    if (tierDiff !== 0 || !a.enrichment || !b.enrichment) return tierDiff;
    if (b.enrichment.strength !== a.enrichment.strength) return b.enrichment.strength - a.enrichment.strength;
    return excess(b.enrichment) - excess(a.enrichment);
  });
}

function tier(e: Enrichment | null): number {
  if (!e) return 3;
  if (e.verdict === "inconclusive") return 2;
  if (e.verdict === "similar") return 1;
  return 0;
}

function excess(e: Enrichment): number {
  return Math.abs(e.matchedAc - e.expectedMatchedAc);
}

/**
 * How many matched alternate alleles the cohort-wide per-ancestry frequencies predict, given the
 * matched cohort's ancestry makeup: Σ over groups of (matched participants × 2 alleles × the
 * variant's All of Us frequency in that group). A group the variant isn't observed in
 * contributes nothing. Null when the breakdown is empty.
 */
export function ancestryAdjustedExpectation(
  cohort: AnnotatedCohortVariant,
  ancestryBreakdown: BreakdownSegment[],
): number | null {
  if (ancestryBreakdown.length === 0) return null;
  const afByPopulation = new Map(cohort.aouPopulations.map((p) => [p.population, p.af ?? 0]));
  let expected = 0;
  for (const segment of ancestryBreakdown) {
    expected += segment.count * 2 * (afByPopulation.get(segment.label as SubpopCode) ?? 0);
  }
  return expected;
}

export interface AncestryContextRow {
  population: SubpopCode;
  /** The matched cohort's participants of this ancestry, and their share of it; null when the breakdown lacks the group. */
  matchedCount: number | null;
  matchedPercent: number | null;
  /** Cohort-wide All of Us frequency in this population; null when not observed. */
  aouAf: number | null;
  aouAc: number | null;
  aouAn: number | null;
  /** gnomAD's frequency for the same code where its vocabulary has one (EUR and MID have no counterpart). */
  gnomadAf: number | null;
  isAouPopmax: boolean;
}

/**
 * One row per All of Us ancestry group: how much of the matched cohort it makes up, beside the
 * variant's frequency within it cohort-wide. That pairing is what tells a counselor whether a
 * cohort-wide figure is representative of the people actually matched.
 */
export function ancestryContext(
  cohort: AnnotatedCohortVariant | null,
  ancestryBreakdown: BreakdownSegment[],
): AncestryContextRow[] {
  const breakdown = new Map(ancestryBreakdown.map((segment) => [segment.label, segment]));
  const aou = new Map(cohort?.aouPopulations.map((p) => [p.population, p]) ?? []);
  const gnomad = new Map(cohort?.gnomadPopulations.map((p) => [p.population, p]) ?? []);
  return AOU_SUBPOP_CODES.map((population) => {
    const segment = breakdown.get(population);
    const aouPop = aou.get(population);
    const gnomadPop = gnomad.get(population as GnomadSubpopCode);
    return {
      population,
      matchedCount: segment?.count ?? null,
      matchedPercent: segment?.percent ?? null,
      aouAf: aouPop?.af ?? null,
      aouAc: aouPop?.ac ?? null,
      aouAn: aouPop?.an ?? null,
      gnomadAf: gnomadPop?.af ?? null,
      isAouPopmax: cohort?.aouSubpopulation === population,
    };
  });
}

/** The ancestry group that makes up the largest share of the matched cohort, if the breakdown names one. */
export function largestMatchedAncestry(rows: AncestryContextRow[]): AncestryContextRow | null {
  let best: AncestryContextRow | null = null;
  for (const row of rows) {
    if (row.matchedCount !== null && (best === null || row.matchedCount > (best.matchedCount ?? 0))) best = row;
  }
  return best;
}
