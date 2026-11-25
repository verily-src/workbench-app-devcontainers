import type { OmopConcept, OmopRule, OmopSpec } from "./api";

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

// The domains that have a value column in app/omop_domains.py. A rule on one of them holds exactly
// one item, because numbers of different measurements (a temperature and an antibody level) cannot
// share one range. For more measurements, the user adds more rules.
const DOMAINS_WITH_VALUE_COLUMN = ["measurement"];

// True once a rule on such a domain has its one item, so the search must not add another.
export function isRuleFullWithOneItem(rule: RuleDraft): boolean {
  return DOMAINS_WITH_VALUE_COLUMN.includes(rule.domain) && rule.picked.length >= 1;
}

export function canHaveValueRange(rule: RuleDraft): boolean {
  return DOMAINS_WITH_VALUE_COLUMN.includes(rule.domain) && rule.picked.length === 1;
}

// Plain decimal numbers only, such as -3, 5.5, .5 or 1e2. Number() alone would also accept 0x10.
const NUMBER_PATTERN = /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/;

// null means the box is empty. NaN means the text is not a finite number.
function readBound(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  if (!NUMBER_PATTERN.test(trimmed)) return Number.NaN;
  const bound = Number(trimmed);
  return Number.isFinite(bound) ? bound : Number.NaN;
}

export function findValueRangeProblem(rule: RuleDraft): string | null {
  if (!canHaveValueRange(rule)) return null;
  const lowest = readBound(rule.valueMin);
  const highest = readBound(rule.valueMax);
  if (Number.isNaN(lowest) || Number.isNaN(highest)) return "Enter the values as numbers.";
  if (lowest !== null && highest !== null && lowest > highest) {
    return "The lowest value must not be higher than the highest value.";
  }
  return null;
}

export function everyValueRangeIsValid(rules: RuleDraft[]): boolean {
  return rules.every((rule) => findValueRangeProblem(rule) === null);
}

// The range in words, for example "between 5.5 and 7.7". null when the rule has no range.
export function describeValueRange(rule: RuleDraft): string | null {
  if (!canHaveValueRange(rule) || findValueRangeProblem(rule) !== null) return null;
  const lowest = readBound(rule.valueMin);
  const highest = readBound(rule.valueMax);
  if (lowest !== null && highest !== null) return `between ${lowest} and ${highest}`;
  if (lowest !== null) return `of at least ${lowest}`;
  if (highest !== null) return `of at most ${highest}`;
  return null;
}

// One rule as the user is building it. It keeps the whole concept, not only its ID,
// so the screen can show the name of each picked item.
export interface RuleDraft {
  id: string;
  exclude: boolean;
  domain: string;
  picked: OmopConcept[];
  // What the user typed for the lowest and highest value. Empty text means no limit.
  valueMin: string;
  valueMax: string;
}

let lastRuleNumber = 0;

export function makeEmptyRule(): RuleDraft {
  lastRuleNumber += 1;
  return {
    id: `rule-${lastRuleNumber}`,
    exclude: false,
    domain: DOMAIN_CHOICES[0].value,
    picked: [],
    valueMin: "",
    valueMax: "",
  };
}

export function everyRuleHasPickedItem(rules: RuleDraft[]): boolean {
  return rules.every((rule) => rule.picked.length > 0);
}

// Turn the rules on the screen into the spec the backend expects.
export function buildSpec(schema: string, rules: RuleDraft[]): OmopSpec {
  return {
    schema,
    criteria: rules.map((rule) => {
      const spec_rule: OmopRule = {
        domain: rule.domain,
        concept_ids: rule.picked.map((concept) => concept.concept_id),
        exclude: rule.exclude,
      };
      const lowest = canHaveValueRange(rule) ? readBound(rule.valueMin) : null;
      const highest = canHaveValueRange(rule) ? readBound(rule.valueMax) : null;
      // A bound that is not a number is left out. The screen already turns Find people off for it.
      if (lowest !== null && !Number.isNaN(lowest)) spec_rule.value_min = lowest;
      if (highest !== null && !Number.isNaN(highest)) spec_rule.value_max = highest;
      return spec_rule;
    }),
  };
}

// One rule in plain words, for the Explorer screen. For example the heading "Has Condition"
// and the names of the items. It holds only text, so it can be saved in the browser.
export interface CriteriaLine {
  heading: string;
  names: string[];
  // For example "between 5.5 and 7.7". Only for a measurement rule with a value range.
  valueRange?: string;
}

export function summarizeRules(rules: RuleDraft[]): CriteriaLine[] {
  return rules.map((rule) => {
    const domainChoice = DOMAIN_CHOICES.find((choice) => choice.value === rule.domain);
    const domainLabel = domainChoice ? domainChoice.label : rule.domain;
    const verb = rule.exclude ? "Does not have" : "Has";
    const line: CriteriaLine = { heading: `${verb} ${domainLabel}`, names: rule.picked.map((concept) => concept.name) };
    const valueRange = describeValueRange(rule);
    if (valueRange !== null) line.valueRange = valueRange;
    return line;
  });
}
