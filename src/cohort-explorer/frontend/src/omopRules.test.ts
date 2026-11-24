import { describe, expect, it } from "vitest";
import {
  buildSpec,
  describeValueRange,
  everyRuleHasPickedItem,
  everyValueRangeIsValid,
  findValueRangeProblem,
  makeEmptyRule,
  summarizeRules,
} from "./omopRules";

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

  it("describes a Has rule with its domain and the names of its items", () => {
    const rule = { ...makeEmptyRule(), picked: [DIABETES] };

    expect(summarizeRules([rule])).toEqual([{ heading: "Has Condition", names: ["Type 2 diabetes mellitus"] }]);
  });

  it("describes a rule from each new domain with its label", () => {
    const rules = ["observation", "procedure", "measurement"].map((domain) => ({ ...makeEmptyRule(), domain }));

    expect(summarizeRules(rules).map((line) => line.heading)).toEqual([
      "Has Observation",
      "Has Procedure",
      "Has Measurement",
    ]);
  });

  it("describes a Does not have rule with its domain and the names of its items", () => {
    const rule = { ...makeEmptyRule(), exclude: true, domain: "drug", picked: [METFORMIN_500, METFORMIN_1000] };

    expect(summarizeRules([rule])).toEqual([
      { heading: "Does not have Drug", names: ["Metformin 500 MG Oral Tablet", "Metformin 1000 MG Oral Tablet"] },
    ]);
  });

  describe("value range of a measurement rule", () => {
    const A1C = { concept_id: 4200001, name: "Hemoglobin A1c", vocabulary: "LOINC", persons: 2 };
    const BMI = { concept_id: 4200002, name: "Body mass index", vocabulary: "LOINC", persons: 2 };

    function a1cRule(valueMin: string, valueMax: string) {
      return { ...makeEmptyRule(), domain: "measurement", picked: [A1C], valueMin, valueMax };
    }

    it("starts a new rule with no range", () => {
      const rule = makeEmptyRule();
      expect([rule.valueMin, rule.valueMax]).toEqual(["", ""]);
    });

    it("sends the lowest and highest value as numbers", () => {
      expect(buildSpec("public", [a1cRule("5.5", "7.7")]).criteria[0]).toEqual({
        domain: "measurement", concept_ids: [4200001], exclude: false, value_min: 5.5, value_max: 7.7,
      });
    });

    it("sends only the bound that was typed", () => {
      const criterion = buildSpec("public", [a1cRule("6.5", "")]).criteria[0];
      expect(criterion.value_min).toBe(6.5);
      expect("value_max" in criterion).toBe(false);
    });

    it("sends no range when both boxes are empty", () => {
      const criterion = buildSpec("public", [a1cRule("", "")]).criteria[0];
      expect("value_min" in criterion || "value_max" in criterion).toBe(false);
    });

    it("sends no range for a measurement rule with two items", () => {
      const rule = { ...a1cRule("5", "8"), picked: [A1C, BMI] };
      expect("value_min" in buildSpec("public", [rule]).criteria[0]).toBe(false);
    });

    it("sends no range for another domain, even if text is left in the boxes", () => {
      const rule = { ...a1cRule("5", "8"), domain: "drug" };
      expect("value_min" in buildSpec("public", [rule]).criteria[0]).toBe(false);
    });

    it("sends a negative lowest value", () => {
      expect(buildSpec("public", [a1cRule("-3.5", "")]).criteria[0].value_min).toBe(-3.5);
    });

    it("finds no problem with a correct range or no range", () => {
      expect(findValueRangeProblem(a1cRule("5", "8"))).toBeNull();
      expect(findValueRangeProblem(a1cRule("", ""))).toBeNull();
      expect(findValueRangeProblem(a1cRule("7", "7"))).toBeNull();
    });

    it("says when the lowest value is above the highest", () => {
      expect(findValueRangeProblem(a1cRule("8", "7"))).toBe(
        "The lowest value must not be higher than the highest value.",
      );
    });

    it("says when a bound is not a number", () => {
      expect(findValueRangeProblem(a1cRule("abc", ""))).toBe("Enter the values as numbers.");
      expect(findValueRangeProblem(a1cRule("", "1e999"))).toBe("Enter the values as numbers.");
    });

    it("finds no problem for a rule that cannot have a range", () => {
      expect(findValueRangeProblem({ ...a1cRule("9", "1"), domain: "drug" })).toBeNull();
    });

    it("says every range is valid only when no rule has a problem", () => {
      expect(everyValueRangeIsValid([a1cRule("5", "8"), makeEmptyRule()])).toBe(true);
      expect(everyValueRangeIsValid([a1cRule("5", "8"), a1cRule("9", "1")])).toBe(false);
    });

    it("describes a range in words", () => {
      expect(describeValueRange(a1cRule("5.5", "7.7"))).toBe("between 5.5 and 7.7");
      expect(describeValueRange(a1cRule("6.5", ""))).toBe("of at least 6.5");
      expect(describeValueRange(a1cRule("", "9"))).toBe("of at most 9");
      expect(describeValueRange(a1cRule("", ""))).toBeNull();
      expect(describeValueRange(a1cRule("9", "1"))).toBeNull();
    });

    it("adds the range to the criteria line of the rule", () => {
      expect(summarizeRules([a1cRule("6.5", "9")])).toEqual([
        { heading: "Has Measurement", names: ["Hemoglobin A1c"], valueRange: "between 6.5 and 9" },
      ]);
    });
  });
});

