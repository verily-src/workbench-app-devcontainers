import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BreakdownBar from "./BreakdownBar";

const SEGMENTS = [
  { label: "EUR", count: 52, percent: 52, color: "#F9C854" },
  { label: "AFR", count: 18, percent: 18, color: "#2078B4" },
  { label: "SAS", count: 8, percent: 8, color: "#8CCA90" },
  { label: "MID", count: 2, percent: 2, color: "#CB2D4C" },
];

describe("BreakdownBar", () => {
  afterEach(cleanup);

  it("draws each group as a run in proportion to its count, with every group in the legend beneath", () => {
    const { container } = render(<BreakdownBar segments={SEGMENTS} label="Ancestry" />);

    // Counts as well as shares, so a screen reader gets what the tooltips show.
    const bar = screen.getByRole("img", {
      name: "Ancestry breakdown: EUR: 52 participants (52%); AFR: 18 participants (18%); SAS: 8 participants (8%); MID: 2 participants (2%)",
    });
    const runs = Array.from(bar.children) as HTMLElement[];
    expect(runs).toHaveLength(4);
    expect(runs[0]).toHaveStyle({ flex: "52 0 3px", backgroundColor: "#F9C854" });
    expect(runs[3]).toHaveStyle({ flex: "2 0 3px" });

    const legend = container.lastElementChild!.lastElementChild!;
    expect(legend).toHaveTextContent("EUR52%AFR18%SAS8%MID2%");
  });

  it("gives every group's count to the keyboard: focusing a legend entry shows its tooltip and highlights its run", async () => {
    render(<BreakdownBar segments={SEGMENTS} label="Ancestry" />);
    const runs = Array.from(screen.getByRole("img").children) as HTMLElement[];
    const entry = screen.getByRole("button", { name: "MID: 2 participants (2%)" });

    fireEvent.focus(entry);
    expect(await screen.findByTestId("infoTooltip")).toHaveTextContent("MID: 2 participants (2%)");
    expect(runs[0]).toHaveStyle({ opacity: "0.4" });
    expect(runs[3]).not.toHaveStyle({ opacity: "0.4" });

    fireEvent.blur(entry);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
    expect(runs[0]).not.toHaveStyle({ opacity: "0.4" });
    expect(screen.getAllByRole("button")).toHaveLength(4);
  });

  it("keeps a focused entry's highlight while the pointer passes over and off it", async () => {
    render(<BreakdownBar segments={SEGMENTS} label="Ancestry" />);
    const runs = Array.from(screen.getByRole("img").children) as HTMLElement[];
    const entry = screen.getByRole("button", { name: "MID: 2 participants (2%)" });
    vi.spyOn(entry, "matches").mockReturnValue(true); // keyboard focus, as the browser reports it

    fireEvent.focus(entry);
    expect(await screen.findByTestId("infoTooltip")).toBeInTheDocument();
    fireEvent.mouseEnter(entry);
    fireEvent.mouseLeave(entry);
    // Still focused, so the group stays highlighted and the tooltip stays up.
    expect(runs[0]).toHaveStyle({ opacity: "0.4" });
    expect(screen.getByTestId("infoTooltip")).toBeInTheDocument();

    // And the other way round: blur while the pointer is still over it keeps both, too.
    fireEvent.mouseEnter(entry);
    fireEvent.blur(entry);
    expect(runs[0]).toHaveStyle({ opacity: "0.4" });
    fireEvent.mouseLeave(entry);
    expect(runs[0]).not.toHaveStyle({ opacity: "0.4" });
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("names every run, labelled or not, in the app's tooltip on hover, and quietens the rest", async () => {
    render(<BreakdownBar segments={SEGMENTS} label="Ancestry" />);
    const runs = Array.from(screen.getByRole("img").children) as HTMLElement[];

    fireEvent.mouseEnter(runs[3]);
    expect(await screen.findByTestId("infoTooltip")).toHaveTextContent("MID: 2 participants (2%)");
    expect(runs[0]).toHaveStyle({ opacity: "0.4" });
    expect(runs[3]).not.toHaveStyle({ opacity: "0.4" });

    fireEvent.mouseLeave(runs[3]);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
    expect(runs[0]).not.toHaveStyle({ opacity: "0.4" });
  });
});
