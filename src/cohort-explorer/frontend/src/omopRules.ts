import type { OmopConcept, OmopSpec } from "./api";

// The same two limits are MAX_RULES and MAX_CONCEPT_IDS in app/omop_criteria.py. Change both together.
export const MAX_RULES = 12;
export const MAX_CONCEPT_IDS = 500;

// The domain names are the keys of OMOP_DOMAINS in app/omop_domains.py.
export const DOMAIN_CHOICES = [
  { value: "condition", label: "Condition" },
  { value: "drug", label: "Drug" },
  { value: "observation", label: "Observation" },
  { value: "procedure", label: "Procedure" },
  { value: "measurement", label: "Measurement" },
];

// A rule on one of these matches any recorded row for the item. The value is not checked.
export const DOMAINS_THAT_IGNORE_VALUES = ["observation", "measurement"];

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

// One rule in plain words, for the Explorer screen. For example the heading "Has Condition"
// and the names of the items. It holds only text, so it can be saved in the browser.
export interface CriteriaLine {
  heading: string;
  names: string[];
}

export function summarizeRules(rules: RuleDraft[]): CriteriaLine[] {
  return rules.map((rule) => {
    const domainChoice = DOMAIN_CHOICES.find((choice) => choice.value === rule.domain);
    const domainLabel = domainChoice ? domainChoice.label : rule.domain;
    const verb = rule.exclude ? "Does not have" : "Has";
    return { heading: `${verb} ${domainLabel}`, names: rule.picked.map((concept) => concept.name) };
  });
}
