import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ViewSwitcher from "./ViewSwitcher";

describe("ViewSwitcher", () => {
  afterEach(cleanup);

  it("marks the showing view pressed and switches on click", () => {
    const onChange = vi.fn();
    render(<ViewSwitcher value="table" onChange={onChange} />);

    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(onChange).toHaveBeenCalledWith("review");
  });

  it("marks Review unavailable with its reason as the description, shown as a tooltip on hover and on focus", () => {
    vi.useFakeTimers();
    try {
      const onChange = vi.fn();
      render(<ViewSwitcher value="table" onChange={onChange} reviewUnavailableReason="Add a phenotype filter to review." />);

      // aria-disabled, not disabled: the option stays in the tab order so keyboard users can
      // reach the reason, and clicking it does nothing.
      const review = screen.getByRole("button", { name: "Review" });
      expect(review).not.toBeDisabled();
      expect(review).toHaveAttribute("aria-disabled", "true");
      expect(review).toHaveAccessibleDescription("Add a phenotype filter to review.");
      fireEvent.click(review);
      expect(onChange).not.toHaveBeenCalled();

      // Focus shows the reason at once; hover shows it after the delay.
      fireEvent.focus(review);
      act(() => vi.advanceTimersByTime(0));
      expect(screen.getByTestId("infoTooltip")).toHaveTextContent("Add a phenotype filter to review.");
      fireEvent.blur(review);
      act(() => vi.advanceTimersByTime(0));
      expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();

      fireEvent.mouseEnter(review);
      act(() => vi.advanceTimersByTime(200));
      expect(screen.getByTestId("infoTooltip")).toHaveTextContent("Add a phenotype filter to review.");
    } finally {
      vi.useRealTimers();
    }
  });
});
