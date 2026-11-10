// Style objects shared by two or more components -- the closest thing VIA has to a design system.
//
// Components style themselves with inline `style` objects rather than stylesheets. Anything used
// in more than one place lands here, imported as:
//
//   import * as Style from "../libs/style";
//   <div style={{ ...Style.elements.panel, width: 500 }}>
//
// Spreading is how overrides work, so keep these groups flat and single-purpose. A style that only
// one component uses belongs in a local `styles` object in that component's own file instead.
//
// `as const satisfies Record<string, CSSProperties>` gets us both halves of the type check: the
// values stay narrow enough to spread without widening, and a misspelled or invalid CSS property
// fails to compile.

import type { CSSProperties } from "react";
import colors, { alpha } from "./colors";

/** Variant IDs, protein changes and version numbers -- anything that should line up per-character. */
export const monoFamily = '"SF Mono", "Courier New", monospace';

/** Buttons, inputs and inline callouts. Panels use the larger panelRadius. */
export const radius = 8;
export const panelRadius = 12;

export const shadows = {
  /** Results panels, which sit flat on the page. */
  panel: `0 1px 3px ${alpha(colors.textPrimary, 0.06)}`,
  /** The entry page's step cards and recent-search list, which float above the hero. */
  raised: `0 12px 28px ${alpha(colors.textPrimary, 0.14)}`,
  /** The selected pill in a segmented control. */
  pill: `0 1px 2px ${alpha(colors.textPrimary, 0.12)}`,
} as const;

export const elements = {
  /** The bordered white container behind every panel and card. */
  panel: {
    background: colors.surface2,
    border: `1px solid ${colors.border}`,
    borderRadius: panelRadius,
    overflow: "hidden",
  },
  /** A panel's title strip. */
  panelHeader: {
    display: "flex",
    alignItems: "center",
    padding: "12px 14px",
    background: colors.surface1,
    borderBottom: `1px solid ${colors.border}`,
  },
  /** A panel's title: dark ink, not the accent, which elsewhere means "clickable". */
  panelTitle: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: 700,
    letterSpacing: -0.1,
  },
  /** Small uppercase label introducing a value: "Condition", "Updated", "Sources". */
  eyebrow: {
    fontSize: 10,
    fontWeight: 700,
    color: colors.textMuted,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  mono: {
    fontFamily: monoFamily,
    fontSize: 11.5,
  },
  /**
   * For text centered against an icon beside it. Trims the text's box to cap height and baseline;
   * otherwise it keeps the font's descender space, which digits and capitals don't use, so they
   * sit ~0.5px high of the icon. Browsers without text-box just keep that small offset.
   */
  trimmedText: {
    textBox: "trim-both cap alphabetic",
  },
  /** The em dash in muted ink that stands in for "no value here". */
  notAvailable: {
    color: colors.textMuted,
  },
  /** In the accessibility tree for screen readers, but not drawn. */
  visuallyHidden: {
    position: "absolute",
    width: 1,
    height: 1,
    margin: -1,
    padding: 0,
    border: 0,
    overflow: "hidden",
    clip: "rect(0 0 0 0)",
    whiteSpace: "nowrap",
  },
  /**
   * InfoTooltip's button around its outlined "i". Muted until hovered or open (tooltipIconActive),
   * so a header row of them doesn't read as a row of buttons. 20px, larger than the 15px icon,
   * for an easier target; the small margin plus that padding keeps it ~4px from its label.
   */
  tooltipIcon: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 20,
    height: 20,
    marginLeft: 1,
    padding: 0,
    border: "none",
    borderRadius: "50%",
    background: "none",
    color: colors.textMuted,
    verticalAlign: "middle",
    cursor: "help",
  },
  tooltipIconActive: {
    color: colors.textAccent,
  },
  /** Keyboard focus only, not a click; see InfoTooltip. */
  tooltipIconFocusRing: {
    outline: "none",
    boxShadow: `0 0 0 2px ${alpha(colors.textAccent, 0.35)}`,
  },
  /** A placeholder bar that pulses while content loads; pair with the animate-skeleton-pulse class. */
  skeleton: {
    height: 14,
    borderRadius: 4,
    background: colors.border,
  },
  /** The sentence under a settings panel's title saying what the panel is for. */
  panelIntro: {
    marginBottom: 14,
    fontSize: 12,
    lineHeight: 1.5,
    color: colors.textSecondary,
  },
  /** A failed request, stated in place of the content it was for. */
  errorNote: {
    padding: "10px 12px",
    borderRadius: radius,
    background: colors.bgDanger,
    color: colors.textDanger,
    fontSize: 12,
  },
  /** The numbered disc that labels a search step, on the step's header and on the row that opens one. */
  stepNumber: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    width: 20,
    height: 20,
    borderRadius: "50%",
    background: colors.textAccent,
    color: colors.white,
    fontSize: 11,
    fontWeight: 700,
  },
  /** Explanatory line under a form field. */
  fieldHint: {
    marginTop: 6,
    fontSize: 11.5,
    lineHeight: 1.5,
    color: colors.textMuted,
  },
} as const satisfies Record<string, CSSProperties>;

