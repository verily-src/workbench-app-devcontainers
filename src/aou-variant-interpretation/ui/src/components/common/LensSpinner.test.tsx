import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import LensSpinner from "./LensSpinner";

const preferReducedMotion = (reduce: boolean) =>
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: reduce && query === "(prefers-reduced-motion: reduce)",
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }) as unknown as MediaQueryList,
  );

const rungs = (container: HTMLElement) => container.querySelector<SVGGElement>('[data-part="rungs"]')!;

describe("LensSpinner", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("scans the rungs through the lens by default", () => {
    preferReducedMotion(false);
    const { container } = render(<LensSpinner />);

    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(rungs(container)).toHaveClass("animate-lens-scan");
    expect(rungs(container).style.animationDuration).toBe("1800ms");
  });

  it("rests in the logo's pose, the green rung centred under the glass", () => {
    preferReducedMotion(false);
    const { container } = render(<LensSpinner />);

    // Every fourth rung is green; the one at rest sits at the lens centre, as in the logo.
    const green = [...container.querySelectorAll("[data-green]")];
    expect(green.map((line) => line.getAttribute("y1"))).toEqual(["27", "51"]);
    expect(green[0]).toHaveAttribute("x1", "18");
    expect(green[0]).toHaveAttribute("x2", "36");
  });

  it("holds still when the user prefers reduced motion", () => {
    preferReducedMotion(true);
    const { container } = render(<LensSpinner />);

    expect(rungs(container)).not.toHaveClass("animate-lens-scan");
    expect(rungs(container).getAttribute("style")).toBeNull();
  });

  it("offsets every spinner to the same wall clock, so spinners mounted apart scan in step", () => {
    preferReducedMotion(false);
    const now = vi.spyOn(performance, "now").mockReturnValue(4000);
    const { container } = render(<LensSpinner />);
    now.mockReturnValue(4900);
    const later = render(<LensSpinner />).container;

    // 4000ms into a 1800ms cycle is 400ms in; 4900ms is 1300ms in. Each starts where the clock is.
    expect(rungs(container).style.animationDelay).toBe("-400ms");
    expect(rungs(later).style.animationDelay).toBe("-1300ms");
  });
});
