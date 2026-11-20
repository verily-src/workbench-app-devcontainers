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

  it("removes the chosen rule row", async () => {
    render(<RuleListWithSpec />);
    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));
    await userEvent.selectOptions(screen.getAllByLabelText("Domain")[1], "drug");

    await userEvent.click(removeRuleButtons()[0]);

    await waitFor(() => expect(searchBoxes()).toHaveLength(1));
    expect((screen.getByLabelText("Domain") as HTMLSelectElement).value).toBe("drug");
  });
});
