import { describe, expect, it } from "vitest";
import { describeHpo } from "./hpo";

describe("describeHpo", () => {
  it("names an exact term by its id, with the match explained", () => {
    expect(describeHpo({ id: "HP:0001636", name: "Tetralogy of Fallot", match: "exact" })).toEqual({
      label: "HP:0001636",
      tooltip: "HPO HP:0001636 Tetralogy of Fallot. Matched on the condition's name.",
      spoken: "HPO term HP:0001636, Tetralogy of Fallot",
    });
  });

  it("marks a nearest term with ≈ and says it is broader", () => {
    expect(describeHpo({ id: "HP:0003124", name: "Hypercholesterolemia", match: "approximate" })).toEqual({
      label: "≈ HP:0003124",
      tooltip: "Nearest HPO term: HP:0003124 Hypercholesterolemia. Broader than the condition; no exact term matched its name.",
      spoken: "nearest HPO term HP:0003124, Hypercholesterolemia",
    });
  });

  it("adds that a link opens the HPO browser", () => {
    const words = describeHpo({ id: "HP:0001636", name: "Tetralogy of Fallot", match: "exact" }, { link: true });
    expect(words.label).toBe("HP:0001636");
    expect(words.tooltip).toBe("HPO HP:0001636 Tetralogy of Fallot. Matched on the condition's name. Opens the HPO browser.");
    expect(words.spoken).toBe("HPO term HP:0001636, Tetralogy of Fallot, opens the HPO browser");
  });
});
