import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConceptSearchBox from "./ConceptSearchBox";

vi.mock("../api", () => ({ searchOmopConcepts: vi.fn() }));
import { searchOmopConcepts } from "../api";

const searchMock = vi.mocked(searchOmopConcepts);

const METFORMIN_500 = { concept_id: 40000001, name: "Metformin 500 MG Oral Tablet", vocabulary: "RxNorm", persons: 2 };
const METFORMIN_1000 = { concept_id: 40000002, name: "Metformin 1000 MG Oral Tablet", vocabulary: "RxNorm", persons: 1 };

function showSearchBox(onPick = vi.fn(), pickedIds: number[] = []) {
  render(
    <ConceptSearchBox resourceId="my-db" schema="omop" domain="drug" pickedIds={pickedIds} onPick={onPick} />,
  );
  return onPick;
}

function searchBox() {
  return screen.getByLabelText("Search by name");
}

beforeEach(() => {
  searchMock.mockReset();
  searchMock.mockResolvedValue([METFORMIN_500, METFORMIN_1000]);
});

describe("ConceptSearchBox", () => {
  it("lists the most common items when the empty box is opened", async () => {
    showSearchBox();
    await userEvent.click(searchBox());

    await screen.findByText("Metformin 500 MG Oral Tablet");
    expect(searchMock).toHaveBeenCalledOnce();
    expect(searchMock).toHaveBeenCalledWith("my-db", "omop", "drug", "");
  });

  it("sends one search, after the user stops typing", async () => {
    showSearchBox();
    await userEvent.type(searchBox(), "metformin");
    await waitFor(() => expect(searchMock).toHaveBeenCalledWith("my-db", "omop", "drug", "metformin"));
    await new Promise((resolve) => setTimeout(resolve, 500));

    // Clicking the box also made one search for the empty text. Count only the typed ones.
    const typedSearches = searchMock.mock.calls.filter((call) => call[3] !== "");
    expect(typedSearches).toHaveLength(1);
  });

  it("does not search for fewer than 3 typed characters", async () => {
    showSearchBox();
    await userEvent.type(searchBox(), "me");
    await new Promise((resolve) => setTimeout(resolve, 500));

    const typedSearches = searchMock.mock.calls.filter((call) => call[3] !== "");
    expect(typedSearches).toHaveLength(0);
    expect(screen.getByText("Type at least 3 characters.")).toBeTruthy();
  });

  it("searches once 3 characters are typed", async () => {
    showSearchBox();
    await userEvent.type(searchBox(), "met");

    await waitFor(() => expect(searchMock).toHaveBeenCalledWith("my-db", "omop", "drug", "met"));
  });

  it("shows each result with its name, ID and number of people", async () => {
    showSearchBox();
    await userEvent.click(searchBox());

    await screen.findByText("Metformin 500 MG Oral Tablet");
    expect(screen.getByText("40000001 · 2 people")).toBeTruthy();
    expect(screen.getByText("40000002 · 1 person")).toBeTruthy();
  });

  it("shows the lowest and highest number of a measurement in its result row", async () => {
    searchMock.mockResolvedValue([
      { concept_id: 4200001, name: "Hemoglobin A1c", vocabulary: "LOINC", persons: 2, value_min: 5.2, value_max: 7.4 },
    ]);
    showSearchBox();
    await userEvent.click(searchBox());

    expect(await screen.findByText("4200001 · 2 people · values 5.2 to 7.4")).toBeTruthy();
  });

  it("shows no numbers for a result without any", async () => {
    searchMock.mockResolvedValue([
      { concept_id: 4200003, name: "Throat culture", vocabulary: "LOINC", persons: 1, value_min: null, value_max: null },
    ]);
    showSearchBox();
    await userEvent.click(searchBox());

    expect(await screen.findByText("4200003 · 1 person")).toBeTruthy();
  });

  it("turns the search box off when it is disabled", () => {
    render(
      <ConceptSearchBox resourceId="my-db" schema="omop" domain="measurement" pickedIds={[]} onPick={vi.fn()} disabled />,
    );

    expect((searchBox() as HTMLInputElement).disabled).toBe(true);
  });

  it("passes the clicked result to onPick", async () => {
    const onPick = showSearchBox();
    await userEvent.click(searchBox());

    await userEvent.click(await screen.findByText("Metformin 500 MG Oral Tablet"));

    expect(onPick).toHaveBeenCalledWith(METFORMIN_500);
  });

  it("keeps the typed text after a result is clicked", async () => {
    showSearchBox();
    await userEvent.type(searchBox(), "metformin");
    await userEvent.click(await screen.findByText("Metformin 500 MG Oral Tablet"));

    expect((searchBox() as HTMLInputElement).value).toBe("metformin");
  });

  it("greys out a result that is already picked", async () => {
    const onPick = showSearchBox(vi.fn(), [40000001]);
    await userEvent.click(searchBox());
    await screen.findByText("Metformin 500 MG Oral Tablet");

    const pickedRow = screen.getByText("Metformin 500 MG Oral Tablet").closest("[role=button]");
    expect(pickedRow?.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(screen.getByText("Metformin 500 MG Oral Tablet"));
    expect(onPick).not.toHaveBeenCalled();
    expect(screen.getByText(/40000001 · 2 people · added/)).toBeTruthy();
  });

  it("says so when nothing matches", async () => {
    searchMock.mockResolvedValue([]);
    showSearchBox();
    await userEvent.type(searchBox(), "zzzz");

    expect(await screen.findByText("No matches. Try other words.")).toBeTruthy();
  });

  it("shows the plain message when the search fails", async () => {
    searchMock.mockRejectedValue(new Error("Could not connect to the database. Check the database choice and try again."));
    showSearchBox();
    await userEvent.click(searchBox());

    expect(await screen.findByText(/Could not connect to the database/)).toBeTruthy();
  });
});
