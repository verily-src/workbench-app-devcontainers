import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import colors from "../../libs/colors";
import { SUBPOP_COLOR } from "../../utils/subpopulations";
import SubpopBadge from "./SubpopBadge";

describe("SubpopBadge", () => {
  it("renders the subpopulation code", () => {
    render(<SubpopBadge subpopulation="AFR" />);

    expect(screen.getByText("AFR")).toBeInTheDocument();
  });

  it("renders the shared badge styles", () => {
    render(<SubpopBadge subpopulation="AMR" />);

    expect(screen.getByText("AMR")).toHaveStyle({
      display: "inline-flex",
      width: "52px",
      backgroundColor: colors.surface1,
      border: `1px solid ${colors.border}`,
      borderRadius: "10px",
      color: colors.textSecondary,
      fontSize: "11px",
      fontWeight: "600",
    });
  });

  it("renders the correct color dot for an AoU-only subpopulation", () => {
    const { container } = render(<SubpopBadge subpopulation="MID" />);
    const badge = container.firstChild as HTMLElement;
    const dot = badge.firstChild as HTMLElement;

    expect(dot).toHaveStyle({
      backgroundColor: SUBPOP_COLOR.MID,
    });
  });

  it("renders the correct color dot for a gnomAD-only subpopulation", () => {
    const { container } = render(<SubpopBadge subpopulation="ASJ" />);
    const badge = container.firstChild as HTMLElement;
    const dot = badge.firstChild as HTMLElement;

    expect(screen.getByText("ASJ")).toBeInTheDocument();
    expect(dot).toHaveStyle({
      backgroundColor: SUBPOP_COLOR.ASJ,
    });
  });

  it("uses the shared color mapping for shared subpopulations", () => {
    const { container } = render(<SubpopBadge subpopulation="SAS" />);
    const badge = container.firstChild as HTMLElement;
    const dot = badge.firstChild as HTMLElement;

    expect(dot).toHaveStyle({
      backgroundColor: colors.subpopSas,
    });
  });
});
