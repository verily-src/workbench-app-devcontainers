import colors from "../libs/colors";
import type { AnnotatedCohortVariant, ClinVarSignificance } from "../types/results";

export interface ClinvarBadgeConfig {
  shortLabel: string;
  ink: string;
  fill: string;
}

// The aggregate badge config for both row and detail badges.
export const CLINVAR_BADGE_CONFIG: Record<ClinVarSignificance, ClinvarBadgeConfig> = {
  Pathogenic: {
    shortLabel: "P",
    ink: colors.textDanger,
    fill: colors.bgDanger,
  },
  "Likely pathogenic": {
    shortLabel: "LP",
    ink: colors.textDanger,
    fill: colors.bgDanger,
  },
  VUS: {
    shortLabel: "VUS",
    ink: colors.textWarning,
    fill: colors.bgWarning,
  },
  "Likely benign": {
    shortLabel: "LB",
    ink: colors.textSuccess,
    fill: colors.bgSuccess,
  },
  Benign: {
    shortLabel: "B",
    ink: colors.textSuccess,
    fill: colors.bgSuccess,
  },
};

/**
 * Whether ClinVar has a record for this variant at all. Not clinvarSignificance: a record whose
 * only classification is "Conflicting interpretations" or "not provided" maps to no significance
 * but is still a real record to show and link to. The VAT dates every ClinVar record it carries,
 * so the last-updated date stands in for the record itself.
 */
export function hasClinvarRecord(variant: AnnotatedCohortVariant): boolean {
  return variant.clinvarLastUpdated !== null;
}

/** ClinVar's highest review status: a practice guideline. */
export const CLINVAR_MAX_STARS = 4;

/** e.g. "criteria provided, multiple submitters, no conflicts", for a star rating shown separately. */
export function clinvarReviewDescription(stars: number, hasConflicts: boolean): string {
  const descriptions: Record<number, string> = {
    0: "no assertion criteria provided",
    1: hasConflicts ? "criteria provided, conflicting classifications" : "criteria provided, single submitter",
    2: "criteria provided, multiple submitters, no conflicts",
    3: "reviewed by expert panel",
    4: "practice guideline",
  };
  return descriptions[stars] ?? "unknown review status";
}
