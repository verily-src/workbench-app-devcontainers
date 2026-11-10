import { useRef } from "react";
import type { CSSProperties } from "react";
import colors from "../../libs/colors";
import { composeHandlers, useHoveredKey } from "../../libs/hooks";
import * as Style from "../../libs/style";
import type { BreakdownSegment } from "../../types/results";
import { formatInt } from "../../utils/format";
import { useTooltip } from "../common/useTooltip";

// A breakdown as one stacked bar with a legend beneath listing every group, its code and share.
// Every run names itself in the app's tooltip on hover, the legend entries do the same on hover or
// focus, and a highlighted group quietens the rest. Sized to the width it's given, so it suits a
// band across the page.

/** A sliver of a group stays visible even when its share rounds to nothing. */
const MIN_RUN_WIDTH = 3;

const styles = {
  // Fills whatever width it's given, in a row or a column.
  root: {
    display: "flex",
    flexDirection: "column",
    gap: 7,
    flex: 1,
    minWidth: 0,
  },
  bar: {
    display: "flex",
    gap: 2,
    borderRadius: 5,
    overflow: "hidden",
    background: colors.surface0,
  },
  run: {
    height: "100%",
    minWidth: MIN_RUN_WIDTH,
    transition: "opacity 0.12s ease, filter 0.12s ease",
  },
  quiet: {
    opacity: 0.4,
  },
  hot: {
    filter: "saturate(1.15)",
  },
  legend: {
    display: "flex",
    flexWrap: "wrap",
    gap: "3px 12px",
    fontSize: 11.5,
    color: colors.textBody,
  },
  // A button with the chrome stripped, so the legend reads as text; the focus ring is drawn only
  // for keyboard focus.
  legendItem: {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "0 2px",
    border: "none",
    borderRadius: 4,
    background: "none",
    font: "inherit",
    color: "inherit",
    cursor: "default",
    transition: "opacity 0.12s ease",
  },
  legendPercent: {
    color: colors.textSecondary,
    fontVariantNumeric: "tabular-nums",
  },
} as const satisfies Record<string, CSSProperties>;

interface BreakdownBarProps {
  segments: BreakdownSegment[];
  /** What the bar breaks down, e.g. "Ancestry", for its accessible name. */
  label: string;
  /** The bar's thickness in px. */
  height?: number;
}

/** How a group is described everywhere it's named: the tooltip, the legend and the bar's label. */
const describe = (segment: BreakdownSegment) =>
  `${segment.label}: ${formatInt(segment.count)} participants (${Math.round(segment.percent)}%)`;

export default function BreakdownBar({ segments, label, height = 10 }: BreakdownBarProps) {
  const { hoveredKey, hoverProps } = useHoveredKey<string>();
  const quiet = (segment: BreakdownSegment) => hoveredKey !== null && hoveredKey !== segment.label;

  return (
    <div style={styles.root}>
      {/* The label carries the counts as well as the shares, so assistive technology gets
          everything the tooltips show. */}
      <div style={{ ...styles.bar, height }} role="img" aria-label={`${label} breakdown: ${segments.map(describe).join("; ")}`}>
        {segments.map((segment, index) => (
          <Run
            key={segment.label}
            segment={segment}
            index={index}
            quiet={quiet(segment)}
            hot={hoveredKey === segment.label}
            hoverProps={hoverProps(segment.label)}
          />
        ))}
      </div>
      {/* Each legend entry is a button that shows the run's tooltip on focus as well as hover, so
          the counts are reachable from the keyboard. */}
      <div style={styles.legend}>
        {segments.map((segment) => (
          <LegendEntry key={segment.label} segment={segment} quiet={quiet(segment)} hoverProps={hoverProps(segment.label)} />
        ))}
      </div>
    </div>
  );
}

interface HoverProps {
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

interface RunProps {
  segment: BreakdownSegment;
  index: number;
  quiet: boolean;
  hot: boolean;
  hoverProps: HoverProps;
}

/** One group's run of the bar, with the app's tooltip naming it and its count on hover. */
function Run({ segment, index, quiet, hot, hoverProps }: RunProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const tooltip = useTooltip(ref, describe(segment));

  return (
    <span
      ref={ref}
      className="animate-grow-x"
      style={{
        ...styles.run,
        flex: `${segment.count || 1} 0 ${MIN_RUN_WIDTH}px`,
        background: segment.color,
        animationDelay: `${index * 0.06}s`,
        ...(quiet ? styles.quiet : undefined),
        ...(hot ? styles.hot : undefined),
      }}
      // The tooltip's own wiring, plus this group's highlight across the bar and legend.
      {...composeHandlers(tooltip.anchorProps, hoverProps)}
    >
      {tooltip.bubble}
    </span>
  );
}

interface LegendEntryProps {
  segment: BreakdownSegment;
  quiet: boolean;
  hoverProps: HoverProps;
}

/**
 * One group in the legend: its dot, code and share, as a button so it can take focus. Hovering or
 * focusing it highlights the group's run and shows the same tooltip the run does.
 */
function LegendEntry({ segment, quiet, hoverProps }: LegendEntryProps) {
  const ref = useRef<HTMLButtonElement>(null);
  const tooltip = useTooltip(ref, describe(segment));

  return (
    <button
      ref={ref}
      type="button"
      aria-label={describe(segment)}
      style={{
        ...styles.legendItem,
        ...(quiet ? styles.quiet : undefined),
        ...(tooltip.keyboardFocused ? Style.elements.tooltipIconFocusRing : undefined),
      }}
      // The tooltip's own wiring, plus the group highlight on hover and on focus alike. The
      // highlight follows the tooltip's rule: it stays while either keyboard focus or the
      // pointer remains, so it isn't lost when the pointer leaves a focused entry.
      {...composeHandlers(tooltip.anchorProps, {
        onMouseEnter: hoverProps.onMouseEnter,
        onMouseLeave: () => {
          if (!tooltip.keyboardFocused) hoverProps.onMouseLeave();
        },
        onFocus: hoverProps.onMouseEnter,
        onBlur: () => {
          if (!tooltip.hovered) hoverProps.onMouseLeave();
        },
      })}
    >
      <span style={Style.colorDot(segment.color, 8)} aria-hidden="true" />
      {segment.label}
      <span style={styles.legendPercent}>{Math.round(segment.percent)}%</span>
      {tooltip.bubble}
    </button>
  );
}
