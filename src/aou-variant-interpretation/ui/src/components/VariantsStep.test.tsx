import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import VariantsStep from "./VariantsStep";

describe("VariantsStep", () => {
  afterEach(cleanup);

  /**
   * Regression guard. The textarea was `flex: 1`, whose zero flex-basis overrides `height` --
   * the property the resize handle sets -- so dragging the handle did nothing. jsdom does no
   * layout, so this checks the style that makes resizing work rather than a drag itself.
   */
  it("grows from its own height, so the resize handle works", () => {
    render(<VariantsStep value="" onChange={vi.fn()} limit={50} minHeight={120} />);

    expect(screen.getByRole("textbox", { name: "Candidate variants" })).toHaveStyle({
      flexGrow: "1",
      flexShrink: "0",
      flexBasis: "auto",
      resize: "vertical",
      minHeight: "120px",
    });
  });
});
