import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import AllOfUs from "./AllOfUs";

describe("AllOfUs", () => {
  afterEach(cleanup);

  it("italicizes the program's name", () => {
    render(<AllOfUs />);

    expect(screen.getByText("All of Us")).toHaveStyle({ fontStyle: "italic" });
  });
});
