import type { OmopConcept, OmopSpec } from "./api";

// The same two limits are MAX_RULES and MAX_CONCEPT_IDS in app/omop_criteria.py. Change both together.
export const MAX_RULES = 12;
export const MAX_CONCEPT_IDS = 500;

// The domain names are the keys of OMOP_DOMAINS in app/omop_domains.py.
export const DOMAIN_CHOICES = [
  { value: "condition", label: "Condition" },
  { value: "drug", label: "Drug" },
];

// One rule as the user is building it. It keeps the whole concept, not only its ID,
// so the screen can show the name of each picked item.
export interface RuleDraft {
  id: string;
  exclude: boolean;
  domain: string;
  picked: OmopConcept[];
}

let lastRuleNumber = 0;

export function makeEmptyRule(): RuleDraft {
  lastRuleNumber += 1;
  return { id: `rule-${lastRuleNumber}`, exclude: false, domain: DOMAIN_CHOICES[0].value, picked: [] };
}

export function everyRuleHasPickedItem(rules: RuleDraft[]): boolean {
  return rules.every((rule) => rule.picked.length > 0);
}

// Turn the rules on the screen into the spec the backend expects.
export function buildSpec(schema: string, rules: RuleDraft[]): OmopSpec {
  return {
    schema,
    criteria: rules.map((rule) => ({
      domain: rule.domain,
      concept_ids: rule.picked.map((concept) => concept.concept_id),
      exclude: rule.exclude,
    })),
  };
}
