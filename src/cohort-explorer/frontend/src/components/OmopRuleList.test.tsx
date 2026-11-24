import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OmopRuleList from "./OmopRuleList";
import { MAX_RULES, buildSpec, makeEmptyRule } from "../omopRules";

vi.mock("../api", () => ({ searchOmopConcepts: vi.fn() }));
import { searchOmopConcepts } from "../api";

const searchMock = vi.mocked(searchOmopConcepts);

const METFORMIN_500 = { concept_id: 40000001, name: "Metformin 500 MG Oral Tablet", vocabulary: "RxNorm", persons: 2 };
const METFORMIN_1000 = { concept_id: 40000002, name: "Metformin 1000 MG Oral Tablet", vocabulary: "RxNorm", persons: 1 };

// Holds the rules the way the real panel will, and shows the spec that would be sent.
function RuleListWithSpec() {
  const [rules, setRules] = useState([makeEmptyRule()]);
  return (
    <div>
      <OmopRuleList rules={rules} resourceId="my-db" schema="omop" onChange={setRules} />
      <pre data-testid="spec">{JSON.stringify(buildSpec("omop", rules))}</pre>
    </div>
  );
}

function shownSpec() {
  return JSON.parse(screen.getByTestId("spec").textContent ?? "");
}

function searchBoxes() {
  return screen.getAllByLabelText("Search by name");
}

function removeRuleButtons() {
  return screen.getAllByRole("button", { name: "Remove rule" });
}

async function searchAndPick(name: string) {
  await userEvent.click(searchBoxes()[0]);
  await userEvent.click(await screen.findByText(name));
}

beforeEach(() => {
  searchMock.mockReset();
  searchMock.mockResolvedValue([METFORMIN_500, METFORMIN_1000]);
});

