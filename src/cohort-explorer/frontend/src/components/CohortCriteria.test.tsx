import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CohortCriteria from "./CohortCriteria";

function lines() {
  return screen.getAllByRole("listitem").map((item) => item.textContent);
}

describe("CohortCriteria", () => {
  it("shows one line for each rule", () => {
    render(
      <CohortCriteria
        criteria={[
          { heading: "Has Condition", names: ["Type 2 diabetes mellitus", "Hypertension"] },
          { heading: "Does not have Drug", names: ["Metformin 500 MG Oral Tablet"] },
        ]}
      />,
    );

    expect(lines()).toEqual([
      "Has Condition: Type 2 diabetes mellitus, Hypertension",
      "Does not have Drug: Metformin 500 MG Oral Tablet",
    ]);
  });

  it("shows the value range of a measurement rule", () => {
    render(
      <CohortCriteria
        criteria={[{ heading: "Has Measurement", names: ["Hemoglobin A1c"], valueRange: "between 6.5 and 9" }]}
      />,
    );

    expect(lines()).toEqual(["Has Measurement: Hemoglobin A1c (result between 6.5 and 9)"]);
  });

  it("shows nothing when there are no rules", () => {
    render(<CohortCriteria criteria={[]} />);

    expect(screen.queryByText("Cohort criteria")).toBeNull();
  });

  it("shows all names of a rule with 3 items", () => {
    render(<CohortCriteria criteria={[{ heading: "Has Drug", names: ["A", "B", "C"] }]} />);

    expect(lines()).toEqual(["Has Drug: A, B, C"]);
  });

  it("shows 3 names and the count of the rest for a rule with 5 items", () => {
    render(<CohortCriteria criteria={[{ heading: "Has Drug", names: ["A", "B", "C", "D", "E"] }]} />);

    expect(lines()).toEqual(["Has Drug: A, B, C and 2 more"]);
  });

  it("lists every name in the tooltip of the count", async () => {
    render(<CohortCriteria criteria={[{ heading: "Has Drug", names: ["A", "B", "C", "D", "E"] }]} />);

    await userEvent.hover(screen.getByText("and 2 more"));

    expect((await screen.findByRole("tooltip")).textContent).toBe("A, B, C, D, E");
  });
});
