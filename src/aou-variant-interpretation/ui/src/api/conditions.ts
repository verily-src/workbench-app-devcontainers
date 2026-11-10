import { apiFetch } from "./client";

/**
 * The Human Phenotype Ontology term the backend pairs with a condition concept, for display. A
 * lexical pairing on the concept's name, not a curated mapping: "exact" when the name is the
 * term's name or an exact synonym, "approximate" when the term is a broader phrase the name
 * contains ("Hypercholesterolemia" for "Familial hypercholesterolemia").
 */
export interface HpoTerm {
  id: string;
  name: string;
  match: "exact" | "approximate";
}

/** A condition concept matching a free-text term, as offered in the phenotype dropdown. */
export interface ConditionConcept {
  conceptId: number;
  name: string;
  /** The HPO term paired with this concept; null when none did. Absent from fixtures that predate it. */
  hpo?: HpoTerm | null;
  /**
   * cb_criteria.est_count -- an estimate All of Us maintains, and what the ranking is based on.
   * Not the same number as the participant count /api/search returns for the same concept, and
   * null when the underlying column is null or non-numeric.
   */
  estimatedParticipantCount: number | null;
}

export interface ConditionCandidates {
  /** The term as the backend trimmed it, echoed back. See fetchConditionCandidates. */
  term: string;
  candidates: ConditionConcept[];
}

/** A concept a search resolved, with its own real participant count beside the estimate. */
export interface MatchedConcept extends ConditionConcept {
  /**
   * Distinct participants recorded with this concept or any descendant of it. With several
   * concepts these overlap, so they don't sum to the search's participantCount.
   */
  participantCount: number;
}

/** Participants recorded with exactly this set of the search's concepts (or a descendant of each). */
export interface ConditionOverlapCell {
  /** The concepts, in request order; one for participants with only that concept. */
  conceptIds: number[];
  count: number;
}

/**
 * The condition half of a /api/search response. Null there when no concept was picked.
 *
 * A participant is matched by *any* of the picked concepts (or a descendant of any), not all of
 * them. Note the two kinds of count are different things and will not agree: a concept's
 * `estimatedParticipantCount` is All of Us's estimate for that concept alone, while the
 * participant counts are real counts over the concept *and all its descendants*.
 */
export interface ConditionSearch {
  /** Every concept ID that was requested, in request order. */
  conceptIds: number[];
  /**
   * The requested concepts that are standard condition concepts in this CDR, in request order.
   * Empty when none is.
   */
  concepts: MatchedConcept[];
  /** Participants with any of the resolved concepts, each counted once. Null when concepts is empty. */
  participantCount: number | null;
  /**
   * How the matched participants divide among the concepts: disjoint cells that sum to
   * participantCount. A real count from the same query, unlike the ancestry and age breakdowns.
   * Empty when concepts is.
   */
  conditionOverlap: ConditionOverlapCell[];
}

/**
 * Looks up condition concepts matching free text.
 *
 * This is the cheap half of the condition pipeline: one query against cb_criteria, with no
 * descendant expansion and no participant count, which is why a type-ahead can call it per
 * keystroke. Use fetchSearchResults with `conditionConceptIds` for the count.
 *
 * Deliberately not cached, unlike fetchSearchResults: every keystroke is a distinct term, so a
 * cache would grow one entry per prefix and almost never hit.
 */
export function fetchConditionCandidates(term: string, signal?: AbortSignal): Promise<ConditionCandidates> {
  const params = new URLSearchParams({ condition: term });
  return apiFetch<ConditionCandidates>(`/condition?${params.toString()}`, { signal });
}
