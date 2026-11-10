import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { APP_VERSION } from "../../libs/version";
import Footer from "./Footer";

describe("Footer", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders the version, beta badge, and Broad logo", () => {
    render(<Footer />);

    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByTitle("VIA version")).toHaveTextContent(`VIA v${APP_VERSION}`);
    expect(screen.getByRole("img", { name: "Broad Institute" })).toHaveAttribute("src", "/broad-logo.svg");
  });
});
