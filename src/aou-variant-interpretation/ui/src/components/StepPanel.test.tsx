import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import StepPanel from "./StepPanel";

describe("StepPanel", () => {
  afterEach(cleanup);

  it("renders its step number, title and body", () => {
    render(
      <StepPanel stepNumber={2} title="Phenotype">
        <p>body</p>
      </StepPanel>,
    );

    expect(screen.getByRole("heading", { name: "Phenotype" })).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("puts a description between the title and the body when given one", () => {
    render(
      <StepPanel stepNumber={1} title="Candidate variants" description="What this step does.">
        <p>body</p>
      </StepPanel>,
    );

    const description = screen.getByText("What this step does.");
    expect(description.compareDocumentPosition(screen.getByText("body"))).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(
      screen.getByRole("heading", { name: "Candidate variants" }).compareDocumentPosition(description),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("renders an optional tag", () => {
    render(
      <StepPanel stepNumber={2} title="Phenotype" tags={[{ label: "Optional", variant: "optional" }]}>
        <p>body</p>
      </StepPanel>,
    );

    expect(screen.getByText("Optional")).toBeInTheDocument();
  });

  it("renders several tags in order, with any hover text", () => {
    render(
      <StepPanel
        stepNumber={1}
        title="Candidate variants"
        tags={[
          { label: "3 entered", variant: "count", title: "Variants entered" },
          { label: "limit 50", variant: "limit" },
        ]}
      >
        <p>body</p>
      </StepPanel>,
    );

    const header = screen.getByRole("heading", { name: "Candidate variants" }).parentElement!;
    expect(header).toHaveTextContent(/3 entered.*limit 50/);
    expect(screen.getByText("3 entered")).toHaveAttribute("title", "Variants entered");
  });

  /**
   * Regression guard. StepPanel spreads Style.elements.panel, which clips to its rounded
   * corners with overflow: hidden -- and that also clips anything a child positions outside
   * the panel. It cut off ConditionSearchField's dropdown at the panel edge, with no way to
   * reach the hidden options, because the clipping ancestor isn't itself scrollable.
   *
   * If this goes back to "hidden", the condition dropdown silently breaks again.
   */
  it("does not clip children that overflow the panel", () => {
    const { container } = render(
      <StepPanel stepNumber={2} title="Phenotype">
        <p>body</p>
      </StepPanel>,
    );

    expect(container.firstChild).toHaveStyle({ overflow: "visible" });
  });

  it("keeps the step number in the plain look when numbered", () => {
    render(
      <StepPanel stepNumber={1} title="Candidate variants" appearance="plain" numbered>
        <p>body</p>
      </StepPanel>,
    );

    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Candidate variants" })).toBeInTheDocument();
  });

  it("drops the card and step number when plain, keeping the title and tags", () => {
    const { container } = render(
      <StepPanel stepNumber={2} title="Phenotype" appearance="plain" tags={[{ label: "Optional", variant: "optional" }]}>
        <p>body</p>
      </StepPanel>,
    );

    expect(screen.getByRole("heading", { name: "Phenotype" })).toBeInTheDocument();
    expect(screen.getByText("Optional")).toBeInTheDocument();
    expect(screen.queryByText("2")).not.toBeInTheDocument();
    expect(container.firstChild).not.toHaveStyle({ borderRadius: "12px" });
  });

  /** The header rounds its own top corners, which is what overflow: hidden used to do. */
  it("rounds the header's top corners itself", () => {
    render(
      <StepPanel stepNumber={2} title="Phenotype">
        <p>body</p>
      </StepPanel>,
    );

    const header = screen.getByRole("heading", { name: "Phenotype" }).parentElement;
    expect(header).toHaveStyle({
      borderTopLeftRadius: "11px",
      borderTopRightRadius: "11px",
    });
  });
});
