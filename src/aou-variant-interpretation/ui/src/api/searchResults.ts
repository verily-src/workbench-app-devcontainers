import { apiFetch } from "./client";
import type { ConditionSearch } from "./conditions";
import type {
  BreakdownSegment,
  ClinVarSignificance,
  CohortVariantRow,
  FilteredVariantRow,
  GnomadSubpopCode,
  PopulationFrequency,
  SearchSummary,
  SubpopCode,
} from "../types/results";

interface RawCohortVariant {
  variant: string;
  gene: string | null;
  annotated: boolean;
  consequence: string | null;
  proteinChange: string | null;
  aouSubpopulation: SubpopCode | null;
  aouAf: number | null;
  aouAc: number | null;
  aouAn: number | null;
  aouPopulations: PopulationFrequency[];
  aouAllAf: number | null;
  aouAllAc: number | null;
  aouAllAn: number | null;
  gnomadSubpopulation: GnomadSubpopCode | null;
  gnomadAf: number | null;
  gnomadAc: number | null;
  gnomadAn: number | null;
  gnomadPopulations: PopulationFrequency[];
  gnomadAllAf: number | null;
  gnomadAllAc: number | null;
  gnomadAllAn: number | null;
  clinvarSignificance: ClinVarSignificance | null;
  clinvarStars: number | null;
  clinvarHasConflicts: boolean;
  clinvarConditions: string[];
  clinvarLastUpdated: string | null;
  spliceAi: number | null;
  plof: "HC" | "LC" | null;
}

interface RawFilteredVariant {
  variant: string;
  gene: string | null;
  consequence: string | null;
  hasStats: boolean;
  cohortAc: number | null;
  cohortAn: number | null;
  cohortAf: number | null;
  homozygotes: number | null;
  heterozygotes: number | null;
  clinvarPlpInTrans: number | null;
  afRatio: number | null;
}

interface RawSearchResultsResponse {
  searchSummary: SearchSummary;
  // Null when no concept ids were given. Unlike the phenotype fields below, this is backed by
  // real queries.
  conditionSearch: ConditionSearch | null;
  // Mock data: there's no participant-level source behind them yet. They're scaled to the picked
  // conditions' real participant count (the breakdowns sum to it), and empty when it's zero or no
  // condition was found.
  ancestryBreakdown: BreakdownSegment[];
  ageBreakdown: BreakdownSegment[];
  cohortVariants: RawCohortVariant[];
  filteredVariants: RawFilteredVariant[];
}

export interface SearchResults {
  searchSummary: SearchSummary;
  conditionSearch: ConditionSearch | null;
  ancestryBreakdown: BreakdownSegment[];
  ageBreakdown: BreakdownSegment[];
  cohortVariants: CohortVariantRow[];
  filteredVariants: FilteredVariantRow[];
}

function toCohortVariantRow(raw: RawCohortVariant): CohortVariantRow {
  if (!raw.annotated) {
    return { annotated: false, variant: raw.variant };
  }
  return {
    annotated: true,
    variant: raw.variant,
    gene: raw.gene!,
    consequence: raw.consequence!,
    proteinChange: raw.proteinChange!,
    aouSubpopulation: raw.aouSubpopulation,
    aouAf: raw.aouAf,
    aouAc: raw.aouAc,
    aouAn: raw.aouAn,
    aouPopulations: raw.aouPopulations,
    aouAllAf: raw.aouAllAf,
    aouAllAc: raw.aouAllAc,
    aouAllAn: raw.aouAllAn,
    gnomadSubpopulation: raw.gnomadSubpopulation,
    gnomadAf: raw.gnomadAf,
    gnomadAc: raw.gnomadAc,
    gnomadAn: raw.gnomadAn,
    gnomadPopulations: raw.gnomadPopulations,
    gnomadAllAf: raw.gnomadAllAf,
    gnomadAllAc: raw.gnomadAllAc,
    gnomadAllAn: raw.gnomadAllAn,
    clinvarSignificance: raw.clinvarSignificance,
    clinvarStars: raw.clinvarStars,
    clinvarHasConflicts: raw.clinvarHasConflicts,
    clinvarConditions: raw.clinvarConditions,
    clinvarLastUpdated: raw.clinvarLastUpdated,
    spliceAi: raw.spliceAi!,
    plof: raw.plof,
  };
}

function toFilteredVariantRow(raw: RawFilteredVariant): FilteredVariantRow {
  if (!raw.hasStats) {
    return { hasStats: false, variant: raw.variant, gene: raw.gene, consequence: raw.consequence };
  }
  return {
    hasStats: true,
    variant: raw.variant,
    gene: raw.gene,
    consequence: raw.consequence,
    cohortAc: raw.cohortAc!,
    cohortAn: raw.cohortAn!,
    cohortAf: raw.cohortAf!,
    homozygotes: raw.homozygotes!,
    heterozygotes: raw.heterozygotes!,
    clinvarPlpInTrans: raw.clinvarPlpInTrans!,
    afRatio: raw.afRatio!,
  };
}

export interface SearchResultsQuery {
  variants: string[];
  /**
   * The concepts the user picked from the dropdown; a participant is matched by any of them.
   * There's no free-text alternative: typed text that was never picked doesn't filter anything.
   */
  conditionConceptIds?: number[];
}

// Keyed by the request URL, which fully encodes every search criterion -- except that the concept
// ids are sorted in the key, since the same set in another order is the same search. Caching the
// in-flight promise -- not just the resolved result -- means two calls for the same query made
// back-to-back (e.g. React StrictMode's double-invoked mount effect in dev) share one network
// request instead of firing the BigQuery query twice. Successful results stay cached for the rest
// of the session; failures are evicted so a retry actually retries.
const cache = new Map<string, Promise<SearchResults>>();

function searchUrl(query: SearchResultsQuery | undefined, conceptIds: number[]): string {
  const params = new URLSearchParams();
  for (const variant of query?.variants ?? []) {
    params.append("variants", variant);
  }
  for (const conceptId of conceptIds) {
    params.append("conditionConceptIds", String(conceptId));
  }
  const queryString = params.toString();
  return queryString ? `/search?${queryString}` : "/search";
}

// With no variants (or an empty list), the backend returns an empty cohortVariants -- there's
// no default browse listing.
export async function fetchSearchResults(query?: SearchResultsQuery): Promise<SearchResults> {
  const conceptIds = query?.conditionConceptIds ?? [];
  const key = searchUrl(query, [...conceptIds].sort((a, b) => a - b));

  const cached = cache.get(key);
  if (cached) {
    return cached;
  }

  // Sent in the order given, so the response (and the chips it fills) keep the user's order.
  const request = fetchAndParse(searchUrl(query, conceptIds));
  request.catch(() => cache.delete(key));
  cache.set(key, request);
  return request;
}

async function fetchAndParse(path: string): Promise<SearchResults> {
  const raw = await apiFetch<RawSearchResultsResponse>(path);
  return {
    searchSummary: raw.searchSummary,
    conditionSearch: raw.conditionSearch,
    ancestryBreakdown: raw.ancestryBreakdown,
    ageBreakdown: raw.ageBreakdown,
    cohortVariants: raw.cohortVariants.map(toCohortVariantRow),
    filteredVariants: raw.filteredVariants.map(toFilteredVariantRow),
  };
}
