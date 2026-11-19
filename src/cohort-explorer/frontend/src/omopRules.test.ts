import { describe, expect, it } from "vitest";
import { buildSpec, everyRuleHasPickedItem, makeEmptyRule } from "./omopRules";

const METFORMIN_500 = { concept_id: 40000001, name: "Metformin 500 MG Oral Tablet", vocabulary: "RxNorm", persons: 2 };
const METFORMIN_1000 = { concept_id: 40000002, name: "Metformin 1000 MG Oral Tablet", vocabulary: "RxNorm", persons: 1 };
const DIABETES = { concept_id: 201826, name: "Type 2 diabetes mellitus", vocabulary: "SNOMED", persons: 3 };

describe("omop rules", () => {
  it("starts a new rule as Has, Condition, with nothing picked", () => {
    const rule = makeEmptyRule();
    expect(rule).toMatchObject({ exclude: false, domain: "condition", picked: [] });
  });

  it("gives each new rule its own id", () => {
    expect(makeEmptyRule().id).not.toBe(makeEmptyRule().id);
  });

  it("builds a spec with the ID of every picked item and no other IDs", () => {
    const diabetesRule = { ...makeEmptyRule(), picked: [DIABETES] };
    const drugRule = { ...makeEmptyRule(), domain: "drug", picked: [METFORMIN_500, METFORMIN_1000] };

    expect(buildSpec("omop", [diabetesRule, drugRule])).toEqual({
      schema: "omop",
      criteria: [
        { domain: "condition", concept_ids: [201826], exclude: false },
        { domain: "drug", concept_ids: [40000001, 40000002], exclude: false },
      ],
    });
  });

  it("builds a Does not have rule with exclude set to true", () => {
    const rule = { ...makeEmptyRule(), exclude: true, picked: [DIABETES] };
    expect(buildSpec("omop", [rule]).criteria[0].exclude).toBe(true);
  });

  it("says rules are complete only when every rule has a picked item", () => {
    const filled = { ...makeEmptyRule(), picked: [DIABETES] };
    expect(everyRuleHasPickedItem([filled])).toBe(true);
    expect(everyRuleHasPickedItem([filled, makeEmptyRule()])).toBe(false);
  });
});
