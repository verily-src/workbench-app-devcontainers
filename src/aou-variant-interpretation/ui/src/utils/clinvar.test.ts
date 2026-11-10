import colors from "../libs/colors";
import { describe, expect, it } from "vitest";
import type { AnnotatedCohortVariant } from "../types/results";
import { CLINVAR_BADGE_CONFIG, clinvarReviewDescription, hasClinvarRecord } from "./clinvar";

describe("clinvar utils", () => {
  it("exposes the expected badge config for each aggregate ClinVar significance", () => {
    expect(CLINVAR_BADGE_CONFIG.Pathogenic).toEqual({
      shortLabel: "P",
      ink: colors.textDanger,
      fill: colors.bgDanger,
    });
    expect(CLINVAR_BADGE_CONFIG["Likely pathogenic"]).toEqual({
      shortLabel: "LP",
      ink: colors.textDanger,
      fill: colors.bgDanger,
    });
    expect(CLINVAR_BADGE_CONFIG.VUS).toEqual({
      shortLabel: "VUS",
      ink: colors.textWarning,
      fill: colors.bgWarning,
    });
    expect(CLINVAR_BADGE_CONFIG["Likely benign"]).toEqual({
      shortLabel: "LB",
      ink: colors.textSuccess,
      fill: colors.bgSuccess,
    });
    expect(CLINVAR_BADGE_CONFIG.Benign).toEqual({
      shortLabel: "B",
      ink: colors.textSuccess,
      fill: colors.bgSuccess,
    });
  });

  it("treats a variant as having a ClinVar record when the record is dated, even with no consensus", () => {
    const withRecord = { clinvarSignificance: null, clinvarLastUpdated: "2024-02-14" } as AnnotatedCohortVariant;
    const withoutRecord = { clinvarSignificance: null, clinvarLastUpdated: null } as AnnotatedCohortVariant;

    expect(hasClinvarRecord(withRecord)).toBe(true);
    expect(hasClinvarRecord(withoutRecord)).toBe(false);
  });

  it("describes each review status, and falls back for an out-of-range star count", () => {
    expect(clinvarReviewDescription(0, false)).toBe("no assertion criteria provided");
    expect(clinvarReviewDescription(1, false)).toBe("criteria provided, single submitter");
    expect(clinvarReviewDescription(1, true)).toBe("criteria provided, conflicting classifications");
    expect(clinvarReviewDescription(2, false)).toBe("criteria provided, multiple submitters, no conflicts");
    expect(clinvarReviewDescription(3, false)).toBe("reviewed by expert panel");
    expect(clinvarReviewDescription(4, false)).toBe("practice guideline");
    expect(clinvarReviewDescription(9, false)).toBe("unknown review status");
  });
});