// Each `*Hover` object is meant to be merged over its base while the pointer is inside the
// element, which is what <Clickable> does with its `hoverStyle` prop.
export const buttons = {
  /** The one call to action in a view, filled in the brand navy: the entry page's Search, the results page's Export TSV. */
  primary: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    padding: "7px 14px",
    border: "none",
    borderRadius: radius,
    background: colors.brandNavy,
    color: colors.white,
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
  },
  primaryHover: {
    background: colors.brandNavyHover,
  },
  /** Outlined neutral button standing next to a primary one, e.g. the drawer's Cancel. */
  secondary: {
    padding: "7px 14px",
    border: `1px solid ${colors.borderStrong}`,
    borderRadius: radius,
    background: colors.surface2,
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: 600,
    cursor: "pointer",
  },
  secondaryHover: {
    background: colors.surface1,
  },
  /** Outlined button in accent ink, for a secondary action that navigates or reveals: "Add phenotype filter". */
  accent: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 12px",
    border: `1px solid ${colors.borderStrong}`,
    borderRadius: radius,
    background: "none",
    color: colors.textAccent,
    fontSize: 11.5,
    fontWeight: 600,
    cursor: "pointer",
  },
  accentHover: {
    background: colors.bgAccent,
  },
  /** The outline button in red, for throwing something away. */
  danger: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "6px 12px",
    border: `1px solid ${colors.textDanger}`,
    borderRadius: radius,
    background: "none",
    color: colors.textDanger,
    fontSize: 11.5,
    fontWeight: 600,
    cursor: "pointer",
  },
  dangerHover: {
    background: colors.bgDanger,
  },
  /** Icon-only button with no chrome until hovered: copy, expand-row. */
  icon: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: 3,
    border: "none",
    borderRadius: 4,
    background: "none",
    color: colors.textMuted,
    cursor: "pointer",
  },
  iconHover: {
    background: colors.surface0,
    color: colors.textAccent,
  },
  disabled: {
    opacity: 0.5,
    cursor: "default",
    pointerEvents: "none",
  },
} as const satisfies Record<string, CSSProperties>;

/**
 * A 1px solid border, written as longhands for anything whose border colour changes on hover or
 * focus. With the `border` shorthand plus a `borderColor` override, React deletes the override
 * when the state ends instead of restoring the colour, and the border falls back to the text
 * colour -- a near-black outline. Longhands keep `borderColor` a key React always sets.
 */
export function stateBorder(color: string): CSSProperties {
  return { borderWidth: 1, borderStyle: "solid", borderColor: color };
}

export const inputs = {
  /** Prose field -- a phenotype term, a search box. */
  text: {
    width: "100%",
    padding: "8px 10px",
    ...stateBorder(colors.borderStrong),
    borderRadius: radius,
    background: colors.surface1,
    color: colors.textBody,
    fontFamily: "inherit",
    fontSize: 12,
  },
  /** Field holding variant IDs, where a monospace face keeps chr-pos-ref-alt readable. */
  mono: {
    width: "100%",
    padding: "10px 12px",
    ...stateBorder(colors.borderStrong),
    borderRadius: radius,
    background: colors.surface1,
    color: colors.textBody,
    fontFamily: monoFamily,
    fontSize: 13,
  },
  /** Merged over the base while focused, in place of a `:focus` rule. Needs a stateBorder base. */
  focused: {
    outline: "none",
    borderColor: colors.textAccent,
    background: colors.surface2,
  },
} as const satisfies Record<string, CSSProperties>;

// Both variant tables are built from these. Note that neither sets borderCollapse: the cohort
// table needs `separate` for its two stacked sticky header rows (see VariantsPanel), while
// the phenotype-matched table below it uses `collapse`.
export const table = {
  base: {
    width: "100%",
    fontSize: 12,
    whiteSpace: "nowrap",
    // Digits line up down a column without a monospace face.
    fontVariantNumeric: "tabular-nums",
  },
  /** Wrapper that scrolls the table under its own sticky header. */
  scroller: {
    overflow: "auto",
    scrollbarWidth: "thin",
  },
  headerCell: {
    position: "sticky",
    padding: "8px 10px",
    background: colors.surface1,
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: 600,
    textAlign: "left",
    zIndex: 1,
  },
  bodyCell: {
    padding: "7px 10px",
    borderBottom: `1px solid ${colors.border}`,
    color: colors.textBody,
  },
  sortable: {
    cursor: "pointer",
    userSelect: "none",
  },
  sortableHover: {
    color: colors.textAccent,
  },
  /**
   * The sort control beside a sortable header's label: a real button, so sorting reaches the
   * keyboard, holding the sort icon in a fixed-width slot so the header doesn't shift when it
   * becomes the sort key. At rest it shows both arrows, muted, so a reader can tell which
   * columns sort.
   */
  sortButton: {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    width: 12,
    marginLeft: 2,
    padding: 0,
    border: "none",
    background: "none",
    verticalAlign: "middle",
    color: colors.textMuted,
    cursor: "pointer",
  },
  sortButtonActive: {
    color: colors.textAccent,
  },
} as const satisfies Record<string, CSSProperties>;

/**
 * The small round swatch tying a row to its slice of a donut chart.
 *
 * A function rather than a static object because the color is the whole point and always comes
 * from the data -- the same reason Terra UI's style.ts has entries like `itemContainer(selected)`.
 */
export function colorDot(color: string, size = 7): CSSProperties {
  return {
    width: size,
    height: size,
    borderRadius: "50%",
    background: color,
    flexShrink: 0,
  };
}
