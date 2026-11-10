import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import colors from "../../libs/colors";
import CopyButton from "./CopyButton";

describe("CopyButton", () => {
  const writeText = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    writeText.mockReset();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
  });

  afterEach(() => {
    cleanup();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it("renders an accessible copy button", () => {
    render(<CopyButton getText={() => "abc"} label="Copy value" />);

    expect(screen.getByRole("button", { name: "Copy value" })).toHaveAttribute("title", "Copy value");
  });

  it("copies the current text when clicked", async () => {
    writeText.mockResolvedValue(undefined);
    const getText = vi.fn(() => "copied text");
    render(<CopyButton getText={getText} label="Copy value" />);

    fireEvent.click(screen.getByRole("button", { name: "Copy value" }));
    await act(async () => {});

    expect(writeText).toHaveBeenCalledWith("copied text");
    expect(getText).toHaveBeenCalledTimes(1);
  });

  it("shows the success state after a successful copy and then resets", async () => {
    writeText.mockResolvedValue(undefined);
    render(<CopyButton getText={() => "copied text"} label="Copy value" />);

    const button = screen.getByRole("button", { name: "Copy value" });
    fireEvent.click(button);
    await act(async () => {});

    expect(button).toHaveStyle({
      color: colors.textSuccess,
    });

    await act(async () => {
      vi.advanceTimersByTime(1200);
    });

    expect(button).not.toHaveStyle({
      color: colors.textSuccess,
    });
  });

  it("does not enter the success state when clipboard write fails", async () => {
    writeText.mockRejectedValue(new Error("denied"));
    render(<CopyButton getText={() => "copied text"} label="Copy value" />);

    const button = screen.getByRole("button", { name: "Copy value" });
    fireEvent.click(button);
    await act(async () => {});

    expect(writeText).toHaveBeenCalled();
    expect(button).not.toHaveStyle({
      color: colors.textSuccess,
    });
  });
});
