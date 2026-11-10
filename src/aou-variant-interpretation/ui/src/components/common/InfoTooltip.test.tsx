import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import InfoTooltip from "./InfoTooltip";

const TEXT = "Allele count among phenotype-matched participants.";

/** jsdom does no layout, so rects are stubbed per element: the icon, then the tooltip itself. */
function stubRects(icon: DOMRect, tooltip: DOMRect) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    return this.getAttribute("data-testid") === "infoTooltip" ? tooltip : icon;
  });
}

describe("InfoTooltip", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("describes the icon to screen readers without any hovering", () => {
    render(<InfoTooltip text={TEXT} />);

    expect(screen.getByRole("button", { name: "More information" })).toHaveAccessibleDescription(TEXT);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("shows on hover after a short delay, and hides on leaving", () => {
    render(<InfoTooltip text={TEXT} />);
    const icon = screen.getByRole("button", { name: "More information" });

    fireEvent.mouseEnter(icon);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByTestId("infoTooltip")).toHaveTextContent(TEXT);

    fireEvent.mouseLeave(icon);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("doesn't show when the pointer only passes over it", () => {
    render(<InfoTooltip text={TEXT} />);
    const icon = screen.getByRole("button", { name: "More information" });

    fireEvent.mouseEnter(icon);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    fireEvent.mouseLeave(icon);
    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("shows on keyboard focus, and hides on Escape", () => {
    render(<InfoTooltip text={TEXT} />);

    fireEvent.focus(screen.getByRole("button", { name: "More information" }));
    act(() => {
      vi.runAllTimers();
    });
    expect(screen.getByTestId("infoTooltip")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("hides on any scroll, since the icon would move out from under it", () => {
    render(
      <div data-testid="scroller">
        <InfoTooltip text={TEXT} />
      </div>,
    );
    fireEvent.focus(screen.getByRole("button", { name: "More information" }));
    act(() => {
      vi.runAllTimers();
    });

    fireEvent.scroll(screen.getByTestId("scroller"));

    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("keeps clicks from reaching the header underneath, so it never sorts the column", () => {
    const onHeaderClick = vi.fn();
    render(
      <div onClick={onHeaderClick}>
        Cohort AC <InfoTooltip text={TEXT} />
      </div>,
    );

    fireEvent.click(screen.getByRole("button", { name: "More information" }));
    act(() => {
      vi.runAllTimers();
    });

    expect(onHeaderClick).not.toHaveBeenCalled();
    expect(screen.getByTestId("infoTooltip")).toBeInTheDocument();
  });

  it("keeps line breaks in the text, for paragraphs", () => {
    render(<InfoTooltip text={"First paragraph.\n\nSecond paragraph."} />);

    fireEvent.focus(screen.getByRole("button", { name: "More information" }));
    act(() => {
      vi.runAllTimers();
    });

    const tooltip = screen.getByTestId("infoTooltip");
    expect(tooltip).toHaveStyle({ whiteSpace: "pre-line" });
    expect(tooltip.textContent).toBe("First paragraph.\n\nSecond paragraph.");
  });

  it("is muted until hovered, then takes the accent colour", () => {
    render(<InfoTooltip text={TEXT} />);
    const icon = screen.getByRole("button", { name: "More information" });
    const muted = "rgb(149, 152, 166)";
    const accent = "rgb(7, 71, 112)";

    expect(icon).toHaveStyle({ color: muted });
    fireEvent.mouseEnter(icon);
    expect(icon).toHaveStyle({ color: accent });
    fireEvent.mouseLeave(icon);
    expect(icon).toHaveStyle({ color: muted });
  });

  it("stays in the accent colour while its tooltip is open", () => {
    render(<InfoTooltip text={TEXT} />);
    const icon = screen.getByRole("button", { name: "More information" });

    fireEvent.focus(icon);
    act(() => {
      vi.runAllTimers();
    });

    expect(icon).toHaveStyle({ color: "rgb(7, 71, 112)" });
  });

  it("draws a focus ring for keyboard focus but not for a click", () => {
    render(<InfoTooltip text={TEXT} />);
    const icon = screen.getByRole("button", { name: "More information" });
    const matches = vi.spyOn(icon, "matches");

    matches.mockReturnValue(false);
    fireEvent.focus(icon);
    expect(icon.style.boxShadow).toBe("");
    fireEvent.blur(icon);

    matches.mockReturnValue(true);
    fireEvent.focus(icon);
    expect(icon.style.boxShadow).not.toBe("");
    fireEvent.blur(icon);
    expect(icon.style.boxShadow).toBe("");
  });

  it("sits centred above the icon when there's room", () => {
    stubRects(new DOMRect(400, 300, 14, 14), new DOMRect(0, 0, 200, 40));
    render(<InfoTooltip text={TEXT} />);

    fireEvent.focus(screen.getByRole("button", { name: "More information" }));
    act(() => {
      vi.runAllTimers();
    });

    // Centred on the icon's middle (407): 407 - 100. Above it by the 8px gap: 300 - 8 - 40.
    expect(screen.getByTestId("infoTooltip")).toHaveStyle({ left: "307px", top: "252px", visibility: "visible" });
  });

  it("flips below the icon near the top of the window, and stays inside its edges", () => {
    stubRects(new DOMRect(4, 10, 14, 14), new DOMRect(0, 0, 200, 40));
    render(<InfoTooltip text={TEXT} />);

    fireEvent.focus(screen.getByRole("button", { name: "More information" }));
    act(() => {
      vi.runAllTimers();
    });

    // Below: icon bottom (24) + 8px gap. Pushed in to the 8px edge rather than off-screen left.
    expect(screen.getByTestId("infoTooltip")).toHaveStyle({ left: "8px", top: "32px" });
  });
});
