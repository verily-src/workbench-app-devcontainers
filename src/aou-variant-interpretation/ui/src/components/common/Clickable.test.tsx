import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Clickable from "./Clickable";

describe("Clickable", () => {
  it("renders as a button with type=button by default", () => {
    render(<Clickable>Press me</Clickable>);

    expect(screen.getByRole("button", { name: "Press me" })).toHaveAttribute("type", "button");
  });

  it("applies the base style when not hovered", () => {
    render(<Clickable style={{ color: "rgb(1, 2, 3)" }}>Styled</Clickable>);

    expect(screen.getByRole("button", { name: "Styled" })).toHaveStyle({
      color: "rgb(1, 2, 3)",
    });
  });

  it("merges hoverStyle on mouse enter", () => {
    render(
      <Clickable style={{ color: "rgb(1, 2, 3)" }} hoverStyle={{ color: "rgb(4, 5, 6)" }}>
        Hover me
      </Clickable>,
    );

    const button = screen.getByRole("button", { name: "Hover me" });
    fireEvent.mouseEnter(button);

    expect(button).toHaveStyle({
      color: "rgb(4, 5, 6)",
    });
  });

  it("removes hoverStyle on mouse leave", () => {
    render(
      <Clickable style={{ color: "rgb(1, 2, 3)" }} hoverStyle={{ color: "rgb(4, 5, 6)" }}>
        Hover away
      </Clickable>,
    );

    const button = screen.getByRole("button", { name: "Hover away" });
    fireEvent.mouseEnter(button);
    fireEvent.mouseLeave(button);

    expect(button).toHaveStyle({
      color: "rgb(1, 2, 3)",
    });
  });

  it("does not apply hoverStyle when disabled", () => {
    render(
      <Clickable
        disabled
        style={{ color: "rgb(1, 2, 3)" }}
        hoverStyle={{ color: "rgb(4, 5, 6)" }}
        disabledStyle={{ opacity: "0.5" }}
      >
        Disabled hover
      </Clickable>,
    );

    const button = screen.getByRole("button", { name: "Disabled hover" });
    fireEvent.mouseEnter(button);

    expect(button).toHaveStyle({
      color: "rgb(1, 2, 3)",
      opacity: "0.5",
    });
  });

  it("applies disabledStyle when disabled", () => {
    render(
      <Clickable disabled style={{ color: "rgb(1, 2, 3)" }} disabledStyle={{ opacity: "0.5" }}>
        Disabled
      </Clickable>,
    );

    expect(screen.getByRole("button", { name: "Disabled" })).toHaveStyle({
      color: "rgb(1, 2, 3)",
      opacity: "0.5",
    });
  });

  it("forwards mouse enter and leave events to callers", () => {
    const onMouseEnter = vi.fn();
    const onMouseLeave = vi.fn();

    render(
      <Clickable onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
        Events
      </Clickable>,
    );

    const button = screen.getByRole("button", { name: "Events" });
    fireEvent.mouseEnter(button);
    fireEvent.mouseLeave(button);

    expect(onMouseEnter).toHaveBeenCalledTimes(1);
    expect(onMouseLeave).toHaveBeenCalledTimes(1);
  });

  it("forwards click handlers", () => {
    const onClick = vi.fn();
    render(<Clickable onClick={onClick}>Click me</Clickable>);

    fireEvent.click(screen.getByRole("button", { name: "Click me" }));

    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
