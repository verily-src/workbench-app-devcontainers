import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useTooltip } from "./useTooltip";
import type { TooltipPlacement } from "./useTooltip";

/** The smallest anchor: a button that only spreads the hook's props. */
function Anchor({ placement }: { placement?: TooltipPlacement }) {
  const ref = useRef<HTMLButtonElement>(null);
  const tooltip = useTooltip(ref, "Explains itself", placement);
  return (
    <button ref={ref} type="button" data-hovered={tooltip.hovered} data-keyboard={tooltip.keyboardFocused} {...tooltip.anchorProps}>
      Anchor
      {tooltip.bubble}
    </button>
  );
}

/** jsdom does no layout, so rects are stubbed per element: the anchor, then the tooltip itself. */
function stubRects(anchor: DOMRect, tooltip: DOMRect) {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
    return this.getAttribute("data-testid") === "infoTooltip" ? tooltip : anchor;
  });
}

describe("useTooltip's placement", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("sits to the anchor's left when asked, centred on its middle", async () => {
    stubRects(new DOMRect(400, 300, 60, 20), new DOMRect(0, 0, 200, 40));
    render(<Anchor placement="left" />);

    fireEvent.focus(screen.getByRole("button"));
    const bubble = await screen.findByTestId("infoTooltip");
    // Left of the anchor by the 8px gap: 400 - 8 - 200. Centred on its middle (310): 310 - 20.
    expect(bubble).toHaveStyle({ left: "192px", top: "290px", visibility: "visible" });
    // The arrow is on the right edge, pointing back at the anchor's middle: 310 - 290 - 4.
    expect(bubble.querySelector("span")).toHaveStyle({ right: "-4px", top: "16px" });
  });

  it("flips to the right when there's no room on the left", async () => {
    stubRects(new DOMRect(50, 300, 60, 20), new DOMRect(0, 0, 200, 40));
    render(<Anchor placement="left" />);

    fireEvent.focus(screen.getByRole("button"));
    const bubble = await screen.findByTestId("infoTooltip");
    // Right of the anchor by the gap: 50 + 60 + 8.
    expect(bubble).toHaveStyle({ left: "118px", top: "290px" });
    expect(bubble.querySelector("span")).toHaveStyle({ left: "-4px" });
  });

  it("sits below when asked, and flips above at the bottom of the window", async () => {
    stubRects(new DOMRect(400, 300, 60, 20), new DOMRect(0, 0, 200, 40));
    const below = render(<Anchor placement="bottom" />);
    fireEvent.focus(screen.getByRole("button"));
    // Below the anchor by the gap: 320 + 8. Centred: 430 - 100.
    expect(await screen.findByTestId("infoTooltip")).toHaveStyle({ left: "330px", top: "328px" });
    below.unmount();

    stubRects(new DOMRect(400, window.innerHeight - 30, 60, 20), new DOMRect(0, 0, 200, 40));
    render(<Anchor placement="bottom" />);
    fireEvent.focus(screen.getByRole("button"));
    // No room beneath: above instead, by the gap: (innerHeight - 30) - 8 - 40.
    expect(await screen.findByTestId("infoTooltip")).toHaveStyle({ top: `${window.innerHeight - 78}px` });
  });
});

describe("useTooltip's anchor props", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("show on focus without the hover delay, and hide on blur", async () => {
    render(<Anchor />);
    const anchor = screen.getByRole("button");

    fireEvent.focus(anchor);
    expect(await screen.findByTestId("infoTooltip")).toHaveTextContent("Explains itself");

    fireEvent.blur(anchor);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("show on click at once, and on hover only after the delay", () => {
    vi.useFakeTimers();
    render(<Anchor />);
    const anchor = screen.getByRole("button");

    fireEvent.mouseEnter(anchor);
    expect(anchor).toHaveAttribute("data-hovered", "true");
    // Short of the delay: nothing yet. Past it: shown.
    act(() => vi.advanceTimersByTime(50));
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(200));
    expect(screen.getByTestId("infoTooltip")).toBeInTheDocument();

    fireEvent.mouseLeave(anchor);
    expect(anchor).toHaveAttribute("data-hovered", "false");
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();

    // A click shows at once: only the zero-delay timer stands between it and the bubble.
    fireEvent.click(anchor);
    act(() => vi.advanceTimersByTime(0));
    expect(screen.getByTestId("infoTooltip")).toBeInTheDocument();
  });

  it("keep the tooltip while keyboard focus remains after the pointer leaves, and hide on blur", async () => {
    render(<Anchor />);
    const anchor = screen.getByRole("button");
    vi.spyOn(anchor, "matches").mockReturnValue(true);

    fireEvent.focus(anchor);
    expect(await screen.findByTestId("infoTooltip")).toBeInTheDocument();
    fireEvent.mouseEnter(anchor);
    fireEvent.mouseLeave(anchor);
    expect(screen.getByTestId("infoTooltip")).toBeInTheDocument();

    fireEvent.blur(anchor);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("keep the tooltip while the pointer remains after blur, and hide when it leaves", async () => {
    render(<Anchor />);
    const anchor = screen.getByRole("button");

    fireEvent.mouseEnter(anchor);
    fireEvent.focus(anchor);
    expect(await screen.findByTestId("infoTooltip")).toBeInTheDocument();
    fireEvent.blur(anchor);
    expect(screen.getByTestId("infoTooltip")).toBeInTheDocument();

    fireEvent.mouseLeave(anchor);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("still close on leaving after a click, since mouse focus doesn't pin the tooltip", async () => {
    render(<Anchor />);
    const anchor = screen.getByRole("button");
    vi.spyOn(anchor, "matches").mockReturnValue(false);

    fireEvent.mouseEnter(anchor);
    fireEvent.focus(anchor); // what a click does to a button
    expect(await screen.findByTestId("infoTooltip")).toBeInTheDocument();

    fireEvent.mouseLeave(anchor);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
  });

  it("report keyboard focus only when the browser would draw a focus ring", () => {
    render(<Anchor />);
    const anchor = screen.getByRole("button");

    vi.spyOn(anchor, "matches").mockReturnValue(false);
    fireEvent.focus(anchor);
    expect(anchor).toHaveAttribute("data-keyboard", "false");
    fireEvent.blur(anchor);

    vi.spyOn(anchor, "matches").mockReturnValue(true);
    fireEvent.focus(anchor);
    expect(anchor).toHaveAttribute("data-keyboard", "true");
  });
});
