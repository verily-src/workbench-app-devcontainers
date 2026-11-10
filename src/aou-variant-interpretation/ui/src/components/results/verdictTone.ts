import colors from "../../libs/colors";
import { SIMILARITY_FOLD, type Enrichment, type Verdict } from "../../utils/statistics";

// How each Review verdict looks, in one place: the detail's verdict strip, the rail's dots and
// ratios, and the rail's legend all read from here, so they can't drift apart.

export interface VerdictTone {
  ink: string;
  /** The verdict strip's background. It has no border, so even the neutral verdicts need a fill that shows on a white panel. */
  fill: string;
  word: string;
  /** The rule behind the verdict, for the rail's legend. */
  rule: string;
  /** A 24-unit SVG path for the verdict's direction: up, down, level (two lines), or none (one dash). */
  glyph: string;
}

const GLYPH_UP = "M12 19V5M6 11l6-6 6 6";
const GLYPH_DOWN = "M12 5v14M6 13l6 6 6-6";
const GLYPH_LEVEL = "M5 9h14M5 15h14";
const GLYPH_NONE = "M7 12h10";

export const VERDICT_TONE: Record<Verdict, VerdictTone> = {
  enriched: { ink: colors.textDanger, fill: colors.bgDanger, word: "Enriched", rule: "interval above 1", glyph: GLYPH_UP },
  depleted: { ink: colors.textAccent, fill: colors.bgAccent, word: "Depleted", rule: "interval below 1", glyph: GLYPH_DOWN },
  similar: {
    ink: colors.textSecondary,
    fill: colors.surface0,
    word: "Similar frequency",
    rule: `within ${1 / SIMILARITY_FOLD}×–${SIMILARITY_FOLD}×`,
    glyph: GLYPH_LEVEL,
  },
  inconclusive: {
    ink: colors.textMuted,
    fill: colors.surface0,
    word: "Inconclusive",
    rule: "too few alleles",
    glyph: GLYPH_NONE,
  },
};

const NO_COMPARISON: VerdictTone = {
  ink: colors.textMuted,
  fill: colors.surface0,
  word: "No comparison",
  rule: "",
  glyph: GLYPH_NONE,
};

/** The tone for a comparison's verdict, or for a variant with nothing to compare. */
export function verdictTone(enrichment: Enrichment | null): VerdictTone {
  return enrichment ? VERDICT_TONE[enrichment.verdict] : NO_COMPARISON;
}
