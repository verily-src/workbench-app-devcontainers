import type { ConditionConcept } from "../api/conditions";

/**
 * How many phenotypes one search can filter by. Bounded by what the chip row, the top bar's
 * badge and the matched-header tooltip can show, not by the backend, which takes any number.
 * A participant is matched by any of them (see api/conditions.ts).
 */
export const PHENOTYPES_LIMIT = 3;

/** What a search filters by: the picked phenotypes' concept ids, in the order they were picked. */
export function searchConceptIds(phenotypes: ConditionConcept[]): number[] {
  return phenotypes.map((phenotype) => phenotype.conceptId);
}

/** The picked phenotypes named in one line, for a status message: "Tetralogy of Fallot, Long QT". */
export function describePhenotypes(phenotypes: ConditionConcept[]): string {
  return phenotypes.map((phenotype) => phenotype.name).join(", ");
}

/**
 * Names joined as alternatives, the way the search treats them: "A", "A or B", "A, B or C". For
 * the sentences that say who the matched participants are.
 */
export function describeAlternatives(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`;
}