describe("OmopRuleList", () => {
  it("starts with one empty rule that has Has, Condition and a search box", () => {
    render(<RuleListWithSpec />);

    expect((screen.getByLabelText("Rule") as HTMLSelectElement).value).toBe("include");
    expect((screen.getByLabelText("Domain") as HTMLSelectElement).value).toBe("condition");
    expect(searchBoxes()).toHaveLength(1);
  });

  it("adds a picked item when a result is clicked", async () => {
    render(<RuleListWithSpec />);
    await userEvent.selectOptions(screen.getByLabelText("Domain"), "drug");

    await searchAndPick("Metformin 500 MG Oral Tablet");

    expect(screen.getByLabelText("Remove Metformin 500 MG Oral Tablet")).toBeTruthy();
    expect(shownSpec().criteria[0].concept_ids).toEqual([40000001]);
  });

  it("sends the ID of every picked item and no other IDs", async () => {
    render(<RuleListWithSpec />);
    await userEvent.selectOptions(screen.getByLabelText("Domain"), "drug");
    await searchAndPick("Metformin 500 MG Oral Tablet");
    await userEvent.click(await screen.findByText("Metformin 1000 MG Oral Tablet"));
    await userEvent.click(screen.getByLabelText("Remove Metformin 500 MG Oral Tablet"));

    expect(shownSpec().criteria[0].concept_ids).toEqual([40000002]);
  });

  it("removes a picked item when its x is clicked", async () => {
    render(<RuleListWithSpec />);
    await searchAndPick("Metformin 500 MG Oral Tablet");

    await userEvent.click(screen.getByLabelText("Remove Metformin 500 MG Oral Tablet"));

    expect(screen.queryByLabelText("Remove Metformin 500 MG Oral Tablet")).toBeNull();
    expect(shownSpec().criteria[0].concept_ids).toEqual([]);
  });

  it("clears the picked items when the domain changes", async () => {
    render(<RuleListWithSpec />);
    await searchAndPick("Metformin 500 MG Oral Tablet");

    await userEvent.selectOptions(screen.getByLabelText("Domain"), "drug");

    expect(shownSpec().criteria[0]).toEqual({ domain: "drug", concept_ids: [], exclude: false });
  });

  it("sends exclude true when Does not have is chosen", async () => {
    render(<RuleListWithSpec />);

    await userEvent.selectOptions(screen.getByLabelText("Rule"), "exclude");

    expect(shownSpec().criteria[0].exclude).toBe(true);
  });

  it("adds a rule row when Add rule is clicked", async () => {
    render(<RuleListWithSpec />);

    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));

    expect(searchBoxes()).toHaveLength(2);
  });

  it("turns Add rule off at the rule limit", async () => {
    render(<RuleListWithSpec />);
    for (let added = 1; added < MAX_RULES; added++) {
      await userEvent.click(screen.getByRole("button", { name: "Add rule" }));
    }

    expect(searchBoxes()).toHaveLength(MAX_RULES);
    expect((screen.getByRole("button", { name: "Add rule" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("turns the remove button off when one rule is left", () => {
    render(<RuleListWithSpec />);

    expect((removeRuleButtons()[0] as HTMLButtonElement).disabled).toBe(true);
  });

  it("says a Has rule matches people with any of the items", () => {
    render(<RuleListWithSpec />);

    expect(screen.getByText("Matches people who have any of these items.")).toBeTruthy();
  });

  it("says a Does not have rule matches people with none of the items", async () => {
    render(<RuleListWithSpec />);

    await userEvent.selectOptions(screen.getByLabelText("Rule"), "exclude");

    expect(screen.getByText("Matches people who have none of these items.")).toBeTruthy();
    expect(screen.queryByText("Matches people who have any of these items.")).toBeNull();
  });

  it("says people must match every rule only when there are two or more rules", async () => {
    render(<RuleListWithSpec />);
    expect(screen.queryByText("People must match every rule.")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));

    expect(screen.getByText("People must match every rule.")).toBeTruthy();
  });

  it("offers condition, drug, observation, procedure and measurement as domains", () => {
    render(<RuleListWithSpec />);

    const options = Array.from((screen.getByLabelText("Domain") as HTMLSelectElement).options);
    expect(options.map((option) => option.value)).toEqual([
      "condition",
      "drug",
      "observation",
      "procedure",
      "measurement",
    ]);
  });

  it("says any recorded value counts for observation and measurement only", async () => {
    render(<RuleListWithSpec />);
    const anyValueLine = "Any recorded value counts.";

    for (const domain of ["observation", "measurement"]) {
      await userEvent.selectOptions(screen.getByLabelText("Domain"), domain);
      expect(screen.getByText(anyValueLine)).toBeTruthy();
    }
    for (const domain of ["condition", "drug", "procedure"]) {
      await userEvent.selectOptions(screen.getByLabelText("Domain"), domain);
      expect(screen.queryByText(anyValueLine)).toBeNull();
    }
  });

  describe("value range of a measurement rule", () => {
    async function chooseMeasurementAndPickOne() {
      render(<RuleListWithSpec />);
      await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");
      await searchAndPick("Metformin 500 MG Oral Tablet");
    }

    it("shows no range boxes before an item is picked", async () => {
      render(<RuleListWithSpec />);
      await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");

      expect(screen.queryByLabelText("Lowest value")).toBeNull();
    });

    it("shows the range boxes for a measurement rule with exactly one item", async () => {
      await chooseMeasurementAndPickOne();

      expect(screen.getByLabelText("Lowest value")).toBeTruthy();
      expect(screen.getByLabelText("Highest value")).toBeTruthy();
    });

    it("turns the search box off once one measurement is picked, and says why", async () => {
      await chooseMeasurementAndPickOne();

      expect((searchBoxes()[0] as HTMLInputElement).disabled).toBe(true);
      expect(screen.getByText("A measurement rule holds one item. Remove it to pick another, or add another rule.")).toBeTruthy();
    });

    it("turns the search box on again when the measurement is removed", async () => {
      await chooseMeasurementAndPickOne();

      await userEvent.click(screen.getByLabelText("Remove Metformin 500 MG Oral Tablet"));

      expect((searchBoxes()[0] as HTMLInputElement).disabled).toBe(false);
    });

    it("keeps the search box on after a pick in a domain that holds many items", async () => {
      render(<RuleListWithSpec />);
      await userEvent.selectOptions(screen.getByLabelText("Domain"), "drug");
      await searchAndPick("Metformin 500 MG Oral Tablet");

      expect((searchBoxes()[0] as HTMLInputElement).disabled).toBe(false);
      expect(screen.queryByText(/rule holds one item/)).toBeNull();
    });

    it("shows what the data holds for the picked measurement, and leaves the boxes empty", async () => {
      searchMock.mockResolvedValue([
        { concept_id: 4200001, name: "Hemoglobin A1c", vocabulary: "LOINC", persons: 2, value_min: 5.2, value_max: 7.4 },
      ]);
      render(<RuleListWithSpec />);
      await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");
      await searchAndPick("Hemoglobin A1c");

      expect(screen.getByText("Results in this data run from 5.2 to 7.4. Leave a box empty for no limit.")).toBeTruthy();
      const lowest = screen.getByLabelText("Lowest value") as HTMLInputElement;
      const highest = screen.getByLabelText("Highest value") as HTMLInputElement;
      expect([lowest.value, highest.value]).toEqual(["", ""]);
      expect([lowest.placeholder, highest.placeholder]).toEqual(["5.2", "7.4"]);
      expect("value_min" in shownSpec().criteria[0]).toBe(false);
    });

    it("says when the picked measurement has no numbers in the data", async () => {
      searchMock.mockResolvedValue([
        { concept_id: 4200003, name: "Throat culture", vocabulary: "LOINC", persons: 1, value_min: null, value_max: null },
      ]);
      render(<RuleListWithSpec />);
      await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");
      await searchAndPick("Throat culture");

      expect(screen.getByText("This item has no numeric results in this data.")).toBeTruthy();
    });

    it("shows no range boxes for another domain", async () => {
      render(<RuleListWithSpec />);
      await userEvent.selectOptions(screen.getByLabelText("Domain"), "drug");
      await searchAndPick("Metformin 500 MG Oral Tablet");

      expect(screen.queryByLabelText("Lowest value")).toBeNull();
    });

    it("sends the typed range in the spec as numbers", async () => {
      await chooseMeasurementAndPickOne();

      await userEvent.type(screen.getByLabelText("Lowest value"), "5.5");
      await userEvent.type(screen.getByLabelText("Highest value"), "7.7");

      expect(shownSpec().criteria[0]).toMatchObject({ value_min: 5.5, value_max: 7.7 });
    });

    it("says in words what the rule matches", async () => {
      await chooseMeasurementAndPickOne();
      expect(screen.getByText("Any recorded value counts.")).toBeTruthy();

      await userEvent.type(screen.getByLabelText("Lowest value"), "5.5");
      await userEvent.type(screen.getByLabelText("Highest value"), "7.7");

      expect(screen.getByText("Matches people who have a result between 5.5 and 7.7.")).toBeTruthy();
      expect(screen.queryByText("Any recorded value counts.")).toBeNull();
    });

    it("says no result for a Does not have rule with a range", async () => {
      await chooseMeasurementAndPickOne();
      await userEvent.selectOptions(screen.getByLabelText("Rule"), "exclude");

      await userEvent.type(screen.getByLabelText("Highest value"), "9");

      expect(screen.getByText("Matches people who have no result of at most 9.")).toBeTruthy();
    });

    it("shows a message when the lowest value is above the highest", async () => {
      await chooseMeasurementAndPickOne();

      await userEvent.type(screen.getByLabelText("Lowest value"), "8");
      await userEvent.type(screen.getByLabelText("Highest value"), "7");

      expect(screen.getByText("The lowest value must not be higher than the highest value.")).toBeTruthy();
    });

    it("clears the range when the domain changes", async () => {
      await chooseMeasurementAndPickOne();
      await userEvent.type(screen.getByLabelText("Lowest value"), "5");

      await userEvent.selectOptions(screen.getByLabelText("Domain"), "drug");
      await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");
      await searchAndPick("Metformin 500 MG Oral Tablet");

      expect((screen.getByLabelText("Lowest value") as HTMLInputElement).value).toBe("");
    });

    it("clears the range when the picked item is removed", async () => {
      await chooseMeasurementAndPickOne();
      await userEvent.type(screen.getByLabelText("Lowest value"), "5");

      await userEvent.click(screen.getByLabelText("Remove Metformin 500 MG Oral Tablet"));
      await searchAndPick("Metformin 1000 MG Oral Tablet");

      expect((screen.getByLabelText("Lowest value") as HTMLInputElement).value).toBe("");
    });
  });

  it("removes the chosen rule row", async () => {
    render(<RuleListWithSpec />);
    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));
    await userEvent.selectOptions(screen.getAllByLabelText("Domain")[1], "drug");

    await userEvent.click(removeRuleButtons()[0]);

    await waitFor(() => expect(searchBoxes()).toHaveLength(1));
    expect((screen.getByLabelText("Domain") as HTMLSelectElement).value).toBe("drug");
  });
});
