import type { ConditionConcept } from "../api/conditions";
import useCases from "../data/useCases.json";

/**
 * A curated demo search: real variants and a condition, with synthetic data written so every
 * panel of the results looks right for it. Generated from data/synthetic/generators/use_cases/ by
 * generate_use_case_fixtures.py -- edit the use cases there, not the JSON.
 */
export interface UseCase {
  key: string;
  title: string;
  description: string;
  variants: string[];
  condition: ConditionConcept;
}

export const USE_CASES: UseCase[] = useCases;
