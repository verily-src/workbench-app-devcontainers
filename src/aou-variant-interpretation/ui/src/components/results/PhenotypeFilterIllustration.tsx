import type { CSSProperties } from "react";
import colors from "../../libs/colors";

// The no-phenotype picture: every participant as a scatter of ancestry-coloured dots, falling
// toward a dashed funnel where the phenotype filter would go, with an navy "+" on its rim, the
// colour of the button beside it. Decorative; the text beside it carries the meaning.

const VIEW_W = 220;
const VIEW_H = 128;

/** The ancestry palette the breakdown bar uses, so the crowd reads as the same participants. */
const DOT_COLORS = [
  colors.subpopEur,
  colors.subpopAfr,
  colors.subpopAmr,
  colors.subpopEas,
  colors.subpopSas,
  colors.subpopMid,
  colors.subpopOth,
] as const;

/** Hand-placed so the crowd looks scattered rather than gridded, denser toward the funnel's mouth. */
const DOTS: { x: number; y: number; r: number; color: string }[] = [
  { x: 42, y: 24, r: 5, color: DOT_COLORS[0] },
  { x: 64, y: 12, r: 4.5, color: DOT_COLORS[1] },
  { x: 86, y: 30, r: 5.5, color: DOT_COLORS[2] },
  { x: 106, y: 13, r: 4.5, color: DOT_COLORS[3] },
  { x: 128, y: 34, r: 5, color: DOT_COLORS[4] },
  { x: 150, y: 15, r: 5, color: DOT_COLORS[5] },
  { x: 172, y: 28, r: 4.5, color: DOT_COLORS[6] },
  { x: 190, y: 13, r: 4, color: DOT_COLORS[0] },
  { x: 54, y: 44, r: 4, color: DOT_COLORS[3] },
  { x: 108, y: 46, r: 5, color: DOT_COLORS[1] },
  { x: 160, y: 44, r: 4.5, color: DOT_COLORS[2] },
  { x: 30, y: 10, r: 3.5, color: DOT_COLORS[4] },
  { x: 78, y: 50, r: 3.5, color: DOT_COLORS[6] },
  { x: 136, y: 52, r: 3.5, color: DOT_COLORS[5] },
];

const styles = {
  svg: {
    display: "block",
    flexShrink: 0,
    maxWidth: "100%",
    height: "auto",
  },
} as const satisfies Record<string, CSSProperties>;

interface PhenotypeFilterIllustrationProps {
  /** Rendered width in px; height follows. */
  width?: number;
}

export default function PhenotypeFilterIllustration({ width = 160 }: PhenotypeFilterIllustrationProps) {
  return (
    <svg
      viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
      width={width}
      height={(width * VIEW_H) / VIEW_W}
      style={styles.svg}
      aria-hidden="true"
      data-testid="phenotype-filter-illustration"
    >
      {/* Everyone, with nothing yet to pick them apart by. */}
      {DOTS.map((dot, index) => (
        <circle key={index} cx={dot.x} cy={dot.y} r={dot.r} fill={dot.color} fillOpacity={0.85} />
      ))}
      {/* The missing filter. */}
      <path
        d="M56 66 H164 L120 104 V124 H100 V104 Z"
        fill={colors.surface1}
        stroke={colors.borderStrong}
        strokeWidth={1.5}
        strokeDasharray="5 4"
        strokeLinejoin="round"
      />
      {/* The "add" badge on its rim. */}
      <circle cx="164" cy="66" r="10" fill={colors.brandNavy} />
      <path d="M164 61.5v9M159.5 66h9" stroke={colors.white} strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}
