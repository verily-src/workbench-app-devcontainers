// Every color the UI uses, in one place.
//
// These live in TypeScript rather than as CSS custom properties so that inline style objects can
// use them directly (with autocomplete, and a compile error on a typo) and so derived values can
// be computed from them -- see alpha() below, which is where every rgba() shadow and scrim in the
// app comes from. The only colors still written as literals are the two on <body> in style.css,
// which a stylesheet can't read from here.
//
// Names map 1:1 onto the CSS variables these replaced (--text-accent -> textAccent, etc.). Unlike
// Terra UI's colors.js there are no intensity functions (colors.primary(0.5)): VIA's palette is a
// fixed set of semantic ink/surface pairs rather than a brand color to derive shades from, so a
// call on every reference would be noise.

/**
 * The favicon's navy: the tile behind the lens. It is the app's ink for titles and key figures, its
 * one interactive colour, and its brand colour, so the mark and the page it sits on agree. At 9.8:1
 * on white it carries small text with room to spare.
 */
const NAVY = "#074770";

const colors = {
  // Ink
  textPrimary: NAVY,
  textBody: "#2b2b33",
  textSecondary: "#5b5f73",
  textMuted: "#9598a6",
  textAccent: NAVY,
  textSuccess: "#3b6d11",
  textWarning: "#854f0b",
  textDanger: "#a32d2d",

  // Brand, from the logo's navy tile and green variant rung
  brandNavy: NAVY,
  brandGreen: "#5cc88d",

  // Call to action: the navy itself, so the one filled button in a view is the mark's tile. A step
  // deeper under the pointer.
  brandNavyHover: "#063a5c",

  // Surfaces, from the page backdrop (0) up to cards sitting on it (2)
  surface0: "#f6f5f2",
  surface1: "#fbfaf8",
  surface2: "#ffffff",
  border: "#e2e1dc",
  borderStrong: "#c7c6c0",
  /** borderStrong a step darker: a field's border under the pointer. */
  borderHover: "#a9a8a1",

  // Tinted fills, each paired with the ink of the same name
  bgAccent: "#e1edf4",
  bgSuccess: "#eaf3de",
  bgWarning: "#faeeda",
  bgDanger: "#fcebeb",

  white: "#ffffff",

  subpopEur: "#F9C854",
  subpopAfr: "#2078B4",
  subpopAmr: "#6DACE4",
  subpopEas: "#A27BD7",
  subpopSas: "#8CCA90",
  subpopMid: "#CB2D4C",
  subpopOth: "#B3AEAD",
  subpopFin: "#6B4226",
  subpopNfe: "#E67E22",
  subpopAsj: "#7B2D8E",

  /**
   * The Condition breakdown's series: one hue per picked condition, in the order picked, then a
   * neutral for participants with more than one. Navy, teal and amber rather than the brand's
   * green: green and the neutral are near-identical under red-green colour blindness. Checked
   * pairwise for colour-vision separation (OKLab distance x100 >= 8 simulated, >= 15 normal).
   */
  conditionA: "#074770",
  conditionB: "#2aa198",
  conditionC: "#cf8a1f",
  conditionOverlap: "#dedcd5",
} as const;

export default colors;

/** The Condition breakdown's hues by position in the search's concept list; see conditionA. */
export const CONDITION_SERIES = [colors.conditionA, colors.conditionB, colors.conditionC];

/**
 * Background tints that mark which source a table's column group reports -- All of Us or gnomAD.
 *
 * `header` fills the source's name cell at the top of its column group, solid, with white text:
 * the one cue that still reads when the table is small. `strong` is the soft wash under it in
 * the variants table; `soft` is for the population table nested inside an expanded row, where
 * the same distinction only needs a hint. `strong` and `soft` share one `hover` value so a
 * hovered row reads as a single band.
 */
/** The accent's own tint: All of Us figures, wherever they sit. */
const AOU_TINT = { header: NAVY, strong: "#eef4f8", soft: "#f6f9fc", hover: "#e2ecf4" } as const;

export const sourceTints = {
  aou: AOU_TINT,
  gnomad: { header: "#6c7086", strong: "#f7f6f3", soft: "#fafbfb", hover: "#eeede8" },
  /**
   * The phenotype-matched column group in the merged table. Its figures are All of Us figures
   * too, so it shares the tint; the scope row above says which participants they cover.
   */
  matched: { header: NAVY, strong: AOU_TINT.strong, hover: AOU_TINT.hover },
} as const;

/** Marks the subpopulation with the highest allele frequency in the population table. */
export const POPMAX_BACKGROUND = "#d9e6f0";

/** The same color at partial opacity -- e.g. alpha(colors.textPrimary, 0.14) for a panel shadow. */
export function alpha(hex: string, opacity: number): string {
  const digits = hex.replace("#", "");
  const pairs =
    digits.length === 3
      ? [...digits].map((digit) => digit + digit)
      : [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 6)];
  const [red, green, blue] = pairs.map((pair) => parseInt(pair, 16));
  return `rgba(${red}, ${green}, ${blue}, ${opacity})`;
}