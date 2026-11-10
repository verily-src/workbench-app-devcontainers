import { cleanup, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { composeHandlers, useCenterAboveFold } from "./hooks";

function Centred() {
  const ref = useRef<HTMLDivElement>(null);
  useCenterAboveFold(ref, 40);
  return (
    <div data-testid="parent">
      <div ref={ref} data-testid="content" />
    </div>
  );
}

/** Lays the parent out at [top, top + height] in a 1000px window, with 100px of content. */
function layOut(top: number, height: number) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ top, bottom: top + height, height } as DOMRect);
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(100);
  vi.stubGlobal("innerHeight", 1000);
}

const offsetOf = () => (document.querySelector("[data-testid=content]") as HTMLElement).style.transform;

describe("useCenterAboveFold", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("centres the content in the part of the parent above the fold", () => {
    // Visible from 600 to the window's bottom at 1000: centre 800, so 800 - 600 - 50.
    layOut(600, 3000);
    render(<Centred />);
    expect(offsetOf()).toBe("translateY(150px)");
  });

  it("measures from under the pinned top bar once the parent's top scrolls past it", () => {
    // Visible from 40 to 1000: centre 520, which is 2520 into the parent; less half the content.
    layOut(-2000, 3000);
    render(<Centred />);
    expect(offsetOf()).toBe("translateY(2470px)");
  });

  it("stays where it was placed as the page scrolls", () => {
    layOut(600, 3000);
    render(<Centred />);
    layOut(-500, 3000);
    window.dispatchEvent(new Event("scroll"));
    expect(offsetOf()).toBe("translateY(150px)");
  });

  it("stays inside the parent", () => {
    layOut(1200, 3000);
    render(<Centred />);
    expect(offsetOf()).toBe("translateY(0px)");
  });
});

describe("composeHandlers", () => {
  it("calls both handlers where names overlap, base first, and keeps the rest", () => {
    const calls: string[] = [];
    const merged = composeHandlers(
      { onMouseEnter: () => calls.push("base enter"), onBlur: () => calls.push("base blur") },
      { onMouseEnter: () => calls.push("extra enter"), onFocus: () => calls.push("extra focus") },
    );

    merged.onMouseEnter();
    merged.onBlur();
    merged.onFocus();
    expect(calls).toEqual(["base enter", "extra enter", "base blur", "extra focus"]);
  });
});
