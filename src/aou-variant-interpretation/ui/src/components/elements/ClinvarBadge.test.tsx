import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import colors, { alpha } from "../../libs/colors";
import ClinvarBadge from "./ClinvarBadge";

describe("ClinvarBadge", () => {
  it("shows the short code in split mode and the full classification in tag mode", () => {
    const { unmount } = render(<ClinvarBadge significance="Pathogenic" />);
    expect(screen.getByText("P")).toBeInTheDocument();
    expect(screen.queryByText("Pathogenic")).not.toBeInTheDocument();
    unmount();

    render(<ClinvarBadge significance="Likely pathogenic" mode="tag" />);
    expect(screen.getByText("Likely pathogenic")).toBeInTheDocument();
    expect(screen.queryByText("LP")).not.toBeInTheDocument();
  });

  it("appends the review stars when given, and leaves them out when null", () => {
    const { container, unmount } = render(<ClinvarBadge significance="VUS" stars={3} />);
    expect(screen.getByText("3★")).toBeInTheDocument();
    expect(screen.getByText("3★")).toHaveStyle({ color: colors.textSecondary });
    expect(container.firstChild).toHaveAttribute("title", "ClinVar: VUS, 3 of 4 stars: reviewed by expert panel");
    unmount();

    const { container: plain } = render(<ClinvarBadge significance="Benign" stars={null} />);
    expect(screen.queryByText(/★/)).not.toBeInTheDocument();
    expect(plain.textContent).toBe("B");
    expect(plain.firstChild).toHaveAttribute("title", "ClinVar: Benign");
  });

  it("is a tinted pill in the classification's colour, one width for every split badge", () => {
    const { container } = render(<ClinvarBadge significance="VUS" stars={2} />);
    expect(container.firstChild).toHaveStyle({
      backgroundColor: colors.bgWarning,
      color: colors.textWarning,
      border: `1px solid ${alpha(colors.textWarning, 0.35)}`,
      borderRadius: "999px",
      width: "68px",
    });
    // The code is centered in a fixed slot, so the divider and stars land at the same x in every row.
    expect(screen.getByText("VUS")).toHaveStyle({ width: "30px", textAlign: "center" });

    const { container: tag } = render(<ClinvarBadge significance="VUS" mode="tag" />);
    expect(tag.firstChild).not.toHaveStyle({ width: "68px" });
  });

  it("links to ClinVar in a new tab when given a URL, without expanding the row beneath", async () => {
    const onRowClick = vi.fn();
    const { unmount } = render(
      <div onClick={onRowClick}>
        <ClinvarBadge significance="Pathogenic" stars={2} href="https://www.ncbi.nlm.nih.gov/clinvar/variation/1/" />
      </div>,
    );

    const link = screen.getByRole("link", {
      name: "ClinVar: Pathogenic, 2 of 4 stars: criteria provided, multiple submitters, no conflicts. Open in ClinVar (opens in new tab)",
    });
    // The app's tooltip, not the browser's: it shows on focus too, and spells the review status out.
    // The empty title keeps a titled ancestor's native tooltip from showing alongside it.
    expect(link).toHaveAttribute("title", "");
    fireEvent.focus(link);
    const bubble = await screen.findByTestId("infoTooltip");
    expect(bubble).toHaveTextContent("Pathogenic");
    expect(bubble).toHaveTextContent("2 of 4 stars: criteria provided, multiple submitters, no conflicts");
    expect(bubble).toHaveTextContent("Click to open ClinVar in a new tab.");
    fireEvent.blur(link);
    expect(screen.queryByTestId("infoTooltip")).not.toBeInTheDocument();
    expect(link).toHaveAttribute("href", "https://www.ncbi.nlm.nih.gov/clinvar/variation/1/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveTextContent("P2★");

    fireEvent.click(link);
    expect(onRowClick).not.toHaveBeenCalled();
    unmount();
  });

  it("stays a plain badge without a URL, and says what one star means when submissions conflict", () => {
    const { unmount } = render(<ClinvarBadge significance="Benign" stars={1} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByTitle("ClinVar: Benign, 1 of 4 stars: criteria provided, single submitter")).toBeInTheDocument();
    unmount();

    const conflicting = render(<ClinvarBadge significance="VUS" stars={1} conflicts />);
    expect(screen.getByTitle("ClinVar: VUS, 1 of 4 stars: criteria provided, conflicting classifications")).toBeInTheDocument();
    conflicting.unmount();
  });
});
