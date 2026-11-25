import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import OmopCohortPanel from "./OmopCohortPanel";

vi.mock("../api", () => ({ searchOmopConcepts: vi.fn(), createOmopCohort: vi.fn() }));
import { createOmopCohort, searchOmopConcepts } from "../api";

const searchMock = vi.mocked(searchOmopConcepts);
const createCohortMock = vi.mocked(createOmopCohort);

const DIABETES = { concept_id: 201826, name: "Type 2 diabetes mellitus", vocabulary: "SNOMED", persons: 3 };

function showPanel(onOpenInExplorer = vi.fn()) {
  render(<OmopCohortPanel resourceId="my-db" onOpenInExplorer={onOpenInExplorer} />);
  return onOpenInExplorer;
}

function findPeopleButton() {
  return screen.getByRole("button", { name: /find people/i }) as HTMLButtonElement;
}

async function pickDiabetes() {
  await userEvent.click(screen.getByLabelText("Search by name"));
  await userEvent.click(await screen.findByText("Type 2 diabetes mellitus"));
}

async function pickDiabetesAndFindPeople() {
  await pickDiabetes();
  await userEvent.click(findPeopleButton());
}

beforeEach(() => {
  searchMock.mockReset();
  searchMock.mockResolvedValue([DIABETES]);
  createCohortMock.mockReset();
  createCohortMock.mockResolvedValue({ count: 2 });
});

describe("OmopCohortPanel", () => {
  it("shows the title and one empty rule", () => {
    showPanel();

    expect(screen.getByText("Build a cohort")).toBeTruthy();
    expect(screen.getAllByLabelText("Search by name")).toHaveLength(1);
  });

  it("keeps Find people off while a rule has nothing picked", () => {
    showPanel();
    expect(findPeopleButton().disabled).toBe(true);
  });

  it("turns Find people on once every rule has a picked item", async () => {
    showPanel();
    await pickDiabetes();
    expect(findPeopleButton().disabled).toBe(false);
  });

  it("keeps Find people off when a second rule is empty", async () => {
    showPanel();
    await pickDiabetes();
    await userEvent.click(screen.getByRole("button", { name: "Add rule" }));
    expect(findPeopleButton().disabled).toBe(true);
  });

  it("sends the database and the picked rules, then shows how many people match", async () => {
    showPanel();
    await pickDiabetesAndFindPeople();

    expect(createCohortMock).toHaveBeenCalledWith("my-db", {
      schema: "public",
      criteria: [{ domain: "condition", concept_ids: [201826], exclude: false }],
    });
    expect(await screen.findByText("2 people match")).toBeTruthy();
  });

  it("sends the value range of a measurement rule with the request", async () => {
    showPanel();
    await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");
    await pickDiabetes();
    await userEvent.type(screen.getByLabelText("Lowest value"), "5.5");
    await userEvent.type(screen.getByLabelText("Highest value"), "7.7");

    await userEvent.click(findPeopleButton());

    expect(createCohortMock).toHaveBeenCalledWith("my-db", {
      schema: "public",
      criteria: [{ domain: "measurement", concept_ids: [201826], exclude: false, value_min: 5.5, value_max: 7.7 }],
    });
  });

  it("turns Find people off while the lowest value is above the highest", async () => {
    showPanel();
    await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");
    await pickDiabetes();

    await userEvent.type(screen.getByLabelText("Lowest value"), "8");
    await userEvent.type(screen.getByLabelText("Highest value"), "7");

    expect(findPeopleButton().disabled).toBe(true);
  });

  it("turns Find people off while a bound is not a number", async () => {
    showPanel();
    await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");
    await pickDiabetes();

    await userEvent.type(screen.getByLabelText("Highest value"), "--");

    expect(findPeopleButton().disabled).toBe(true);
  });

  it("turns Find people on again once the range is fixed", async () => {
    showPanel();
    await userEvent.selectOptions(screen.getByLabelText("Domain"), "measurement");
    await pickDiabetes();
    await userEvent.type(screen.getByLabelText("Lowest value"), "8");
    await userEvent.type(screen.getByLabelText("Highest value"), "7");

    await userEvent.clear(screen.getByLabelText("Lowest value"));

    expect(findPeopleButton().disabled).toBe(false);
  });

  it("says 1 person matches for a count of one", async () => {
    createCohortMock.mockResolvedValue({ count: 1 });
    showPanel();
    await pickDiabetesAndFindPeople();

    expect(await screen.findByText("1 person matches")).toBeTruthy();
  });

  it("opens the explorer with the schema name and the rules in plain words when Open in Explorer is clicked", async () => {
    const onOpenInExplorer = showPanel();
    await pickDiabetesAndFindPeople();

    await userEvent.click(await screen.findByRole("button", { name: "Open in Explorer" }));

    expect(onOpenInExplorer).toHaveBeenCalledWith("public", [
      { heading: "Has Condition", names: ["Type 2 diabetes mellitus"] },
    ]);
  });

  it("shows the message when the explorer cannot be opened", async () => {
    const onOpenInExplorer = vi.fn().mockRejectedValue(new Error("The cohort was not found. Click Find people again."));
    showPanel(onOpenInExplorer);
    await pickDiabetesAndFindPeople();

    await userEvent.click(await screen.findByRole("button", { name: "Open in Explorer" }));

    expect(await screen.findByText("The cohort was not found. Click Find people again.")).toBeTruthy();
  });

  it("turns Open in Explorer off when nobody matches", async () => {
    createCohortMock.mockResolvedValue({ count: 0 });
    showPanel();
    await pickDiabetesAndFindPeople();

    expect(await screen.findByText("0 people match")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Open in Explorer" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the plain error message and keeps the rules when the request fails", async () => {
    createCohortMock.mockRejectedValue(new Error("The count took longer than 15 seconds and was stopped."));
    showPanel();
    await pickDiabetesAndFindPeople();

    expect(await screen.findByText(/took longer than 15 seconds/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Open in Explorer" })).toBeNull();
    expect(screen.getByLabelText("Remove Type 2 diabetes mellitus")).toBeTruthy();
  });

  it("hides the count when the rules change afterwards", async () => {
    showPanel();
    await pickDiabetesAndFindPeople();
    await screen.findByText("2 people match");

    await userEvent.click(screen.getByLabelText("Remove Type 2 diabetes mellitus"));

    expect(screen.queryByText("2 people match")).toBeNull();
    expect(screen.queryByRole("button", { name: "Open in Explorer" })).toBeNull();
  });

  it("shows the schema name public in the Advanced section", () => {
    showPanel();
    expect((screen.getByLabelText("Schema name") as HTMLInputElement).value).toBe("public");
  });

  it("sends a changed schema name", async () => {
    showPanel();
    await userEvent.clear(screen.getByLabelText("Schema name"));
    await userEvent.type(screen.getByLabelText("Schema name"), "cdm");
    await pickDiabetesAndFindPeople();

    expect(createCohortMock.mock.calls[0][1].schema).toBe("cdm");
  });
});
