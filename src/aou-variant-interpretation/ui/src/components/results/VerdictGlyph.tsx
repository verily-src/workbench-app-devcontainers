import colors, { alpha } from "../../libs/colors";
import type { VerdictTone } from "./verdictTone";

interface VerdictGlyphProps {
  tone: VerdictTone;
  /** The disc's diameter in px; the glyph scales with it. */
  size?: number;
  /** A full-strength disc with a white glyph, for the selected entry in a list. */
  solid?: boolean;
}

/**
 * A verdict's direction in a disc of its own ink: up for enriched, down for depleted, level for
 * similar, a single dash for no direction. Used by the verdict strip and the rail, so the two match.
 */
export default function VerdictGlyph({ tone, size = 24, solid = false }: VerdictGlyphProps) {
  const glyph = Math.round(size * 0.58);
  return (
    <span
      aria-hidden="true"
      style={{
        display: "inline-grid",
        placeItems: "center",
        flexShrink: 0,
        width: size,
        height: size,
        borderRadius: "50%",
        background: solid ? tone.ink : alpha(tone.ink, 0.14),
        color: solid ? colors.white : tone.ink === colors.textMuted ? colors.textSecondary : tone.ink,
      }}
    >
      <svg width={glyph} height={glyph} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
        <path d={tone.glyph} />
      </svg>
    </span>
  );
}
